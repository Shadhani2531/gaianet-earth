import json
import os
import random
import logging
import math
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Cache variables
_ndvi_cache = None
_last_fetch_time = None
CACHE_EXPIRY = 86400  # 1 day

PROCESSED_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')
NDVI_DATA_FILE = os.path.join(PROCESSED_DATA_DIR, 'ndvi.json')

# --- Real NASA MODIS NDVI (ORNL DAAC) --------------------------------------
# Source: ORNL DAAC "MODIS and VIIRS Land Product Subsets RESTful Web
# Service" (https://doi.org/10.3334/ORNLDAAC/1600). No authentication
# required. Product MOD13Q1 = MODIS Terra 16-day NDVI composite, 250m
# resolution. NDVI values are returned scaled by 10000 per the product's
# documented scale factor (raw 4517 -> NDVI 0.4517).
_ORNL_MODIS_BASE = "https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset"
_ndvi_point_cache: Dict[str, Any] = {}  # key: "lat,lon,date" -> {value, fetched_at}


def _to_modis_date(dt: datetime) -> str:
    """Convert a datetime to MODIS 'A-format' date: A + 4-digit year + 3-digit day-of-year."""
    return f"A{dt.year}{dt.timetuple().tm_yday:03d}"


def _fetch_real_modis_ndvi(lat: float, lon: float, dt: datetime) -> Optional[float]:
    """
    Query the real ORNL DAAC MODIS subset service for the NDVI value
    closest to (lat, lon, dt). Returns a float in [-1, 1], or None if the
    service is unreachable or has no valid pixel for this point/date
    (e.g. permanent cloud cover, ocean, or a date outside MODIS coverage
    which begins February 2000).
    """
    cache_key = f"{round(lat, 2)},{round(lon, 2)},{dt.strftime('%Y-%m')}"
    cached = _ndvi_point_cache.get(cache_key)
    if cached and (datetime.now(timezone.utc) - cached["fetched_at"]) < timedelta(hours=24):
        return cached["value"]

    if dt < datetime(2000, 2, 24, tzinfo=timezone.utc):
        return None  # before MODIS Terra coverage begins

    modis_date = _to_modis_date(dt)
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
        logger.warning(f"ORNL DAAC MODIS NDVI fetch failed for ({lat},{lon},{modis_date}): {e}")
        return None


def get_ndvi_at_location(lat: float, lon: float, date_str: str = None) -> Dict[str, Any]:
    """
    Real NDVI value for a specific point and date, from NASA MODIS
    (via ORNL DAAC's MOD13Q1 subset service). Falls back to a clearly
    labeled biome/season ESTIMATE only if the real service is unreachable
    or returns no data for this point (e.g. persistent cloud cover) —
    the fallback is never presented as real satellite data.
    """
    if date_str:
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)

    real_ndvi = _fetch_real_modis_ndvi(lat, lon, dt)

    if real_ndvi is not None:
        ndvi = real_ndvi
        source = "NASA MODIS Terra (MOD13Q1, via ORNL DAAC)"
        data_source = "real_modis"
    else:
        # Honest fallback: biome/season estimate, clearly labeled as such.
        ndvi = _estimate_ndvi_by_biome(lat, lon, dt)
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
        "timestamp": dt.isoformat(),
        "source": source,
        "data_source": data_source,
    }


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

def get_vegetation_geojson() -> Dict[str, Any]:
    global _ndvi_cache, _last_fetch_time
    
    now = datetime.now(timezone.utc)
    
    if _ndvi_cache and _last_fetch_time:
        if (now - _last_fetch_time).total_seconds() < CACHE_EXPIRY:
            return _ndvi_cache
            
    try:
        features = []
        real_count = 0
        fallback_count = 0
        step = 10 # Coarser grid for the GeoJSON overview if imagery is used
        for lat in range(-60, 80, step):
            for lon in range(-180, 180, step):
                data = get_ndvi_at_location(lat, lon)
                if data["data_source"] == "real_modis":
                    real_count += 1
                else:
                    fallback_count += 1
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {"value": data["ndvi"], "ndvi": data["ndvi"], "type": "vegetation",
                                   "data_source": data["data_source"]}
                })
        
        # Honest label: this grid is a MIX of real MODIS pixels and biome
        # estimates (oceans, persistent cloud cover, and API timeouts fall
        # back to the estimate) — never claim 100% real without checking.
        real_pct = round(100 * real_count / max(1, real_count + fallback_count))
        dataset = {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "source": f"NASA MODIS Terra (MOD13Q1, via ORNL DAAC) — {real_pct}% real satellite pixels, remainder estimated where MODIS had no valid data (ocean/cloud/timeout)",
                "real_pixel_count": real_count,
                "estimated_pixel_count": fallback_count,
                "timestamp": now.isoformat()
            }
        }
        _ndvi_cache = dataset
        _last_fetch_time = now
        return dataset
        
    except Exception as e:
        logger.error(f"Failed to generate vegetation data: {e}")
        return {"type": "FeatureCollection", "features": []}
