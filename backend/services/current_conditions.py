"""
Current temperature and a REAL temperature anomaly for a point.

Why this module exists
----------------------
1. Current temperature. The Insight panel previously showed the latest
   MONTH's average of daily MAXIMUM temperatures (from the archive API),
   and /environment used the WAQI air-quality station's sensor reading
   (iaqi.t). Neither is "the temperature right now at this spot":
     - a monthly mean of daily maxima runs several degrees above the
       current temperature for most of the day and all of the night;
     - a WAQI reading comes from the nearest AQ monitor (can be km away),
       can be hours old, and those sensors are often on rooftops/roads.
   Weather apps show model-based current conditions at the user's exact
   coordinates. This module does the same via Open-Meteo `current=`
   (NWP model current conditions, ~15-minute resolution), and returns
   the observation time so the UI can say "as of HH:MM".

2. Temperature anomaly. The old anomaly compared that monthly mean of
   daily maxima against a hand-written latitude/season formula
   (28 - 0.5*|lat| + 10*sin(...)), which produced numbers like +13 C for
   Nagpur in October. The anomaly here compares LIKE WITH LIKE, from ONE
   dataset (Open-Meteo historical archive, ERA5-based reanalysis):
       recent  = mean of daily mean temperature over the last 7 days
                 the archive has (archive lags ~5 days)
       baseline = mean of daily mean temperature for the SAME calendar
                 days, averaged over 1991-2020 (WMO standard normal)
       anomaly = recent - baseline
   Both sides come from the same reanalysis, so model/grid bias cancels.

Honesty rules (project principle): nothing is fabricated. Any failure
returns None plus an explicit status — never a placeholder number.
"""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

BASELINE_START = "1991-01-01"
BASELINE_END = "2020-12-31"
BASELINE_LABEL = "1991-2020"
RECENT_WINDOW_DAYS = 7
ARCHIVE_LAG_DAYS = 6          # archive is ~5 days behind; 6 is a safe margin

CURRENT_CACHE_TTL_S = 600     # 10 min — Open-Meteo current updates every 15 min
RECENT_CACHE_TTL_S = 6 * 3600
MAX_CACHE_ENTRIES = 256

_lock = threading.Lock()
_current_cache: Dict[tuple, tuple] = {}      # key -> (fetched_ts, result)
_recent_cache: Dict[tuple, tuple] = {}       # key -> (fetched_ts, result)
_climatology_cache: Dict[tuple, Dict[str, float]] = {}  # key -> {"MM-DD": mean}


def _key(lat: float, lon: float, decimals: int) -> tuple:
    return (round(lat, decimals), round(lon, decimals))


def _cache_put(cache: dict, key: tuple, value: Any) -> None:
    with _lock:
        if len(cache) >= MAX_CACHE_ENTRIES:
            cache.pop(next(iter(cache)))  # drop oldest inserted
        cache[key] = value


# ---------------------------------------------------------------------------
# 1. Current temperature
# ---------------------------------------------------------------------------

def get_current_temperature(lat: float, lon: float) -> Dict[str, Any]:
    """Model-based current conditions at the exact coordinates."""
    key = _key(lat, lon, 2)  # ~1 km — finer than the model grid anyway
    now = time.time()
    with _lock:
        hit = _current_cache.get(key)
    if hit and now - hit[0] < CURRENT_CACHE_TTL_S:
        return hit[1]

    try:
        resp = requests.get(
            _FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {}) or {}
        temp = current.get("temperature_2m")
        if temp is None:
            raise ValueError("Open-Meteo returned no temperature_2m for this point")

        result = {
            "temperature_c": round(float(temp), 1),
            "feels_like_c": _round_or_none(current.get("apparent_temperature")),
            "humidity_pct": current.get("relative_humidity_2m"),
            "wind_kmh": current.get("wind_speed_10m"),
            "observation_time": current.get("time"),            # local, ISO
            "timezone": data.get("timezone"),
            "timezone_abbreviation": data.get("timezone_abbreviation"),
            "model_elevation_m": data.get("elevation"),
            "source": "Open-Meteo current conditions (NWP model, ~15-min resolution)",
            "data_source": "real_openmeteo",
            "status": "live",
        }
        _cache_put(_current_cache, key, (now, result))
        return result
    except Exception as e:
        logger.warning(f"Current temperature fetch failed for ({lat},{lon}): {e}")
        return {
            "temperature_c": None, "feels_like_c": None, "humidity_pct": None,
            "observation_time": None, "timezone": None,
            "source": "Open-Meteo current conditions",
            "data_source": "unavailable",
            "status": "unavailable",
        }


