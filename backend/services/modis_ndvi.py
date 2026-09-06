import json
import os
import random
import logging
import math
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

PROCESSED_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')
NDVI_DATA_FILE = os.path.join(PROCESSED_DATA_DIR, 'ndvi.json')

# --- Real NASA MODIS NDVI (ORNL DAAC) --------------------------------------
# Source: ORNL DAAC "MODIS and VIIRS Land Product Subsets RESTful Web
# Service" (https://doi.org/10.3334/ORNLDAAC/1600). No authentication
# required. Product MOD13Q1 = MODIS Terra 16-day NDVI composite, 250m
# resolution. NDVI values are returned scaled by 10000 per the product's
# documented scale factor (raw 4517 -> NDVI 0.4517).
_ORNL_MODIS_BASE = "https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset"
_ORNL_MODIS_DATES_BASE = "https://modis.ornl.gov/rst/api/v1/MOD13Q1/dates"
_ndvi_point_cache: Dict[str, Any] = {}  # key: "lat,lon,modis_date" -> {value, fetched_at}

# Note: this module previously also served a global 504-point vegetation
# grid (get_vegetation_geojson) for a blocky raster overlay on the globe.
# That grid — and its VEGETATION_GRID_ENABLED gate — was removed entirely
# per explicit request: the 10°-grid tiling never looked right, and the
# per-location value + Vegetation History chart in the Insight card (now
# gated by the same "Vegetation (NDVI)" toggle) replace it instead.

# --- Available-dates lookup --------------------------------------------------
# key: "lat,lon" (rounded) -> {"dates": [(calendar_date: datetime, modis_date: str), ...], "fetched_at": datetime}
_dates_cache: Dict[str, Any] = {}
_DATES_CACHE_HOURS = 24


