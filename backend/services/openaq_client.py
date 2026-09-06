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


# How old a "latest" reading can be before it's no longer trustworthy
# enough to present as a confident verification number. Real stations
# commonly report hourly; 24h is generous enough to tolerate a station
# reporting less often, while still catching one that's actually
# stuck/offline for days and silently serving a stale last-known value.
_MAX_PM25_AGE_HOURS = 24.0


def get_verified_latest_pm25(station: Dict[str, Any], max_age_hours: float = _MAX_PM25_AGE_HOURS) -> Dict[str, Any]:
    """
    Fetches and VALIDATES the single latest real PM2.5 record for one
    station — the missing step that let a stale/invalid reading (e.g. an
    exact 0.0 from a dead sensor) get silently presented as a confident
    "live" verification number with no way to tell the two apart.

    Checks, in order:
      - the exact matched OpenAQ /latest record (sensorsId, value,
        datetime) — logged in full, not just the bare value, so a
        suspicious result can actually be investigated afterward instead
        of guessed at;
      - basic physical sanity (a negative PM2.5 reading is impossible);
      - its real measurement timestamp, converted to an age in hours;
      - whether that age is within max_age_hours.

    Deliberately does NOT reject an exact 0.0 outright — real air
    genuinely can read at or near zero (e.g. right after rain scrubs
    particulates out of the air), so a FRESH 0.0 is treated as valid;
    only a STALE reading (of any value, including 0.0) is rejected. This
    also does not touch which station gets selected (see
    get_nearest_station_verification in alerts.py) — it only decides
    whether THAT station's reading is trustworthy enough to show at all.

    Returns {"value", "measured_at", "age_hours", "valid", "reason"}.
    "reason" is one of: "ok", "no_pm25_sensor", "no_matching_sensor_
    record", "no_value_in_record", "negative_value_invalid", "no_
    timestamp", "unparseable_timestamp", "stale", "fetch_failed".
    """
    result: Dict[str, Any] = {
        "value": None, "measured_at": None, "age_hours": None,
        "valid": False, "reason": "unknown",
    }

    sensor_id = _pm25_sensor_id(station)
    if sensor_id is None:
        result["reason"] = "no_pm25_sensor"
        return result

    location_id = station.get("id")
    try:
        resp = requests.get(
            f"{_OPENAQ_BASE}/locations/{location_id}/latest",
            headers=_get_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        record = next((r for r in results if r.get("sensorsId") == sensor_id), None)

        if record is None:
            result["reason"] = "no_matching_sensor_record"
            logger.info(f"AQI verification: station {location_id} has no /latest record for PM2.5 sensor {sensor_id}")
            return result

        raw_value = record.get("value")
        raw_datetime = record.get("datetime")

        # OpenAQ v3 commonly nests this as {"utc": "...", "local": "..."}
        # per docs.openaq.org, but logging the RAW field regardless of
        # shape means a wrong assumption here still leaves real evidence
        # to correct from, rather than silently mis-parsing forever.
        measured_at_str = None
        if isinstance(raw_datetime, dict):
            measured_at_str = raw_datetime.get("utc") or raw_datetime.get("local")
        elif isinstance(raw_datetime, str):
            measured_at_str = raw_datetime

        logger.info(
            f"AQI verification: raw /latest record for station {location_id} "
            f"sensor {sensor_id}: value={raw_value!r} datetime={raw_datetime!r}"
        )

        if raw_value is None:
            result["reason"] = "no_value_in_record"
            return result
        if raw_value < 0:
            result["reason"] = "negative_value_invalid"
            logger.warning(f"AQI verification: station {location_id} returned a physically invalid negative PM2.5 ({raw_value}) — rejected")
            return result

        result["value"] = raw_value
        result["measured_at"] = measured_at_str

        if not measured_at_str:
            # No timestamp at all in the record — can't confirm this is
            # actually current, so don't present it as verified live data.
            result["reason"] = "no_timestamp"
            logger.info(f"AQI verification: station {location_id}'s /latest record had no datetime field — cannot confirm freshness, rejecting")
            return result

        try:
            measured_dt = datetime.fromisoformat(measured_at_str.replace("Z", "+00:00"))
            if measured_dt.tzinfo is None:
                measured_dt = measured_dt.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - measured_dt).total_seconds() / 3600
            result["age_hours"] = round(age_hours, 1)
        except Exception as e:
            # Couldn't parse the timestamp at all — can't confirm
            # freshness, so don't present it as a confident live reading
            # either. Logged so the actual raw format that broke parsing
            # is visible for a real fix, not a guess.
            result["reason"] = "unparseable_timestamp"
            logger.warning(f"AQI verification: could not parse datetime {measured_at_str!r} for station {location_id}: {e}")
            return result

        if result["age_hours"] > max_age_hours:
            result["reason"] = "stale"
            logger.info(
                f"AQI verification: station {location_id}'s latest PM2.5 reading is "
                f"{result['age_hours']}h old (> {max_age_hours}h threshold) — rejecting as stale, "
                f"not presenting as valid verification"
            )
            return result

        result["valid"] = True
        result["reason"] = "ok"
        return result
    except Exception as e:
        logger.warning(f"AQI verification: detailed PM2.5 fetch failed for station {location_id}: {e}")
        result["reason"] = "fetch_failed"
        return result

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
    Radius-scoped station lookup for a single point — used by alerts.py's
    /alerts/summary (both the browser extension's alarm-driven check and,
    since the global marker/cluster layer was removed, the Insight card's
    AQI verification line too — see updateAqiVerificationNode in ui.js).

    This is now the ONLY consumer of real-time OpenAQ station data in the
    app. It intentionally only enriches the handful of stations actually
    within range, rather than a global sweep — the app previously also
    had a get_stations_with_readings() that fetched/enriched up to 100
    stations globally for a map layer; that layer was removed entirely,
    and the function along with it, since this radius-scoped query is
    exactly what every remaining real consumer actually needed.
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

    # Only a handful of stations at this point (radius-scoped) — safe to
    # enrich them all concurrently.
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
                # Carried forward so a later per-station re-validation
                # (get_verified_latest_pm25) can find the PM2.5 sensor —
                # without this, _pm25_sensor_id() always returns None on
                # this stripped-down dict, which looked exactly like "this
                # station has no PM2.5 sensor" when it actually just meant
                # "this field never made it into the enriched output."
                "sensors": station.get("sensors", []),
            })

    _near_cache[cache_key] = {"data": enriched, "fetched_at": now}
    return enriched


def get_country_aqi_aggregate(max_stations_to_query: int = 80) -> Dict[str, Dict[str, Any]]:
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

    # Resolve readings concurrently — this loop making up to 80 sequential
    # blocking calls (worst case ~800s at max_workers=10) was very likely
    # why the Global Health Index tab got stuck on "Loading real station
    # data..." with no visible progress or failure, rather than genuinely
    # being broken — worse still at the previous default of 200 stations.
    # Reduced 200 -> 80 for a meaningfully faster worst case, and the
    # /shi-global route in main.py now also persists results to disk and
    # serves stale data immediately while refreshing in the background,
    # so even this reduced worst-case duration is no longer something a
    # user has to sit through synchronously after every backend restart.
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