# ---------------------------------------------------------------------------
# 2. Temperature anomaly vs a real 1991-2020 climatology — ONE shared method
#    for the Insight card (one point) and the globe heatmap (126 points).
# ---------------------------------------------------------------------------
#
#   recent   = mean daily-mean temperature over the last 7 days the ERA5
#              archive has (it lags ~5-6 days)
#   baseline = mean of the SAME 7 calendar days in each year 1991-2020
#   anomaly  = recent - baseline          (both sides: same reanalysis)
#
# Cost (Open-Meteo free tier = 10,000 calls/day; a request longer than two
# weeks per location counts as several calls). The previous version pulled
# 30 full years of daily data per location (~780 calls each). Fetching only
# the matching ~1-2 week window in each of the 30 years costs ~31 calls per
# location, and the archive accepts many locations per request, so the
# whole heatmap grid shares the same 31 requests. Each location's baseline
# for a given calendar window never changes, so it is cached on disk.

ANOMALY_YEARS = list(range(1991, 2021))      # WMO 1991-2020 normal
MIN_BASELINE_YEARS = 25
RECENT_FETCH_DAYS = 14
ANOMALY_CACHE_TTL_S = 12 * 3600
_BASELINE_DIR = Path(__file__).resolve().parents[1] / "data" / "anomaly_baseline_cache"
_anomaly_cache: Dict[tuple, tuple] = {}


def _shift_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:                      # 29 Feb -> 28 Feb
        return d.replace(year=d.year - years, day=28)


class RateLimited(Exception):
    """Open-Meteo returned HTTP 429 (free tier: 600 calls/min, 5,000/hour,
    10,000/day; a multi-location request counts once PER location)."""


def _archive_daily_mean(points: List[Tuple[float, float]], start: date, end: date) -> List[Dict[str, float]]:
    """Daily-mean temperature for many points in ONE archive request.
    Returns, per point, {iso_date: temp}. Dates are UTC days for every
    point, so recent window and baseline use identical day boundaries."""
    resp = requests.get(
        _ARCHIVE_URL,
        params={
            "latitude": ",".join(f"{la:.4f}" for la, _ in points),
            "longitude": ",".join(f"{lo:.4f}" for _, lo in points),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_mean",
            "timezone": "GMT",
        },
        timeout=40,
    )
    if resp.status_code == 429:
        raise RateLimited(resp.text[:200])
    resp.raise_for_status()
    body = resp.json()
    results = body if isinstance(body, list) else [body]
    out = []
    for r in results:
        daily = (r or {}).get("daily", {}) or {}
        out.append({t: float(v) for t, v in zip(daily.get("time", []) or [],
                                                 daily.get("temperature_2m_mean", []) or []) if v is not None})
    if len(out) != len(points):
        raise ValueError(f"archive returned {len(out)} series for {len(points)} points")
    return out


def _baseline_cache_file(lat: float, lon: float) -> Path:
    return _BASELINE_DIR / f"{lat:.1f}_{lon:.1f}.json"


def _load_cached_baseline(lat: float, lon: float, window_key: str) -> Optional[Dict[str, Any]]:
    try:
        with open(_baseline_cache_file(lat, lon), "r", encoding="utf-8") as f:
            return json.load(f).get(window_key)
    except (OSError, ValueError):
        return None


def _save_cached_baseline(lat: float, lon: float, window_key: str, value: Dict[str, Any]) -> None:
    try:
        _BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        path = _baseline_cache_file(lat, lon)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data[window_key] = value
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        tmp.replace(path)
    except OSError as e:
        logger.warning(f"Could not cache anomaly baseline: {e}")


