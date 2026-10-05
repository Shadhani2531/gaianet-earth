"""
Place search with disambiguation, and reverse geocoding.

Why: search previously flew to results[0] (Cesium Ion), Nominatim used
limit=1, and Ask Gaia's geocoder used count=1 — so a name shared by
several places ("Aurangabad" in Maharashtra AND Bihar) silently resolved
to one of them. Internally every location is identified by COORDINATES;
names are only labels. This module returns ALL plausible matches with
enough context (district, state, country, type) for the user to choose.

Sources (both free/keyless):
  - Open-Meteo geocoding (GeoNames): structured admin1/admin2/country,
    feature type, population — good for cities and towns.
  - Nominatim (OpenStreetMap): also covers small villages and localities.
    Usage policy respected: identifying User-Agent, <= 1 request/second,
    results cached, and NO search-as-you-type (only on submit).

Query qualifiers: "Aurangabad, Bihar" -> name "Aurangabad", qualifier
"Bihar", used to filter candidates by state/district/country.
"""

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_OM_URL = "https://geocoding-api.open-meteo.com/v1/search"
_NOM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_NOM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
_HEADERS = {"User-Agent": "GaiaNetEarth/1.0 (academic environmental-monitoring project, YCCE Nagpur)"}

MAX_RESULTS = 8
DEDUPE_KM = 15.0          # same name within this distance = same place
CACHE_TTL_S = 24 * 3600

