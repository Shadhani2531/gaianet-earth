import os
import requests
from datetime import datetime, timedelta

# WAQI token now read from environment (.env), never hardcoded in source.
# Falls back to a demo token only if nothing is configured, so local dev
# doesn't hard-crash — but production/deployed use should always set
# WAQI_TOKEN in backend/.env.
WAQI_TOKEN = os.environ.get("WAQI_TOKEN", "demo")

# --- Real NOAA global CO2 (GML) -------------------------------------------
# Source: NOAA Global Monitoring Laboratory, globally-averaged marine
# surface monthly mean CO2 (co2_mm_gl.csv). Replaces the previous
# random.randint(380, 450) placeholder with the real published monthly
# global CO2 mixing ratio, cached for a day so we're not refetching NOAA's
# CSV on every single environment-data request.
_NOAA_CO2_URL = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_mm_gl.csv"
_co2_cache = {"value": None, "fetched_at": None}


def get_real_global_co2_ppm() -> float:
    """
    Fetch the most recent real globally-averaged CO2 reading (ppm) from
    NOAA GML. Cached for 24 hours since this updates monthly, not per
    request. Falls back to the last known real value (or a conservative
    recent-real-world estimate) if NOAA is unreachable — NEVER falls back
    to a random number.
    """
    now = datetime.utcnow()
    if (_co2_cache["value"] is not None and _co2_cache["fetched_at"]
            and (now - _co2_cache["fetched_at"]) < timedelta(hours=24)):
        return _co2_cache["value"]

    try:
        resp = requests.get(_NOAA_CO2_URL, timeout=10)
        resp.raise_for_status()
        # File is CSV with a commented header block (lines starting with '#'),
        # then columns: year, month, decimal, average, average_unc, trend, trend_unc
        last_valid = None
        for line in resp.text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                average = float(parts[3])
            except ValueError:
                continue
            if average > 0:
                last_valid = average
        if last_valid is not None:
            _co2_cache["value"] = round(last_valid, 2)
            _co2_cache["fetched_at"] = now
            return _co2_cache["value"]
    except Exception as e:
        print(f"NOAA CO2 fetch failed (using last known/fallback value): {e}")

    # Fallback only if NOAA is unreachable AND we have no prior cached value:
    # a labeled, conservative recent real-world figure, not a random guess.
    if _co2_cache["value"] is not None:
        return _co2_cache["value"]
    return 424.0  # approx. real global mean as of early 2025; update periodically