def _fetch_with_retry(fetch, pts, s, e, retries: int, wait_s: float, sleep):
    for attempt in range(retries + 1):
        try:
            return fetch(pts, s, e)
        except RateLimited:
            if attempt == retries:
                raise
            logger.warning(f"Open-Meteo rate limit hit; retrying in {wait_s:.0f}s")
            sleep(wait_s)


def compute_anomalies(points: List[Tuple[float, float]], today: Optional[date] = None,
                      fetch=None, pace_s: float = 0.0, progress=None, sleep=time.sleep,
                      retries: int = 2, retry_wait_s: float = 65.0,
                      window_end: Optional[date] = None) -> List[Dict[str, Any]]:
    """Anomaly for each point with the method described above. `fetch` is
    injectable for tests (defaults to the live archive).

    pace_s > 0: requests are sent ONE AT A TIME with that gap (used for the
    126-point heatmap grid, where each request counts as 126 calls against
    Open-Meteo's 600/minute limit). pace_s == 0: up to 6 in parallel (fine
    for a single point: 31 calls). 429 responses are retried after the
    per-minute window resets. progress(done, total) reports build progress.

    window_end=None (Insight card): the LATEST 7 days the archive has, per
    point — the most up-to-date, accurate value.
    window_end=<date> (heatmap): exactly the 7 days ending on that date (a
    fixed Monday-Sunday week), so the grid only needs rebuilding weekly."""
    fetch = fetch or _archive_daily_mean
    today = today or datetime.now(timezone.utc).date()
    method = (f"Mean daily temperature over the last {RECENT_WINDOW_DAYS} days available minus the "
              f"{BASELINE_LABEL} average for the same calendar days")
    base = {"method": method, "baseline_period": BASELINE_LABEL,
            "source": "Open-Meteo historical archive (ERA5-based reanalysis), same dataset both sides",
            "data_source": "derived_real_openmeteo"}
    results: List[Dict[str, Any]] = [dict(base, anomaly_c=None, status="unavailable") for _ in points]

    if window_end is not None:
        end = window_end
        start = end - timedelta(days=RECENT_WINDOW_DAYS - 1)
    else:
        end = today - timedelta(days=ARCHIVE_LAG_DAYS)
        start = end - timedelta(days=RECENT_FETCH_DAYS - 1)
    total_steps = 1 + len(ANOMALY_YEARS)
    if progress:
        progress(0, total_steps)
    try:
        recent = _fetch_with_retry(fetch, points, start, end, retries, retry_wait_s, sleep)
    except Exception as e:
        logger.warning(f"Anomaly: recent window fetch failed: {e}")
        for r in results:
            r["reason"] = "Recent archive data not available right now"
        return results

    windows: Dict[int, List[date]] = {}
    for i, series in enumerate(recent):
        days = sorted(date.fromisoformat(t) for t in series)
        if window_end is not None:
            days = [d for d in days if start <= d <= end]      # fixed week: all 7 days required
        if len(days) < RECENT_WINDOW_DAYS:
            results[i]["reason"] = ("Archive does not yet have the whole week for this point"
                                    if window_end is not None else
                                    "Recent archive data not available for this point")
            continue
        windows[i] = days[-RECENT_WINDOW_DAYS:]

    # Baselines: from the disk cache where possible; fetch the rest together.
    baselines: Dict[int, float] = {}
    need = []
    for i, w in windows.items():
        key = f"{w[0].strftime('%m-%d')}..{w[-1].strftime('%m-%d')}"
        cached = _load_cached_baseline(points[i][0], points[i][1], key)
        if cached:
            baselines[i] = cached["baseline_mean_c"]
            results[i]["baseline_years_used"] = cached["years"]
        else:
            need.append((i, key))

    if need:
        span_start = min(windows[i][0] for i, _ in need)
        span_end = max(windows[i][-1] for i, _ in need)
        need_points = [points[i] for i, _ in need]
        offsets = [span_end.year - y for y in ANOMALY_YEARS]     # window END year runs 1991..2020
        per_year: Dict[int, List[Dict[str, float]]] = {}
        def one(o):
            return o, _fetch_with_retry(fetch, need_points, _shift_years(span_start, o),
                                        _shift_years(span_end, o), retries, retry_wait_s, sleep)
        done = 1
        if pace_s > 0:
            for k, o in enumerate(offsets):
                if k:
                    sleep(pace_s)
                try:
                    per_year[o] = one(o)[1]
                except Exception as e:
                    logger.warning(f"Anomaly: baseline year {span_end.year - o} failed: {e}")
                done += 1
                if progress:
                    progress(done, total_steps)
        else:
            with ThreadPoolExecutor(max_workers=6) as pool:
                futures = [pool.submit(one, o) for o in offsets]
                for fut in futures:
                    try:
                        o, series = fut.result()
                        per_year[o] = series
                    except Exception as e:
                        logger.warning(f"Anomaly: baseline year fetch failed: {e}")
                    done += 1
                    if progress:
                        progress(done, total_steps)
        for j, (i, key) in enumerate(need):
            year_means = []
            for o, series in per_year.items():
                vals = [series[j].get(_shift_years(d, o).isoformat()) for d in windows[i]]
                vals = [v for v in vals if v is not None]
                if len(vals) >= RECENT_WINDOW_DAYS - 1:
                    year_means.append(sum(vals) / len(vals))
            if len(year_means) >= MIN_BASELINE_YEARS:
                baselines[i] = sum(year_means) / len(year_means)
                results[i]["baseline_years_used"] = len(year_means)
                _save_cached_baseline(points[i][0], points[i][1], key,
                                      {"baseline_mean_c": baselines[i], "years": len(year_means)})
            else:
                results[i]["reason"] = (f"Only {len(year_means)} of {len(ANOMALY_YEARS)} baseline years "
                                        f"available (need {MIN_BASELINE_YEARS}) — the data source may be "
                                        f"rate-limiting; try again in a minute")

    if progress:
        progress(total_steps, total_steps)
    for i, w in windows.items():
        if i not in baselines:
            continue
        temps = [recent[i][d.isoformat()] for d in w]
        recent_mean = sum(temps) / len(temps)
        results[i].update({
            "requested_end": end.isoformat(),
            "anomaly_c": round(recent_mean - baselines[i], 2),
            "recent_mean_c": round(recent_mean, 2),
            "baseline_mean_c": round(baselines[i], 2),
            "window_start": w[0].isoformat(),
            "window_end": w[-1].isoformat(),
            "status": "ok",
        })
        results[i].pop("reason", None)
    return results


