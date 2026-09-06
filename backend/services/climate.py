import random
import logging
import math
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

def _generate_fallback_data(lat: float, lon: float, months_back: int = 6) -> List[Dict[str, Any]]:
    """Synthetic fallback if API fails."""
    history = []
    now = datetime.now(timezone.utc)
    base_temp = 28.0 - (abs(lat) * 0.5) 
    
    for i in range(months_back - 1, -1, -1):
        month_date = now - timedelta(days=30 * i)
        month_idx = month_date.month
        seasonal_offset = 10.0 * math.sin((month_idx - 4) * (2 * math.pi / 12))
        if lat < 0: seasonal_offset *= -1
        
        temp = base_temp + seasonal_offset + random.uniform(-1, 1)
        rainfall = max(20, 150 - abs(lat) * 1.5) + random.uniform(0, 50)

        history.append({
            "month": month_date.strftime("%Y-%m"),
            "avg_temp_c": round(temp, 1),
            "total_rainfall_mm": round(max(0, rainfall), 1)
        })
    return history

def get_live_climate_trends(lat: float, lon: float, months_back: int = 6) -> tuple:
    """
    Fetches real historical climate data from Open-Meteo Archive API.
    Groups daily data into monthly summaries for the dashboard charts.

    Returns (history, is_real) — is_real is False whenever the synthetic
    fallback fired (rate limited or API error), so callers can label the
    response honestly instead of always claiming live data regardless of
    what actually happened.
    """
    # Archive has ~5 day lag, so we fetch up to 5 days ago
    end_date = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=30 * months_back)).strftime('%Y-%m-%d')
    
    url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={start_date}&end_date={end_date}&daily=temperature_2m_max,precipitation_sum&timezone=GMT"
    
    try:
        logger.info(f"Fetching Open-Meteo data for {lat},{lon}")
        response = requests.get(url, timeout=10)
        
        if response.status_code == 429:
            logger.warning("Open-Meteo Rate Limited. Using fallback.")
            return _generate_fallback_data(lat, lon, months_back), False
            
        response.raise_for_status()
        data = response.json()
        
        daily = data.get('daily', {})
        times = daily.get('time', [])
        temps = daily.get('temperature_2m_max', [])
        precip = daily.get('precipitation_sum', [])
        
        # Group by month
        monthly_stats: Dict[str, Dict[str, Any]] = {}
        for i in range(len(times)):
            month_key = times[i][:7] # YYYY-MM
            if month_key not in monthly_stats:
                monthly_stats[month_key] = {"temps": [], "precip": 0.0}
            
            if i < len(temps) and temps[i] is not None:
                val = temps[i]
                if isinstance(val, (int, float)):
                    monthly_stats[month_key]["temps"].append(float(val))
            if i < len(precip) and precip[i] is not None:
                p_val = precip[i]
                if isinstance(p_val, (int, float)):
                    monthly_stats[month_key]["precip"] += float(p_val)
        
        history: List[Dict[str, Any]] = []
        for month in sorted(monthly_stats.keys()):
            t_list: List[float] = monthly_stats[month]["temps"]
            avg_temp = sum(t_list) / len(t_list) if t_list else 0.0
            history.append({
                "month": month,
                "avg_temp_c": round(float(avg_temp), 1),
                "total_rainfall_mm": round(float(monthly_stats[month]["precip"]), 1)
            })
            
        return history, True
    except Exception as e:
        logger.error(f"Open-Meteo API Error: {e}. Falling back to simulation.")
        return _generate_fallback_data(lat, lon, months_back), False

GRID_STEP = 20  # Coarser grid for faster load
GRID_CACHE_EXPIRY = 3600  # 1 hour — genuinely current conditions, refresh hourly

_grid_conditions_cache: Dict[str, Any] = {"data": None, "fetched_at": None}


def _build_grid_points(step: int = GRID_STEP) -> List[tuple]:
    return [(lat, lon) for lat in range(-60, 80, step) for lon in range(-180, 180, step)]


def _expected_seasonal_temp(lat: float, month_idx: int) -> float:
    """
    A documented, transparent climatological baseline — used ONLY to turn a
    real current temperature reading into an anomaly. This is a simple
    latitude+season model, not a substitute for real temperature data, and
    is clearly labeled as a model in the response metadata below.
    """
    base_temp = 28.0 - (abs(lat) * 0.5)
    seasonal_offset = 10.0 * math.sin((month_idx - 4) * (2 * math.pi / 12))
    if lat < 0:
        seasonal_offset *= -1
    return base_temp + seasonal_offset


