"""
GaiaNet Earth — OpenAQ v3 client
File: backend/services/openaq_client.py

OpenAQ v1/v2 were retired January 31, 2025 and now return HTTP 410 Gone
for every request (confirmed via OpenAQ's own documentation). This
replaces the old broken v2 calls with real v3 API calls, which require a
free API key (https://explore.openaq.org).

Used by:
- /stations (existing endpoint, was silently broken — every call was
  hitting 410 and returning an empty list)
- /shi-global (new, Tab 6 country-level SHI heatmap)
"""

import os
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

_OPENAQ_BASE = "https://api.openaq.org/v3"

_locations_cache = {"data": None, "fetched_at": None}
_country_agg_cache = {"data": None, "fetched_at": None}
CACHE_HOURS = 6

# Captures the reason behind the most recent OpenAQ failure (rate limit,
# invalid key, timeout, etc.) so it can be surfaced through the API response
# — previously this only ever reached the server console via logger.error,
# meaning debugging Tab 6 required tailing backend logs every single time.
_last_openaq_error = None


def get_last_openaq_error() -> str | None:
    """The most recent real OpenAQ error message, or None if the last
    fetch succeeded. Cleared on the next successful fetch."""
    return _last_openaq_error


def _get_headers():
    api_key = os.environ.get("OPENAQ_API_KEY", "")
    return {"X-API-Key": api_key} if api_key else {}


def _has_api_key() -> bool:
    return bool(os.environ.get("OPENAQ_API_KEY", "").strip())


def has_api_key() -> bool:
    """Public accessor for _has_api_key(), for other services (e.g.
    alerts.py) that need to distinguish 'no key configured' from 'key
    configured but no station nearby' without reaching into this
    module's private helper."""
    return _has_api_key()