WAQI_MAX_STATION_DISTANCE_KM = 50.0
WAQI_MAX_AGE_HOURS = 24.0


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _waqi_reading(lat: float, lon: float):
    """
    Real air quality from the nearest WAQI station — or None, honestly.

    Previously, on ANY failure this returned aqi=100 / pm25=50 / temp=25
    as silent placeholders (the Insight panel then showed "AQI 100" and a
    Health Index of 66 derived from it). Also, with WAQI's shared "demo"
    token the API returns Shanghai's station for every query. Now:
      - no token / "demo" token  -> no call, aqi None, reason given
      - nearest station > 50 km away -> rejected (not "this location")
      - reading older than 24 h -> rejected as stale
      - iaqi.pm25 is WAQI's AQI SUB-INDEX, converted back to ug/m3
    Every response carries data_source + reason + station details.
    """
    from services.scenario_engine import _aqi_to_pm25

    aqi = None
    temp = None
    pm25 = None
    station = None
    data_source = "unavailable"
    reason = None

    if not WAQI_TOKEN or WAQI_TOKEN.strip().lower() == "demo":
        reason = "WAQI_TOKEN not set in backend/.env (the shared demo token only returns Shanghai)"
    else:
        url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={WAQI_TOKEN}"
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "ok":
                reason = f"WAQI error: {data.get('data')}"
            else:
                d = data.get("data", {}) or {}
                city = d.get("city", {}) or {}
                geo = city.get("geo") or []
                dist_km = (round(_haversine_km(lat, lon, float(geo[0]), float(geo[1])), 1)
                           if len(geo) == 2 else None)
                t = d.get("time", {}) or {}
                age_h = None
                observed_iso = t.get("iso")
                if observed_iso:
                    try:
                        obs = datetime.fromisoformat(observed_iso)
                        if obs.tzinfo is not None:
                            from datetime import timezone as _tz
                            age_h = round((datetime.now(_tz.utc) - obs).total_seconds() / 3600.0, 1)
                    except ValueError:
                        pass
                station = {
                    "name": city.get("name"),
                    "distance_km": dist_km,
                    "observed_at": observed_iso,
                    "age_hours": age_h,
                }

                aqi_val = d.get("aqi")
                if dist_km is None or dist_km > WAQI_MAX_STATION_DISTANCE_KM:
                    reason = (f"Nearest WAQI station ({city.get('name')}) is "
                              f"{dist_km} km away — too far to represent this location")
                elif age_h is not None and age_h > WAQI_MAX_AGE_HOURS:
                    reason = f"Nearest WAQI reading is {age_h} h old — too stale"
                elif aqi_val in (None, "-"):
                    reason = "Nearest WAQI station reported no AQI"
                else:
                    aqi = int(aqi_val)
                    data_source = "live_waqi"
                    iaqi = d.get("iaqi", {}) or {}
                    if "pm25" in iaqi and iaqi["pm25"].get("v") is not None:
                        pm25 = _aqi_to_pm25(float(iaqi["pm25"]["v"]))
                    if "t" in iaqi and iaqi["t"].get("v") is not None:
                        temp = float(iaqi["t"]["v"])
        except Exception as e:
            reason = f"WAQI unreachable: {e}"
            print(f"WAQI API Error: {e}")

    return {
        "temperature_c": temp,
        "air_quality_index": aqi,
        "pm25": pm25,
        "co2_ppm": get_real_global_co2_ppm(),  # real NOAA GML data, not random
        "location": {"lat": lat, "lon": lon},
        "data_source": data_source,
        "aqi_station": station,
        "aqi_reason": reason,
    }


# ---------------------------------------------------------------------------
# AQI source chain: WAQI station -> OpenAQ station -> Open-Meteo CAMS model
# ---------------------------------------------------------------------------
# WAQI alone was a single point of failure (it regularly answers
# {"status":"nope","data":"can not connect"}). Each fallback is a REAL
# source with its own label; nothing is ever invented:
#   1. WAQI nearest station  (<=50 km, <24 h)  -> live_waqi       (LIVE)
#      overall AQI = max of all pollutant sub-indices
#   2. OpenAQ v3 nearest station (<=25 km, <24 h, valid PM2.5) -> live_openaq (LIVE)
#      AQI computed from PM2.5 only (EPA breakpoints) — labeled as such
#   3. Open-Meteo air-quality model (CAMS) current us_aqi -> model_openmeteo (EST)
#      a model estimate for the grid cell, not a measurement
#   4. none -> unavailable, with every source's reason listed
_OPENMETEO_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPENAQ_RADIUS_KM = 25.0   # OpenAQ v3's own max search radius
ENV_CACHE_TTL_S = 300     # /environment and /shi both call this per click
_env_cache = {}


def _openaq_reading(lat: float, lon: float):
    from services import alerts
    v = alerts.get_nearest_station_verification(lat, lon, OPENAQ_RADIUS_KM)
    if v.get("data_source") == "live" and v.get("nearest_aqi") is not None:
        return {
            "aqi": int(v["nearest_aqi"]),
            "pm25": v.get("nearest_raw_pm25"),
            "station": {
                "name": v.get("nearest_station_name"),
                "distance_km": v.get("nearest_distance_km"),
                "observed_at": v.get("measured_at"),
                "age_hours": v.get("age_hours"),
            },
        }, None
    reasons = {
        "missing_api_key": "OPENAQ_API_KEY not set",
        "no_station_in_radius": f"no OpenAQ station within {int(OPENAQ_RADIUS_KM)} km",
    }
    src = v.get("data_source")
    return None, reasons.get(src) or f"no valid recent OpenAQ PM2.5 within {int(OPENAQ_RADIUS_KM)} km"