def _get_available_dates(lat: float, lon: float) -> Optional[list]:
    """
    Returns the cached/fresh list of ALL published (calendar_date, modis_date)
    tuples for this (lat, lon) from ORNL DAAC's /MOD13Q1/dates endpoint — not
    filtered to any date range, since the endpoint itself returns the full
    history for a point in one call. Shared by both the "latest available"
    lookup (used by the live single-location value) and the historical-years
    lookup, so a location's dates are only ever fetched once per cache
    window, not once per use case. Returns None if the request fails.
    """
    cache_key = f"{round(lat, 2)},{round(lon, 2)}"
    now = datetime.now(timezone.utc)
    cached = _dates_cache.get(cache_key)

    if cached and (now - cached["fetched_at"]).total_seconds() < _DATES_CACHE_HOURS * 3600:
        return cached["dates"]

    try:
        resp = requests.get(
            _ORNL_MODIS_DATES_BASE,
            params={"latitude": lat, "longitude": lon},
            headers={"Accept": "application/json"},
            timeout=10,
        )
        logger.info(f"NDVI: /dates request for ({lat},{lon}) -> HTTP {resp.status_code}")
        resp.raise_for_status()
        payload = resp.json()
        raw_dates = payload.get("dates", [])

        parsed_dates = []
        for entry in raw_dates:
            try:
                cal_date = datetime.strptime(entry["calendar_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                parsed_dates.append((cal_date, entry["modis_date"]))
            except Exception:
                continue  # skip any malformed entry rather than fail the whole lookup

        _dates_cache[cache_key] = {"dates": parsed_dates, "fetched_at": now}
        return parsed_dates
    except Exception as e:
        logger.warning(f"NDVI: /dates request failed for ({lat},{lon}): {e}")
        return None


def _get_latest_available_modis_date(lat: float, lon: float, before_dt: datetime) -> Optional[str]:
    """
    Returns the exact modis_date string (e.g. "A2026072") for the latest
    composite on or before before_dt — never a date computed/guessed
    locally. Returns None if the dates lookup fails or no published date
    exists on or before before_dt. (Unchanged behavior/logging from the
    original version — now just backed by the shared _get_available_dates.)
    """
    parsed_dates = _get_available_dates(lat, lon)
    if parsed_dates is None:
        return None

    candidates = [(cal_date, modis_date) for (cal_date, modis_date) in parsed_dates if cal_date <= before_dt]
    if not candidates:
        logger.warning(f"NDVI: /dates for ({lat},{lon}) returned no composite on or before {before_dt.date()}")
        return None

    candidates.sort(key=lambda c: c[0])
    latest_cal_date, latest_modis_date = candidates[-1]
    logger.info(f"NDVI: latest available MOD13Q1 date for ({lat},{lon}) on/before {before_dt.date()} is {latest_modis_date} ({latest_cal_date.date()})")
    return latest_modis_date


def _to_modis_date(dt: datetime) -> str:
    """Convert a datetime to MODIS 'A-format' date: A + 4-digit year + 3-digit day-of-year."""
    return f"A{dt.year}{dt.timetuple().tm_yday:03d}"


def _fetch_subset_ndvi_value(lat: float, lon: float, modis_date: str) -> Optional[float]:
    """
    Low-level: one real ORNL DAAC /MOD13Q1/subset call for an EXACT,
    already-resolved modis_date string, parsed to a single NDVI float.
    Shared by both the live single-location lookup (_fetch_real_modis_ndvi)
    and the historical-years lookup (get_ndvi_history), so both use the
    identical request/parse/cache path — no duplicated logic to drift out
    of sync. Returns None on request failure or no valid pixel for this
    date/location (e.g. persistent cloud cover).
    """
    cache_key = f"{round(lat, 2)},{round(lon, 2)},{modis_date}"
    cached = _ndvi_point_cache.get(cache_key)
    if cached and (datetime.now(timezone.utc) - cached["fetched_at"]) < timedelta(hours=24):
        return cached["value"]

    try:
        resp = requests.get(
            _ORNL_MODIS_BASE,
            params={
                "latitude": lat,
                "longitude": lon,
                "startDate": modis_date,
                "endDate": modis_date,
                "kmAboveBelow": 0,
                "kmLeftRight": 0,
            },
            headers={"Accept": "application/json"},
            timeout=10,
        )
        logger.info(f"NDVI: /subset request for ({lat},{lon}) date={modis_date} -> HTTP {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()

        for band_entry in data.get("subset", []):
            if band_entry.get("band") == "250m_16_days_NDVI":
                raw_values = [v for v in band_entry.get("data", []) if v is not None]
                if not raw_values:
                    return None
                # Center pixel is the requested point at kmAboveBelow=0/kmLeftRight=0
                # (a 1x1 subset), so just average whatever's returned.
                avg_raw = sum(raw_values) / len(raw_values)
                ndvi_value = round(avg_raw * 0.0001, 4)
                _ndvi_point_cache[cache_key] = {
                    "value": ndvi_value,
                    "fetched_at": datetime.now(timezone.utc),
                }
                return ndvi_value
        return None
    except Exception as e:
        logger.warning(f"NDVI: /subset request failed for ({lat},{lon},{modis_date}): {e}")
        return None


def _fetch_real_modis_ndvi(lat: float, lon: float, requested_dt: datetime) -> Optional[float]:
    """
    Query the real ORNL DAAC MODIS subset service for the NDVI value at
    (lat, lon), for the latest actually-published composite on or before
    requested_dt (resolved via /MOD13Q1/dates — never a locally-guessed
    date). Returns a float in [-1, 1], or None if no published date is
    found, or the subset request itself fails/has no valid pixel (e.g.
    permanent cloud cover, ocean). (Unchanged behavior/logging from the
    original version — now just a thin wrapper over the shared
    _fetch_subset_ndvi_value.)
    """
    if requested_dt < datetime(2000, 2, 24, tzinfo=timezone.utc):
        return None  # before MODIS Terra coverage begins

    modis_date = _get_latest_available_modis_date(lat, lon, requested_dt)
    if modis_date is None:
        return None  # /dates lookup failed, or nothing published yet for this point

    return _fetch_subset_ndvi_value(lat, lon, modis_date)


def get_ndvi_at_location(lat: float, lon: float, date_str: str = None) -> Dict[str, Any]:
    """
    Real NDVI value for a specific point, for the latest MOD13Q1 composite
    actually published on or before the requested date (from NASA MODIS via
    ORNL DAAC — see _get_latest_available_modis_date). Falls back to a
    clearly labeled biome/season ESTIMATE only if the real service is
    unreachable or has no published data for this point — the fallback is
    never presented as real satellite data.
    """
    if date_str:
        try:
            requested_dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if requested_dt.tzinfo is None:
                requested_dt = requested_dt.replace(tzinfo=timezone.utc)
        except Exception:
            requested_dt = datetime.now(timezone.utc)
    else:
        requested_dt = datetime.now(timezone.utc)

    real_ndvi = _fetch_real_modis_ndvi(lat, lon, requested_dt)

    if real_ndvi is not None:
        ndvi = real_ndvi
        source = "NASA MODIS Terra (MOD13Q1, via ORNL DAAC)"
        data_source = "real_modis"
    else:
        # Honest fallback: biome/season estimate, clearly labeled as such.
        ndvi = _estimate_ndvi_by_biome(lat, lon, requested_dt)
        source = "Estimated (biome/season model — real MODIS data unavailable for this point/date)"
        data_source = "estimated_fallback"

    # Categorization
    if ndvi > 0.7: health, risk = "Excellent", "Low"
    elif ndvi > 0.4: health, risk = "Good", "Moderate"
    elif ndvi > 0.2: health, risk = "Sparse", "High"
    else: health, risk = "Critical/Barren", "Very High"

    return {
        "lat": lat,
        "lon": lon,
        "ndvi": round(ndvi, 3),
        "health": health,
        "wildfire_risk": risk,
        "timestamp": requested_dt.isoformat(),
        "source": source,
        "data_source": data_source,
    }


# Historical years never change once a real MOD13Q1 composite is published
# for them — only the "current/latest available year" entry could ever get
# a newer composite later. 30 days is generous and safe either way: it
# means repeated clicks on the same location don't re-hit ORNL DAAC for
# weeks, and even the "latest year" entry only goes stale for at most a
# month, well inside one 16-day compositing cycle's worth of slack.
_history_cache: Dict[str, Any] = {}
_HISTORY_CACHE_HOURS = 24 * 30

# Fixed reference years for the Vegetation History chart. 2001 is the
# earliest included since MOD13Q1 (Terra) coverage only begins Feb 2000 —
# an earlier year like 1990 would have zero real MODIS data to show,
# which is why it's deliberately excluded rather than left to silently
# return "unavailable" for every location.
_HISTORY_REFERENCE_YEARS = [2001, 2005, 2010, 2015, 2020]


def get_ndvi_history(lat: float, lon: float) -> Dict[str, Any]:
    """
    Real historical NDVI at (lat, lon) for _HISTORY_REFERENCE_YEARS plus
    whichever year the current "latest available" composite falls in.

    Each year's value is the MEAN of every real MOD13Q1 composite
    published within a fixed July 1 - August 31 window that year — not a
    single composite. A single 16-day snapshot can be strongly skewed by
    monsoon timing, crop cycles, irrigation, or one unusually green/dry
    period, which would misrepresent a real seasonal swing as a
    directional vegetation-cover trend. Averaging multiple real
    observations across the same fixed window is more scientifically
    defensible than one snapshot per year.

    Every averaged value comes only from real composites (via the same
    _fetch_subset_ndvi_value the live single-location lookup uses) —
    never fabricated, estimated, or interpolated. If a year has zero
    valid real composites in the window, it's returned as
    data_source: "unavailable" with ndvi: null, leaving a real gap in
    the chart rather than guessing. observations_used records exactly
    how many real composites went into each year's mean, so a mean from
    1 composite and a mean from 4 are distinguishable if needed later.

    Cached per location; see _HISTORY_CACHE_HOURS. Does NOT touch the
    global 504-point vegetation grid or increase its resolution — only
    runs for the one location a user clicks on, and reuses the /dates
    list a prior get_ndvi_at_location() call for the same point will
    likely have already cached.
    """
    cache_key = f"{round(lat, 2)},{round(lon, 2)}"
    now = datetime.now(timezone.utc)
    cached = _history_cache.get(cache_key)
    if cached and (now - cached["fetched_at"]).total_seconds() < _HISTORY_CACHE_HOURS * 3600:
        return cached["result"]

    dates_list = _get_available_dates(lat, lon)
    if not dates_list:
        result = {
            "lat": lat, "lon": lon, "years": [],
            "error": "Could not retrieve MODIS composite dates for this location.",
        }
        _history_cache[cache_key] = {"result": result, "fetched_at": now}
        return result

    # "Latest available year" — the year of whichever real composite is
    # currently the most recent one published for this point (same
    # determination the live single-location lookup uses), just to decide
    # which extra year to add alongside the fixed reference years. The
    # actual averaging below always uses the fixed Jul-Aug window
    # regardless of which day this happens to land on.
    now_candidates = sorted([(cd, md) for (cd, md) in dates_list if cd <= now], key=lambda c: c[0])
    if not now_candidates:
        result = {
            "lat": lat, "lon": lon, "years": [],
            "error": "No published MODIS composite available up to the present for this location.",
        }
        _history_cache[cache_key] = {"result": result, "fetched_at": now}
        return result

    latest_year = now_candidates[-1][0].year
    target_years = sorted(set(_HISTORY_REFERENCE_YEARS + [latest_year]))

    def fetch_year(year: int) -> Dict[str, Any]:
        try:
            # Fixed calendar window, same for every year — July 1 to
            # August 31 — rather than anchored to "today's" date. A fixed
            # real-calendar window is what makes the years genuinely
            # comparable; composites that don't exist yet (e.g. late
            # August of the current year) simply won't appear in
            # dates_list, no special-casing needed.
            window_start = datetime(year, 7, 1, tzinfo=timezone.utc)
            window_end = datetime(year, 8, 31, tzinfo=timezone.utc)

            composites_in_window = [
                (cd, md) for (cd, md) in dates_list if window_start <= cd <= window_end
            ]

            if not composites_in_window:
                logger.info(f"NDVI history: year {year} has no published composite in the Jul-Aug window for ({lat},{lon})")
                return {"year": year, "ndvi": None, "observations_used": 0, "data_source": "unavailable"}

            real_values = []
            used_dates = []
            for cal_date, modis_date in composites_in_window:
                value = _fetch_subset_ndvi_value(lat, lon, modis_date)
                if value is not None:
                    real_values.append(value)
                    used_dates.append(modis_date)

            if not real_values:
                logger.info(f"NDVI history: year {year} had {len(composites_in_window)} composite(s) in window but 0 valid pixels for ({lat},{lon})")
                return {"year": year, "ndvi": None, "observations_used": 0, "data_source": "unavailable"}

            seasonal_mean = round(sum(real_values) / len(real_values), 4)
            logger.info(
                f"NDVI history: year {year} Jul-Aug seasonal mean {seasonal_mean} "
                f"from {len(real_values)}/{len(composites_in_window)} real composite(s) "
                f"({', '.join(used_dates)}) for ({lat},{lon})"
            )
            return {
                "year": year,
                "ndvi": seasonal_mean,
                "observations_used": len(real_values),
                "composites_available": len(composites_in_window),
                "data_source": "real_modis",
            }
        except Exception as e:
            # Never let one year's unexpected failure crash the whole
            # history request (and silently look identical to "every
            # year unavailable") — log the real exception so this is
            # diagnosable instead of guessed at.
            logger.warning(f"NDVI history: year {year} raised an unexpected error for ({lat},{lon}): {e}")
            return {"year": year, "ndvi": None, "observations_used": 0, "data_source": "unavailable"}

    # A handful of years (<=6), run concurrently so the chart doesn't take
    # too long to render — each year now does multiple real requests
    # internally (one per composite in its window, typically 3-4), still
    # nowhere near the scale of the removed 504-point grid.
    with ThreadPoolExecutor(max_workers=6) as executor:
        years_out = list(executor.map(fetch_year, target_years))

    result = {
        "lat": lat,
        "lon": lon,
        "reference_period": "07-01 to 08-31 (seasonal mean)",
        "years": years_out,
    }
    _history_cache[cache_key] = {"result": result, "fetched_at": now}
    return result


def _estimate_ndvi_by_biome(lat: float, lon: float, dt: datetime) -> float:
    """
    Fallback ONLY — biome/season-based NDVI estimate, used solely when the
    real MODIS service has no data for this point/date. Never labeled as
    real satellite data by callers of get_ndvi_at_location.
    """
    month = dt.month
    abs_lat = abs(lat)

    if abs_lat < 10:
        base = 0.85  # Tropical
    elif 15 < abs_lat < 30:
        base = 0.15  # Desert
    elif 35 < abs_lat < 60:
        base = 0.55  # Temperate
    else:
        base = 0.05  # Tundra/Ocean/Ice

    seasonal_offset = 0
    if 30 < lat < 70:
        seasonal_offset = 0.2 * math.sin((month - 4) * (math.pi / 6))
    elif -70 < lat < -30:
        seasonal_offset = 0.2 * math.sin((month + 2) * (math.pi / 6))

    return max(-0.1, min(0.98, base + seasonal_offset))