def get_stations(limit: int = 1000) -> List[Dict[str, Any]]:
    """
    Real OpenAQ v3 station list with PM2.5/PM10 sensors, each including
    a real country code (ISO 3166-1 alpha-2). Cached for 6 hours since
    station metadata doesn't change minute-to-minute.

    BUG FIX: OpenAQ v3's /locations endpoint hard-caps `limit` at 1000
    per page (docs.openaq.org/using-the-api/pagination) and rejects
    anything higher with a 422 Unprocessable Entity — no partial results,
    no silent clamping on their end. get_country_aqi_aggregate() was
    calling this with limit=2000, so every single Tab 6 (Global SHI)
    request failed at this very first step with a 422, before any of the
    per-station reading logic even ran. Clamped defensively here (same
    pattern as _OPENAQ_MAX_RADIUS_M below) so no caller can trigger this
    again by passing too high a value.
    """
    global _last_openaq_error
    limit = min(limit, 1000)
    now = datetime.now(timezone.utc)
    if (_locations_cache["data"] is not None and _locations_cache["fetched_at"]
            and (now - _locations_cache["fetched_at"]) < timedelta(hours=CACHE_HOURS)):
        return _locations_cache["data"]

    if not _has_api_key():
        logger.warning("OPENAQ_API_KEY not set — cannot fetch real OpenAQ v3 data. "
                        "Get a free key at https://explore.openaq.org and add it to backend/.env")
        _last_openaq_error = "OPENAQ_API_KEY not set"
        return []

    try:
        resp = requests.get(
            f"{_OPENAQ_BASE}/locations",
            params={"limit": limit, "parameters_id": [2]},  # 2 = PM2.5
            headers=_get_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        _locations_cache["data"] = results
        _locations_cache["fetched_at"] = now
        _last_openaq_error = None
        return results
    except Exception as e:
        logger.error(f"Failed to fetch OpenAQ v3 stations: {e}")
        _last_openaq_error = str(e)
        return _locations_cache["data"] if _locations_cache["data"] is not None else []


def _pm25_sensor_id(station: Dict[str, Any]) -> int | None:
    """Finds the sensor id (not location id) on a /locations-shaped station
    object that measures PM2.5 (parameter id 2). A station can have several
    sensors (PM2.5, PM10, O3, ...); this is what lets get_station_latest_pm25
    pick out the right one from a /latest response."""
    for s in station.get("sensors", []):
        if s.get("parameter", {}).get("id") == 2:
            return s.get("id")
    return None


def get_station_latest_pm25(location_id: int, pm25_sensor_id: int | None = None) -> float | None:
    """
    Real latest PM2.5 reading for a single station.

    BUG FIX: OpenAQ v3's /locations/{id}/latest response does NOT embed a
    "parameter" object per result (confirmed against OpenAQ's own docs,
    docs.openaq.org/resources/latest) — each result only carries a
    "sensorsId" foreign key, "value", "datetime", and "coordinates". The
    previous version of this function matched on
    `r.get("parameter", {}).get("id") == 2`, which is always False since
    that key never exists on a /latest result — meaning this silently
    returned None for every single station, every single call, since it
    was written. That's why Tab 6 (Global SHI) showed "Could not fetch
    real OpenAQ data" with no specific reason attached (the /locations
    list call itself succeeded fine; only the per-station reading lookup
    was broken), and why /stations-with-readings and /alerts/summary were
    quietly returning no real readings too.

    The correct match is against `sensorsId`, which requires knowing that
    station's PM2.5 sensor's id ahead of time — get it from the station's
    own /locations sensors[] entry via _pm25_sensor_id() before calling
    this, since a station can have several sensors for different
    pollutants and /latest doesn't say which is which on its own.
    """
    if not _has_api_key():
        return None
    if pm25_sensor_id is None:
        # No known PM2.5 sensor id for this station — can't reliably tell
        # which of possibly several pollutant readings is PM2.5, so don't
        # guess at one.
        return None
    try:
        resp = requests.get(
            f"{_OPENAQ_BASE}/locations/{location_id}/latest",
            headers=_get_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        for r in results:
            if r.get("sensorsId") == pm25_sensor_id:
                return r.get("value")
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch latest PM2.5 for station {location_id}: {e}")
        return None


_stations_readings_cache = {"data": None, "fetched_at": None}
STATIONS_READINGS_CACHE_HOURS = 1
MAX_STATIONS_WITH_READINGS = 100

# Small per-point cache for the radius-scoped lookup below. Keyed on a
# coarse rounding of (lat, lon, radius_km) so nearby repeat requests (e.g.
# the extension re-checking the same monitored location every 15 minutes)
# hit cache instead of re-querying OpenAQ every time.
_near_cache: Dict[tuple, Dict[str, Any]] = {}
NEAR_CACHE_MINUTES = 10

# OpenAQ v3's /locations endpoint accepts a radius filter, but caps it
# server-side (their docs put the ceiling at 25km at the time this was
# written — that may have changed; this client can't verify it live from
# here, so we clamp defensively and let OpenAQ's own error response be the
# source of truth if this cap is ever wrong).
_OPENAQ_MAX_RADIUS_M = 25_000


def get_stations_near(lat: float, lon: float, radius_km: float, limit: int = 25) -> List[Dict[str, Any]]:
    """
    Targeted alternative to get_stations_with_readings() for callers that
    only care about one point — e.g. alerts.py's /alerts/summary, used by
    the browser extension's alarm-driven check.

    get_stations_with_readings() was built for the main map: fetch up to
    100 stations GLOBALLY, enrich all of them, cache for an hour. Using
    that for a single-point radius query meant paying for ~100 individual
    OpenAQ /latest calls just to keep the handful actually within range —
    slow (10+ concurrent-batched round trips) and wasteful of OpenAQ's
    rate limit on stations the caller immediately discards. This function
    asks OpenAQ for stations near the point directly, so enrichment only
    ever touches the few stations that matter for this call.
    """
    if not _has_api_key():
        return []

    radius_m = min(radius_km * 1000, _OPENAQ_MAX_RADIUS_M)
    cache_key = (round(lat, 2), round(lon, 2), round(radius_m))
    now = datetime.now(timezone.utc)

    cached = _near_cache.get(cache_key)
    if cached and (now - cached["fetched_at"]) < timedelta(minutes=NEAR_CACHE_MINUTES):
        return cached["data"]

    try:
        resp = requests.get(
            f"{_OPENAQ_BASE}/locations",
            params={
                "coordinates": f"{lat},{lon}",
                "radius": int(radius_m),
                "limit": limit,
                "parameters_id": [2],  # PM2.5
            },
            headers=_get_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        stations = resp.json().get("results", [])
    except Exception as e:
        logger.warning(f"get_stations_near failed for ({lat},{lon},{radius_km}km): {e}")
        # Serve stale cache for this point if we have it, rather than
        # nothing, but never fabricate a reading.
        return cached["data"] if cached else []

    if not stations:
        _near_cache[cache_key] = {"data": [], "fetched_at": now}
        return []

    # Only a handful of stations at this point (radius-scoped, not the
    # global top-100) — safe to enrich them all concurrently without the
    # 10-wave bottleneck get_stations_with_readings() has at 100 stations.
    enriched = []
    with ThreadPoolExecutor(max_workers=min(10, len(stations))) as executor:
        future_to_station = {
            executor.submit(get_station_latest_pm25, s["id"], _pm25_sensor_id(s)): s for s in stations
        }
        for future in as_completed(future_to_station):
            station = future_to_station[future]
            try:
                reading = future.result()
            except Exception as e:
                logger.warning(f"PM2.5 fetch failed for station {station['id']}: {e}")
                continue
            if reading is None:
                continue
            enriched.append({
                "id": station["id"],
                "name": station.get("name") or station.get("location"),
                "coordinates": station.get("coordinates"),
                "country": (station.get("country") or {}).get("name"),
                "city": station.get("locality"),
                "pm25": reading,
            })

    _near_cache[cache_key] = {"data": enriched, "fetched_at": now}
    return enriched


def get_stations_with_readings(limit: int = MAX_STATIONS_WITH_READINGS) -> List[Dict[str, Any]]:
    """
    Real stations WITH each one's actual latest PM2.5 reading resolved
    server-side. Fixes a real bug: the frontend used to read
    station.parameters[].lastValue directly from the plain /locations
    response, but OpenAQ v3's /locations list does NOT include live
    readings inline (see get_country_aqi_aggregate's docstring below) — so
    that value was always undefined, every station's reading silently
    defaulted to 0, and every dot rendered as "green" regardless of real
    air quality.

    Bounded to `limit` stations and cached for an hour — resolving a
    reading requires a separate real /locations/{id}/latest call per
    station, and OpenAQ v3 rate-limits aggressively, so querying all
    ~1000+ available stations on every request isn't practical. Stations
    whose real reading can't be resolved are OMITTED entirely, never
    defaulted to a fabricated "safe" value.
    """
    now = datetime.now(timezone.utc)
    if (_stations_readings_cache["data"] is not None and _stations_readings_cache["fetched_at"]
            and (now - _stations_readings_cache["fetched_at"]) < timedelta(hours=STATIONS_READINGS_CACHE_HOURS)):
        return _stations_readings_cache["data"]

    stations = get_stations(limit=1000)
    if not stations:
        return []

    has_pm25 = [
        s for s in stations
        if any(p.get("parameter", {}).get("id") == 2 for p in s.get("sensors", []))
    ][:limit]

    # Resolve readings concurrently instead of one station at a time — with
    # up to 100 stations and a 10s-per-call timeout, sequential fetching had
    # a worst case of ~1000 seconds before returning anything, which looked
    # identical to "broken" from the frontend. Kept to a modest 10 workers
    # (not 30, like the vegetation grid) since OpenAQ rate-limits more
    # aggressively than ORNL DAAC.
    enriched = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_station = {
            executor.submit(get_station_latest_pm25, station["id"], _pm25_sensor_id(station)): station
            for station in has_pm25
        }
        for future in as_completed(future_to_station):
            station = future_to_station[future]
            try:
                reading = future.result()
            except Exception as e:
                logger.warning(f"PM2.5 fetch failed for station {station['id']}: {e}")
                continue
            if reading is None:
                continue  # Omit rather than guess.
            enriched.append({
                "id": station["id"],
                "name": station.get("name") or station.get("location"),
                "coordinates": station.get("coordinates"),
                "country": (station.get("country") or {}).get("name"),
                "city": station.get("locality"),
                "pm25": reading,
            })

    _stations_readings_cache["data"] = enriched
    _stations_readings_cache["fetched_at"] = now
    return enriched


def get_country_aqi_aggregate(max_stations_to_query: int = 200) -> Dict[str, Dict[str, Any]]:
    """
    Real per-country average PM2.5, aggregated from actual OpenAQ v3 station
    readings. Returns {country_code: {"avg_pm25": float, "station_count": int,
    "country_name": str}}.

    HONEST LIMITATION: OpenAQ v3's /locations list does NOT include live
    readings inline (confirmed against the real API response shape) — a
    separate /locations/{id}/latest call is required per station. Querying
    every station worldwide (thousands) on every request isn't practical
    even with caching, so this samples up to max_stations_to_query real
    stations (spread across as many distinct countries as possible) rather
    than querying all of them. This is a real, honestly-labeled sampling
    limitation, not a fabrication — the result metadata reports exactly
    how many real stations were sampled. Countries with zero real PM2.5
    stations in the sample are simply absent from the result; they are
    never backfilled with a guess.
    """
    now = datetime.now(timezone.utc)
    if (_country_agg_cache["data"] is not None and _country_agg_cache["fetched_at"]
            and (now - _country_agg_cache["fetched_at"]) < timedelta(hours=CACHE_HOURS)):
        return _country_agg_cache["data"]

    stations = get_stations(limit=1000)  # 1000 is OpenAQ's real hard cap, not a chosen sample size
    if not stations:
        return {}

    # Spread the sample across countries round-robin, so a handful of
    # densely-instrumented countries (e.g. US, India) don't consume the
    # entire query budget and starve smaller countries out of the sample.
    by_country_stations = defaultdict(list)
    for station in stations:
        country_info = station.get("country") or {}
        code = country_info.get("code")
        if not code:
            continue
        has_pm25 = any(s.get("parameter", {}).get("id") == 2 for s in station.get("sensors", []))
        if has_pm25:
            by_country_stations[code].append(station)

    sampled: List[tuple] = []  # (station, country_code)
    idx = 0
    country_codes = list(by_country_stations.keys())
    while len(sampled) < max_stations_to_query and country_codes:
        made_progress = False
        for code in country_codes:
            bucket = by_country_stations[code]
            if idx < len(bucket):
                sampled.append((bucket[idx], code))
                made_progress = True
                if len(sampled) >= max_stations_to_query:
                    break
        idx += 1
        if not made_progress:
            break

    country_names = {}
    for station, code in sampled:
        country_names[code] = (station.get("country") or {}).get("name", code)

    # Resolve readings concurrently — this loop making up to 200 sequential
    # blocking calls (worst case ~2000s) is very likely why the Global
    # Health Index tab got stuck on "Loading real station data..." with no
    # visible progress or failure, rather than genuinely being broken.
    by_country_values = defaultdict(list)
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_pair = {
            executor.submit(get_station_latest_pm25, station["id"], _pm25_sensor_id(station)): (station, code)
            for station, code in sampled
        }
        for future in as_completed(future_to_pair):
            station, code = future_to_pair[future]
            try:
                value = future.result()
            except Exception as e:
                logger.warning(f"PM2.5 fetch failed for station {station['id']}: {e}")
                continue
            if value is not None:
                by_country_values[code].append(value)

    aggregate = {}
    for code, values in by_country_values.items():
        if not values:
            continue
        aggregate[code] = {
            "avg_pm25": round(sum(values) / len(values), 1),
            "station_count": len(values),
            "country_name": country_names.get(code, code),
        }

    _country_agg_cache["data"] = aggregate
    _country_agg_cache["fetched_at"] = now
    return aggregate


# --- Real country boundary polygons (Natural Earth, public domain) --------
# Source: https://github.com/datasets/geo-countries — GeoJSON conversion of
# Natural Earth's country boundaries, public domain, using the same
# ISO 3166-1 alpha-2 codes OpenAQ returns. Fetched once and cached, since
# country borders don't change during a session and the file is ~14MB.
_COUNTRY_BOUNDARIES_URL = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
_boundaries_cache = {"data": None, "fetched_at": None}
BOUNDARIES_CACHE_HOURS = 168  # 1 week — country borders essentially never change


def get_country_boundaries_geojson() -> Dict[str, Any]:
    """Real Natural Earth country boundary polygons, keyed by the same
    ISO alpha-2 codes used throughout this module."""
    now = datetime.now(timezone.utc)
    if (_boundaries_cache["data"] is not None and _boundaries_cache["fetched_at"]
            and (now - _boundaries_cache["fetched_at"]) < timedelta(hours=BOUNDARIES_CACHE_HOURS)):
        return _boundaries_cache["data"]

    try:
        resp = requests.get(_COUNTRY_BOUNDARIES_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        original_count = len(data.get("features", []))
        data["features"] = [
            f for f in data.get("features", [])
            if (f.get("properties") or {}).get("ISO3166-1-Alpha-2") != "AQ"
        ]
        removed = original_count - len(data["features"])
        if removed:
            logger.info(
                f"Filtered {removed} Antarctica feature(s) from country boundaries — "
                f"its polygon touches latitude -90.0, which crashes Cesium's polygon "
                f"renderer (subdivideRhumbLine RangeError, a confirmed Cesium engine "
                f"bug, not specific to this data). Antarctica has no country_coords.py "
                f"entry and is never scored by the SHI composite, so nothing real is lost."
            )

        _boundaries_cache["data"] = data
        _boundaries_cache["fetched_at"] = now
        return data
    except Exception as e:
        logger.error(f"Failed to fetch country boundaries: {e}")
        return _boundaries_cache["data"] if _boundaries_cache["data"] is not None else {"type": "FeatureCollection", "features": []}