_cache: Dict[Tuple, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_nom_lock = threading.Lock()
_nom_last_call = [0.0]

_OM_FEATURE_KIND = {
    "PPLC": "capital", "PPLA": "city", "PPLA2": "city", "PPLA3": "town",
    "PPLA4": "town", "PPL": "town", "PPLX": "locality", "PPLL": "village",
    "ADM1": "state", "ADM2": "district", "ADM3": "sub-district", "PCLI": "country",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _cache_get(key):
    with _cache_lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    return None


def _cache_put(key, value):
    with _cache_lock:
        if len(_cache) > 512:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.time(), value)


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().casefold()


def _nominatim_get(url: str, params: Dict[str, Any]) -> Any:
    """Nominatim policy: max 1 request/second, identifying User-Agent."""
    with _nom_lock:
        wait = 1.05 - (time.time() - _nom_last_call[0])
        if wait > 0:
            time.sleep(wait)
        _nom_last_call[0] = time.time()
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _parse_query(query: str) -> Tuple[str, List[str]]:
    parts = [p.strip() for p in query.split(",") if p.strip()]
    if not parts:
        return "", []
    return parts[0], parts[1:]


def _label(c: Dict[str, Any]) -> str:
    """'Aurangabad · Bihar, India' — name plus the context that tells it apart."""
    ctx = []
    for part in (c.get("district"), c.get("state"), c.get("country")):
        if part and _norm(part) != _norm(c.get("name")) and part not in ctx:
            ctx.append(part)
    return c["name"] + (" · " + ", ".join(ctx) if ctx else "")


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

def _from_open_meteo(name: str) -> List[Dict[str, Any]]:
    """Open-Meteo candidates for a bare name, cached under ("om", name).
    Shared by typeahead suggestions and the full /geocode search, so typing
    "Aurangabad" and then pressing Enter only costs the Nominatim call.
    Returns fresh dict copies so callers can annotate them safely."""
    key = ("om", _norm(name))
    cached = _cache_get(key)
    if cached is not None:
        return [dict(c) for c in cached]
    resp = requests.get(_OM_URL, params={"name": name, "count": 10, "language": "en", "format": "json"},
                        timeout=8)
    resp.raise_for_status()
    out = []
    for r in resp.json().get("results") or []:
        if r.get("latitude") is None or r.get("longitude") is None:
            continue
        out.append({
            "name": r.get("name"),
            "district": r.get("admin2"),
            "state": r.get("admin1"),
            "country": r.get("country"),
            "country_code": (r.get("country_code") or "").upper() or None,
            "lat": float(r["latitude"]),
            "lon": float(r["longitude"]),
            "kind": _OM_FEATURE_KIND.get(r.get("feature_code") or "", "place"),
            "population": r.get("population"),
            "importance": None,
            "source": "Open-Meteo (GeoNames)",
        })
    _cache_put(key, out)
    return [dict(c) for c in out]


def _from_nominatim(query: str) -> List[Dict[str, Any]]:
    data = _nominatim_get(_NOM_SEARCH_URL, {
        "q": query, "format": "jsonv2", "limit": 10, "addressdetails": 1,
        "accept-language": "en",
    })
    out = []
    for r in data or []:
        a = r.get("address") or {}
        name = r.get("name") or a.get("village") or a.get("town") or a.get("city") \
            or (r.get("display_name") or "").split(",")[0]
        if not name:
            continue
        out.append({
            "name": name,
            "district": a.get("state_district") or a.get("county"),
            "state": a.get("state"),
            "country": a.get("country"),
            "country_code": (a.get("country_code") or "").upper() or None,
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "kind": r.get("addresstype") or r.get("type") or "place",
            "population": None,
            "importance": r.get("importance"),
            "source": "OpenStreetMap (Nominatim)",
        })
    return out


# --------------------------------------------------------------------------
# shared candidate processing (full search + typeahead)
# --------------------------------------------------------------------------

def _apply_qualifiers(candidates, qualifiers):
    """'Aurangabad, Bihar': qualifiers must match district/state/country.
    If nothing matches, keep the unfiltered list rather than show nothing."""
    if not qualifiers:
        return candidates
    def matches(c):
        ctx = " ".join(_norm(c.get(f)) for f in ("district", "state", "country", "country_code"))
        return all(_norm(q) in ctx for q in qualifiers)
    filtered = [c for c in candidates if matches(c)]
    return filtered or candidates


def _dedupe(candidates):
    """Same name within DEDUPE_KM is one place; merge missing admin fields."""
    merged: List[Dict[str, Any]] = []
    for c in candidates:
        dup = next((m for m in merged
                    if _norm(m["name"]) == _norm(c["name"])
                    and _haversine_km(m["lat"], m["lon"], c["lat"], c["lon"]) <= DEDUPE_KM), None)
        if dup:
            for f in ("district", "state", "country", "country_code", "population", "importance"):
                if not dup.get(f) and c.get(f):
                    dup[f] = c[f]
        else:
            merged.append(dict(c))
    return merged


def _rank(candidates, name):
    """Label + exact flag; exact-name matches first, then bigger places."""
    target = _norm(name)
    for c in candidates:
        c["exact"] = _norm(c["name"]) == target
        c["label"] = _label(c)
    candidates.sort(key=lambda c: (
        not c["exact"],
        -(c.get("population") or 0),
        -(c.get("importance") or 0),
    ))
    return candidates


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

SUGGEST_MIN_CHARS = 3
SUGGEST_LIMIT = 6


def suggest_places(query: str, limit: int = SUGGEST_LIMIT) -> Dict[str, Any]:
    """
    Typeahead suggestions — Open-Meteo (GeoNames) ONLY. Nominatim is never
    called here: its usage policy forbids search-as-you-type, and small
    villages are covered by the full /geocode search on Enter instead.
    Uses the same ("om", name) cache as search_places().
    """
    query = (query or "").strip()
    name, qualifiers = _parse_query(query)
    base = {"query": query, "name": name, "qualifiers": qualifiers}
    if len(name) < SUGGEST_MIN_CHARS:
        return {**base, "candidates": [], "status": "too_short"}
    limit = max(1, min(int(limit), 10))
    try:
        candidates = _from_open_meteo(name)
    except Exception as e:
        logger.warning(f"Suggest failed for '{query}': {e}")
        return {**base, "candidates": [], "status": "unavailable"}
    ranked = _rank(_dedupe(_apply_qualifiers(candidates, qualifiers)), name)[:limit]
    return {**base, "candidates": ranked, "status": "ok" if ranked else "no_results"}


def search_places(query: str) -> Dict[str, Any]:
    """
    Returns:
      {
        "query": ..., "name": ..., "qualifiers": [...],
        "candidates": [ {name, district, state, country, lat, lon, kind,
                         population, label, exact, source}, ... ],
        "ambiguous": bool,   # >1 exact-name match in different places
        "status": "ok" | "no_results" | "unavailable",
      }
    """
    query = (query or "").strip()
    name, qualifiers = _parse_query(query)
    base = {"query": query, "name": name, "qualifiers": qualifiers}
    if not name:
        return {**base, "candidates": [], "ambiguous": False, "status": "no_results"}

    key = ("search", _norm(query))
    cached = _cache_get(key)
    if cached:
        return cached

    candidates: List[Dict[str, Any]] = []
    errors = []
    try:
        candidates += _from_open_meteo(name)
    except Exception as e:
        errors.append(f"Open-Meteo: {e}")
    try:
        candidates += _from_nominatim(query)
    except Exception as e:
        errors.append(f"Nominatim: {e}")

    if not candidates:
        status = "unavailable" if len(errors) == 2 else "no_results"
        result = {**base, "candidates": [], "ambiguous": False, "status": status,
                  "errors": errors}
        if status == "no_results":
            _cache_put(key, result)
        return result

    merged = _rank(_dedupe(_apply_qualifiers(candidates, qualifiers)), name)[:MAX_RESULTS]

    exact = [c for c in merged if c["exact"]]
    result = {
        **base,
        "candidates": merged,
        "ambiguous": len(exact) > 1,
        "status": "ok",
    }
    _cache_put(key, result)
    return result


def reverse_geocode(lat: float, lon: float) -> Dict[str, Any]:
    """Human-readable place for a clicked point (Nominatim reverse)."""
    key = ("reverse", round(lat, 3), round(lon, 3))   # ~100 m
    cached = _cache_get(key)
    if cached:
        return cached
    try:
        r = _nominatim_get(_NOM_REVERSE_URL, {
            "lat": lat, "lon": lon, "format": "jsonv2", "zoom": 14,
            "addressdetails": 1, "accept-language": "en",
        })
        if not r or r.get("error"):
            result = {"lat": lat, "lon": lon, "label": None, "status": "no_results"}
            _cache_put(key, result)
            return result
        a = r.get("address") or {}
        name = (a.get("village") or a.get("town") or a.get("city") or a.get("hamlet")
                or a.get("suburb") or a.get("municipality") or a.get("county") or r.get("name"))
        c = {
            "name": name or "Unnamed area",
            "district": a.get("state_district") or a.get("county"),
            "state": a.get("state"),
            "country": a.get("country"),
            "country_code": (a.get("country_code") or "").upper() or None,
        }
        result = {"lat": lat, "lon": lon, **c, "label": _label(c),
                  "source": "OpenStreetMap (Nominatim)", "status": "ok"}
        _cache_put(key, result)
        return result
    except Exception as e:
        logger.warning(f"Reverse geocode failed for ({lat},{lon}): {e}")
        return {"lat": lat, "lon": lon, "label": None, "status": "unavailable"}