def _fetch_global_grid_conditions() -> Optional[Dict[str, Any]]:
    """
    Real current temperature + precipitation for a coarse global grid, in
    ONE Open-Meteo request — it supports up to 1000 locations per call via
    comma-separated coordinate lists, so this replaces what used to be a
    fabricated random.uniform() grid (and would otherwise have needed ~126
    separate sequential/parallel calls) with a single fast real request.
    Cached for an hour.
    """
    now = datetime.now(timezone.utc)
    cached = _grid_conditions_cache["data"]
    fetched_at = _grid_conditions_cache["fetched_at"]
    if cached and fetched_at and (now - fetched_at).total_seconds() < GRID_CACHE_EXPIRY:
        return cached

    grid_points = _build_grid_points()
    lat_str = ",".join(str(lat) for lat, lon in grid_points)
    lon_str = ",".join(str(lon) for lat, lon in grid_points)

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat_str,
                "longitude": lon_str,
                "current": "temperature_2m,precipitation,cloud_cover,wind_speed_10m,wind_direction_10m",
                "timezone": "GMT",
            },
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json()
        # A single-location request returns one JSON object; multi-location
        # returns a list — normalize to a list either way.
        if isinstance(results, dict):
            results = [results]

        readings = []
        for (lat, lon), result in zip(grid_points, results):
            current = result.get("current", {})
            temp = current.get("temperature_2m")
            if temp is None:
                continue
            readings.append({
                "lat": lat, "lon": lon,
                "temp": temp,
                "precip": current.get("precipitation") or 0.0,
                "cloud_cover": current.get("cloud_cover"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "wind_direction_deg": current.get("wind_direction_10m"),
            })

        dataset = {"readings": readings, "fetched_at": now}
        _grid_conditions_cache["data"] = dataset
        _grid_conditions_cache["fetched_at"] = now
        return dataset
    except Exception as e:
        logger.error(f"Failed to fetch global grid conditions from Open-Meteo: {e}")
        return None


def get_climate_geojson() -> Dict[str, Any]:
    grid = _fetch_global_grid_conditions()
    if not grid:
        return {"type": "FeatureCollection", "features": [],
                "metadata": {"source": "Open-Meteo", "status": "unavailable"}}

    month_idx = grid["fetched_at"].month
    features = []
    for r in grid["readings"]:
        baseline = _expected_seasonal_temp(r["lat"], month_idx)
        anomaly = round(r["temp"] - baseline, 2)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {"value": float(anomaly), "type": "climate", "data_source": "real_openmeteo"}
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "Open-Meteo (real current temperature); anomaly computed against a documented latitude/season baseline model — the temperature itself is real, the baseline is a transparent model, never a random value",
            "timestamp": grid["fetched_at"].isoformat()
        }
    }


# Fixed reference years — same as Temperature/Vegetation History, for a
# consistent story across all three. 2001 is the earliest since this is
# the shared convention across this project's history features (MODIS
# coverage begins Feb 2000; Open-Meteo's ERA5 archive itself goes back
# much further, but there's no reason for rainfall's reference years to
# differ from the other two history features).
_RAINFALL_HISTORY_REFERENCE_YEARS = [2001, 2005, 2010, 2015, 2020]
_rainfall_history_cache: Dict[str, Any] = {}
_RAINFALL_HISTORY_CACHE_HOURS = 24 * 30

# A year's ANNUAL SUM is only reported if at least this fraction of its
# days have real data. Unlike an average (NDVI/temperature), a SUM is
# directly biased by missing days — a handful of gaps silently
# understate the real total rather than just adding noise — so summing
# whatever real days happen to exist without a completeness floor could
# quietly misrepresent an incomplete year as if it were a full one.
_RAINFALL_MIN_COMPLETENESS = 0.90


def _latest_fully_completed_year(now: datetime) -> int:
    """
    Returns the most recent calendar year that has BOTH actually ended
    AND cleared Open-Meteo's archive publishing lag (~5 days, same lag
    used elsewhere in this file) — never the current, still-in-progress
    year. An annual total needs a full Jan 1 - Dec 31 of real data;
    reporting this year's partial total as if it were a complete annual
    figure would misrepresent it (e.g. flagging 2026 as "the latest
    year" in September 2026, when only ~8 months have actually happened).
    """
    candidate = now.year - 1
    while datetime(candidate, 12, 31, tzinfo=timezone.utc) + timedelta(days=5) > now:
        candidate -= 1
    return candidate


