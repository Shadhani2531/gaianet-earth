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


def get_stations(limit: int = 1000) -> List[Dict[str, Any]]:
    """
    Real OpenAQ v3 station list with PM2.5/PM10 sensors, each including
    a real country code (ISO 3166-1 alpha-2). Cached for 6 hours since
    station metadata doesn't change minute-to-minute.
    """
    global _last_openaq_error
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


def get_station_latest_pm25(location_id: int) -> float | None:
    """Real latest PM2.5 reading for a single station."""
    if not _has_api_key():
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
            if r.get("parameter", {}).get("id") == 2:  # PM2.5
                return r.get("value")
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch latest PM2.5 for station {location_id}: {e}")
        return None


_stations_readings_cache = {"data": None, "fetched_at": None}
STATIONS_READINGS_CACHE_HOURS = 1
MAX_STATIONS_WITH_READINGS = 100


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
            executor.submit(get_station_latest_pm25, station["id"]): station
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

    stations = get_stations(limit=2000)
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
            executor.submit(get_station_latest_pm25, station["id"]): (station, code)
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
        _boundaries_cache["data"] = data
        _boundaries_cache["fetched_at"] = now
        return data
    except Exception as e:
        logger.error(f"Failed to fetch country boundaries: {e}")
        return _boundaries_cache["data"] if _boundaries_cache["data"] is not None else {"type": "FeatureCollection", "features": []}
