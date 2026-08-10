"""
Alert summary service — powers the Planetary Health OS browser extension's
background monitoring loop (see extension/background.js).

Deliberately returns a SMALL payload (a handful of numbers), not raw
GeoJSON. The extension's MV3 service worker wakes briefly on a
chrome.alarms tick and must finish its fetch before Chrome can suspend it
again — shipping the full wildfire/station feed here would defeat that
and duplicate work the /wildfires and /stations-with-readings endpoints
already do for the main map.

Reuses the existing real-data clients rather than adding a new upstream
integration:
  - nasa_firms.get_wildfires_geojson()      (NASA FIRMS, already cached)
  - openaq_client.get_stations_with_readings() (OpenAQ v3, already cached)

Like the rest of this backend, this never fabricates a reading. If no
station has real data within the radius, aqi_max is null with an honest
status — not defaulted to "safe".
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services import nasa_firms, openaq_client

logger = logging.getLogger(__name__)

# How many independent fire detections within the radius count as a
# "cluster" worth alerting on, vs. one or two isolated/likely-false-positive
# hotspots.
FIRE_CLUSTER_THRESHOLD = 3


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers. Duplicated (not imported) from
    nasa_firms.py's private helper deliberately — that one is module-private
    (leading underscore) and this module shouldn't reach into another
    service's internals for a two-line formula."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# EPA PM2.5 -> US AQI breakpoints (24-hour, µg/m^3 -> AQI 0-500). Public
# formula, not fabricated: https://www.airnow.gov/aqi/aqi-calculator-concentration/
_PM25_BREAKPOINTS = [
    (0.0, 12.0, 0, 50),
    (12.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 150.4, 151, 200),
    (150.5, 250.4, 201, 300),
    (250.5, 350.4, 301, 400),
    (350.5, 500.4, 401, 500),
]


def _pm25_to_aqi(pm25: float) -> Optional[int]:
    """Converts a PM2.5 concentration to a US AQI value via the standard
    EPA piecewise-linear breakpoint formula. Returns None outside the
    defined range rather than extrapolating a made-up number."""
    for c_lo, c_hi, i_lo, i_hi in _PM25_BREAKPOINTS:
        if c_lo <= pm25 <= c_hi:
            return round(((i_hi - i_lo) / (c_hi - c_lo)) * (pm25 - c_lo) + i_lo)
    if pm25 > _PM25_BREAKPOINTS[-1][1]:
        return 500  # beyond the last defined breakpoint — cap, don't extrapolate
    return None


def get_alert_summary(lat: float, lon: float, radius_km: float = 50.0) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    # OpenAQ's radius filter caps at 25km server-side (see
    # openaq_client._OPENAQ_MAX_RADIUS_M) — smaller than the up-to-500km
    # this endpoint accepts for the fire search. Surfacing the actual
    # searched radius rather than silently searching less than the
    # caller asked for and calling it the same thing.
    aqi_search_radius_km = min(radius_km, 25.0)
    result: Dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "aqi_search_radius_km": aqi_search_radius_km,
        "generated_at": now.isoformat(),
        "aqi_max": None,
        "aqi_station_distance_km": None,
        "fire_count": 0,
        "fire_cluster_detected": False,
        "nearest_fire_distance_km": None,
        "data_source": {"fires": "unavailable", "air_quality": "unavailable"},
    }

    # --- Wildfires (NASA FIRMS) ---
    try:
        wildfires = nasa_firms.get_wildfires_geojson()
        features = wildfires.get("features", [])
        nearby_distances = []
        for feature in features:
            coords = feature.get("geometry", {}).get("coordinates")
            if not coords or len(coords) < 2:
                continue
            fire_lon, fire_lat = coords[0], coords[1]
            distance = _haversine_km(lat, lon, fire_lat, fire_lon)
            if distance <= radius_km:
                nearby_distances.append(distance)

        result["fire_count"] = len(nearby_distances)
        result["fire_cluster_detected"] = len(nearby_distances) >= FIRE_CLUSTER_THRESHOLD
        if nearby_distances:
            result["nearest_fire_distance_km"] = round(min(nearby_distances), 1)
        result["data_source"]["fires"] = (
            "live" if wildfires.get("metadata", {}).get("status") == "success" else "cache_or_stale"
        )
    except Exception as e:
        logger.warning(f"Alert summary: FIRMS lookup failed: {e}")

    # --- Air quality (OpenAQ v3) ---
    # Uses get_stations_near() — a radius-scoped query — not
    # get_stations_with_readings(), which sweeps the top 100 stations
    # GLOBALLY and was the actual cause of /alerts/summary occasionally
    # taking 10-100+ seconds on a cold cache (100 individual OpenAQ
    # /latest calls, only a few of which were ever within range).
    try:
        stations = openaq_client.get_stations_near(lat, lon, radius_km)
        best_pm25 = None
        best_distance = None
        for station in stations:
            coords = station.get("coordinates") or {}
            s_lat, s_lon = coords.get("latitude"), coords.get("longitude")
            if s_lat is None or s_lon is None:
                continue
            distance = _haversine_km(lat, lon, s_lat, s_lon)
            if distance <= aqi_search_radius_km:
                pm25 = station.get("pm25")
                if pm25 is not None and (best_pm25 is None or pm25 > best_pm25):
                    best_pm25 = pm25
                    best_distance = distance

        if best_pm25 is not None:
            result["aqi_max"] = _pm25_to_aqi(best_pm25)
            result["aqi_station_distance_km"] = round(best_distance, 1)
            result["data_source"]["air_quality"] = "live"
        elif not openaq_client.has_api_key():
            result["data_source"]["air_quality"] = "missing_api_key"
        else:
            result["data_source"]["air_quality"] = "no_station_in_radius"
    except Exception as e:
        logger.warning(f"Alert summary: OpenAQ lookup failed: {e}")

    return result