def last_complete_week_end(today: Optional[date] = None) -> date:
    """Most recent Sunday whose whole Monday-Sunday week is already in the
    archive (which lags ~ARCHIVE_LAG_DAYS)."""
    today = today or datetime.now(timezone.utc).date()
    latest = today - timedelta(days=ARCHIVE_LAG_DAYS)
    return latest - timedelta(days=(latest.weekday() + 1) % 7)     # weekday(): Mon=0 ... Sun=6


def get_temperature_anomaly(lat: float, lon: float) -> Dict[str, Any]:
    """Insight-card anomaly: the shared method for a single point."""
    key = (_key(lat, lon, 1), date.today().isoformat())
    with _lock:
        hit = _anomaly_cache.get(key)
    if hit and time.time() - hit[0] < ANOMALY_CACHE_TTL_S:
        return hit[1]
    try:
        res = compute_anomalies([(round(lat, 1), round(lon, 1))])[0]
    except Exception as e:
        logger.warning(f"Temperature anomaly failed for ({lat},{lon}): {e}")
        res = {"anomaly_c": None, "status": "unavailable", "reason": str(e)[:200]}
    if res.get("status") == "ok":
        _cache_put(_anomaly_cache, key, (time.time(), res))
    return res


def _round_or_none(v, nd: int = 1):
    return round(float(v), nd) if v is not None else None