def _openmeteo_aq_reading(lat: float, lon: float):
    try:
        resp = requests.get(
            _OPENMETEO_AQ_URL,
            params={"latitude": lat, "longitude": lon,
                    "current": "us_aqi,pm2_5", "timezone": "auto"},
            timeout=10,
        )
        resp.raise_for_status()
        cur = (resp.json().get("current") or {})
        if cur.get("us_aqi") is None:
            return None, "Open-Meteo air-quality model returned no AQI"
        return {
            "aqi": int(round(float(cur["us_aqi"]))),
            "pm25": round(float(cur["pm2_5"]), 1) if cur.get("pm2_5") is not None else None,
            "station": None,
            "observed_at": cur.get("time"),
        }, None
    except Exception as e:
        return None, f"Open-Meteo air-quality model unreachable: {e}"


def generate_environment_data(lat: float, lon: float):
    """Air quality via the source chain above + real NOAA CO2.
    Response keeps the old keys and adds aqi_source / aqi_basis /
    aqi_attempts so the UI can say exactly where the number came from."""
    import time as _time
    key = (round(lat, 2), round(lon, 2))
    hit = _env_cache.get(key)
    if hit and _time.time() - hit[0] < ENV_CACHE_TTL_S:
        return hit[1]

    attempts = []
    aqi = pm25 = temp = station = None
    data_source, aqi_source, aqi_basis = "unavailable", None, None
    observed_at = None

    # 1. WAQI
    w = _waqi_reading(lat, lon)
    if w["air_quality_index"] is not None:
        aqi, pm25, temp, station = w["air_quality_index"], w["pm25"], w["temperature_c"], w["aqi_station"]
        data_source, aqi_source, aqi_basis = "live_waqi", "WAQI station", "overall"
    else:
        attempts.append(f"WAQI: {w.get('aqi_reason')}")

    # 2. OpenAQ
    if aqi is None:
        try:
            r, why = _openaq_reading(lat, lon)
        except Exception as e:
            r, why = None, f"OpenAQ lookup failed: {e}"
        if r:
            aqi, pm25, station = r["aqi"], r["pm25"], r["station"]
            data_source, aqi_source, aqi_basis = "live_openaq", "OpenAQ station", "pm25"
        else:
            attempts.append(f"OpenAQ: {why}")

    # 3. Open-Meteo CAMS model
    if aqi is None:
        r, why = _openmeteo_aq_reading(lat, lon)
        if r:
            aqi, pm25, observed_at = r["aqi"], r["pm25"], r["observed_at"]
            data_source, aqi_source, aqi_basis = "model_openmeteo", "Open-Meteo CAMS model", "overall"
        else:
            attempts.append(f"Open-Meteo: {why}")

    result = {
        "temperature_c": temp,
        "air_quality_index": aqi,
        "pm25": pm25,
        "co2_ppm": get_real_global_co2_ppm(),  # real NOAA GML data, not random
        "location": {"lat": lat, "lon": lon},
        "data_source": data_source,
        "aqi_source": aqi_source,          # human label of the source used
        "aqi_basis": aqi_basis,            # "overall" or "pm25" (PM2.5-only AQI)
        "aqi_station": station,
        "aqi_observed_at": observed_at or (station or {}).get("observed_at"),
        "aqi_attempts": attempts,          # why earlier sources were skipped
        "aqi_reason": None if aqi is not None else "; ".join(attempts),
    }
    _env_cache[key] = (_time.time(), result)
    if len(_env_cache) > 256:
        _env_cache.pop(next(iter(_env_cache)))
    return result