def get_rainfall_history(lat: float, lon: float) -> Dict[str, Any]:
    """
    Real ANNUAL precipitation totals (mm/year, Jan 1 - Dec 31 sum) at
    (lat, lon) for _RAINFALL_HISTORY_REFERENCE_YEARS plus the latest
    FULLY COMPLETED calendar year (see _latest_fully_completed_year —
    never the current, still-in-progress year).

    Deliberately an ANNUAL total rather than a fixed seasonal window
    (the approach used for NDVI's Jul-Aug comparison): rainfall
    seasonality varies enormously by region — India's monsoon,
    Australia's wet season, Finland's snow-dominated winter, and
    Brazil's basin patterns all follow completely different calendars —
    so no single fixed window would be a fair, globally meaningful
    comparison the way Jul-Aug reasonably works for NDVI. A full-year
    total sidesteps that entirely.

    Every value is a real sum over real Open-Meteo archive daily
    readings — never fabricated or interpolated. Because summing (unlike
    averaging) is directly biased by missing days, a year is only
    reported if at least _RAINFALL_MIN_COMPLETENESS of its days have
    real data; otherwise it's null/unavailable. days_used/days_expected
    are recorded either way for transparency. Cached per location; see
    _RAINFALL_HISTORY_CACHE_HOURS.
    """
    cache_key = f"{round(lat, 2)},{round(lon, 2)}"
    now = datetime.now(timezone.utc)
    cached = _rainfall_history_cache.get(cache_key)
    if cached and (now - cached["fetched_at"]).total_seconds() < _RAINFALL_HISTORY_CACHE_HOURS * 3600:
        return cached["result"]

    latest_year = _latest_fully_completed_year(now)
    target_years = sorted(set(_RAINFALL_HISTORY_REFERENCE_YEARS + [latest_year]))

    def fetch_year(year: int) -> Dict[str, Any]:
        try:
            start = datetime(year, 1, 1, tzinfo=timezone.utc)
            end = datetime(year, 12, 31, tzinfo=timezone.utc)
            days_expected = (end - start).days + 1  # 365 or 366

            url = (
                f"https://archive-api.open-meteo.com/v1/archive"
                f"?latitude={lat}&longitude={lon}"
                f"&start_date={start.strftime('%Y-%m-%d')}"
                f"&end_date={end.strftime('%Y-%m-%d')}"
                f"&daily=precipitation_sum&timezone=GMT"
            )
            resp = requests.get(url, timeout=15)
            logger.info(f"Rainfall history: year {year} annual request ({start.date()}..{end.date()}) -> HTTP {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
            daily_values = data.get("daily", {}).get("precipitation_sum", [])
            real_values = [v for v in daily_values if v is not None]
            days_used = len(real_values)

            completeness = (days_used / days_expected) if days_expected else 0
            if completeness < _RAINFALL_MIN_COMPLETENESS:
                logger.info(
                    f"Rainfall history: year {year} only {days_used}/{days_expected} days real "
                    f"({completeness:.0%}) — below completeness threshold for ({lat},{lon})"
                )
                return {"year": year, "annual_mm": None, "days_used": days_used,
                         "days_expected": days_expected, "data_source": "unavailable"}

            annual_total = round(sum(real_values), 1)
            logger.info(f"Rainfall history: year {year} annual total {annual_total}mm from {days_used}/{days_expected} real days for ({lat},{lon})")
            return {"year": year, "annual_mm": annual_total, "days_used": days_used,
                     "days_expected": days_expected, "data_source": "real_openmeteo"}
        except Exception as e:
            logger.warning(f"Rainfall history: year {year} raised an unexpected error for ({lat},{lon}): {e}")
            return {"year": year, "annual_mm": None, "days_used": 0, "days_expected": None, "data_source": "unavailable"}

    # A handful of years (<=6), run concurrently — same reasoning as the
    # other two history features.
    with ThreadPoolExecutor(max_workers=6) as executor:
        years_out = list(executor.map(fetch_year, target_years))

    result = {
        "lat": lat,
        "lon": lon,
        "metric": "annual_precipitation_mm",
        "years": years_out,
    }
    _rainfall_history_cache[cache_key] = {"result": result, "fetched_at": now}
    return result


def get_location_climate(lat: float, lon: float) -> Dict[str, Any]:
    """Provides time-series data using live Open-Meteo data."""
    history, is_real = get_live_climate_trends(lat, lon)

    # Anomaly = real current temperature vs. a climatological baseline for
    # this latitude and month — the same _expected_seasonal_temp() model
    # get_climate_geojson() (the map layer) already uses. This used to
    # compare against a naive 6-month rolling average instead, which
    # mostly just measures the ordinary seasonal cycle rather than a real
    # anomaly: a summer reading compared against a 6-month average that
    # includes winter months produces a large number that isn't unusual
    # at all, just seasonal. Fixed to use the real baseline model so this
    # stat and the map layer's anomaly mean the same thing.
    current_temp = float(history[-1]["avg_temp_c"]) if history and history[-1]["avg_temp_c"] != 0 else 20.0
    current_month = datetime.now(timezone.utc).month
    baseline = _expected_seasonal_temp(lat, current_month)
    anomaly = round(current_temp - baseline, 2)

    return {
        "location": {"lat": lat, "lon": lon},
        "historical_trends": history,
        "current_anomaly": float(anomaly),
        "source": "Open-Meteo Live API" if is_real else "Estimated (Open-Meteo unavailable — seasonal/latitude model used instead)",
        "data_source": "real_openmeteo" if is_real else "estimated_fallback"
    }


# Fixed reference years for the Temperature History chart — same years as
# the Vegetation History chart for a consistent story across both, though
# unlike MODIS, Open-Meteo's ERA5-based archive has real daily data
# continuously back to 1940, so there's no "is this year's data published
# yet" concern the way there is for MODIS composites.
_TEMP_HISTORY_REFERENCE_YEARS = [2001, 2005, 2010, 2015, 2020]
_temp_history_cache: Dict[str, Any] = {}
_TEMP_HISTORY_CACHE_HOURS = 24 * 30


def get_temperature_history(lat: float, lon: float) -> Dict[str, Any]:
    """
    Real historical temperature at (lat, lon) for _TEMP_HISTORY_REFERENCE_
    YEARS plus the current year, each matched to the SAME ~7-day window
    around today's month/day (so a summer year isn't compared to a winter
    one). Each year's value is the real average of temperature_2m_max
    across that window from Open-Meteo's archive API (ERA5 reanalysis) —
    or explicitly "unavailable" if the request fails/returns no valid
    days, never fabricated or interpolated. Cached per location for
    _TEMP_HISTORY_CACHE_HOURS, since fixed past years never change (only
    the current year's window could ever need a refresh).
    """
    cache_key = f"{round(lat, 2)},{round(lon, 2)}"
    now = datetime.now(timezone.utc)
    cached = _temp_history_cache.get(cache_key)
    if cached and (now - cached["fetched_at"]).total_seconds() < _TEMP_HISTORY_CACHE_HOURS * 3600:
        return cached["result"]

    ref_month, ref_day = now.month, now.day
    target_years = sorted(set(_TEMP_HISTORY_REFERENCE_YEARS + [now.year]))

    def fetch_year(year: int) -> Dict[str, Any]:
        try:
            try:
                center = datetime(year, ref_month, ref_day, tzinfo=timezone.utc)
            except ValueError:
                # e.g. reference day is Feb 29 and `year` isn't a leap year
                center = datetime(year, ref_month, 28, tzinfo=timezone.utc)

            window_start = center - timedelta(days=3)
            window_end = center + timedelta(days=3)

            # Archive has ~5 day lag (same as get_live_climate_trends
            # above). BUG FIX: previously this only clamped window_end
            # down to (now - 5 days) while leaving window_start at
            # (center - 3 days) — for the CURRENT year, center IS "today",
            # so window_start (today - 3) was always AFTER the clamped
            # window_end (today - 5), making the window invalid every
            # single time, unconditionally — not a real data gap, just
            # this bug. Fix: shift the WHOLE window earlier (keeping its
            # ~7-day width) when it would otherwise reach beyond the lag,
            # rather than only pulling in one edge.
            latest_allowed = now - timedelta(days=5)
            if window_end > latest_allowed:
                window_end = latest_allowed
                window_start = window_end - timedelta(days=6)

            url = (
                f"https://archive-api.open-meteo.com/v1/archive"
                f"?latitude={lat}&longitude={lon}"
                f"&start_date={window_start.strftime('%Y-%m-%d')}"
                f"&end_date={window_end.strftime('%Y-%m-%d')}"
                f"&daily=temperature_2m_max&timezone=GMT"
            )
            resp = requests.get(url, timeout=10)
            logger.info(f"Temp history: year {year} window {window_start.date()}..{window_end.date()} -> HTTP {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
            temps = [t for t in data.get("daily", {}).get("temperature_2m_max", []) if t is not None]

            if not temps:
                logger.info(f"Temp history: year {year} returned no valid daily values for ({lat},{lon})")
                return {"year": year, "avg_temp_c": None, "data_source": "unavailable"}

            avg_temp = round(sum(temps) / len(temps), 1)
            return {"year": year, "avg_temp_c": avg_temp, "data_source": "real_openmeteo"}
        except Exception as e:
            logger.warning(f"Temp history: year {year} raised an unexpected error for ({lat},{lon}): {e}")
            return {"year": year, "avg_temp_c": None, "data_source": "unavailable"}

    # A handful of years (<=6), run concurrently — same reasoning as the
    # Vegetation History fetch: keeps click-to-chart latency reasonable
    # without approaching anything like the removed 504-point grid's scale.
    with ThreadPoolExecutor(max_workers=6) as executor:
        years_out = list(executor.map(fetch_year, target_years))

    result = {
        "lat": lat,
        "lon": lon,
        "reference_period": f"{ref_month:02d}-{ref_day:02d} (+/-3 days)",
        "years": years_out,
    }
    _temp_history_cache[cache_key] = {"result": result, "fetched_at": now}
    return result
