import random
import logging
import math
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

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
                "current": "temperature_2m,precipitation,cloud_cover",
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


def get_rainfall_geojson() -> Dict[str, Any]:
    grid = _fetch_global_grid_conditions()
    if not grid:
        return {"type": "FeatureCollection", "features": [],
                "metadata": {"source": "Open-Meteo", "status": "unavailable"}}

    features = []
    for r in grid["readings"]:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {"value": float(r["precip"]), "type": "rainfall", "data_source": "real_openmeteo"}
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "Open-Meteo (real current precipitation, mm in the last hour)",
            "timestamp": grid["fetched_at"].isoformat()
        }
    }


def get_weather_conditions_geojson() -> Dict[str, Any]:
    grid = _fetch_global_grid_conditions()
    if not grid:
        return {"type": "FeatureCollection", "features": [],
                "metadata": {"source": "Open-Meteo", "status": "unavailable"}}

    features = []
    for r in grid["readings"]:
        if r.get("cloud_cover") is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {"value": float(r["cloud_cover"]), "type": "weather_conditions", "data_source": "real_openmeteo"}
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "Open-Meteo (real current cloud cover, %)",
            "timestamp": grid["fetched_at"].isoformat()
        }
    }

def get_location_climate(lat: float, lon: float) -> Dict[str, Any]:
    """Provides time-series data using live Open-Meteo data."""
    history, is_real = get_live_climate_trends(lat, lon)
    
    # Calculate current anomaly (vs last 6 months avg)
    all_temps: List[float] = [float(h["avg_temp_c"]) for h in history if h["avg_temp_c"] != 0]
    avg_6m = sum(all_temps) / len(all_temps) if all_temps else 20.0
    current_temp = float(history[-1]["avg_temp_c"]) if history else 20.0
    anomaly = round(current_temp - avg_6m, 2)

    return {
        "location": {"lat": lat, "lon": lon},
        "historical_trends": history,
        "current_anomaly": float(anomaly),
        "source": "Open-Meteo Live API" if is_real else "Estimated (Open-Meteo unavailable — seasonal/latitude model used instead)",
        "data_source": "real_openmeteo" if is_real else "estimated_fallback"
    }
