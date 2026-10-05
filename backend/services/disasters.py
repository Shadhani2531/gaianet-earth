"""
Natural disasters / hazards — Phase 1 (GDACS + USGS).

Primary test case: the 26 Aug 2026 Bhote Koshi / Rasuwagadhi "Himalayan
Tsunami" (GDACS FL 1104124, USGS us7000tbwb). Everything below was shaped
by checking that event's REAL API responses, which exposed these traps:

  1. GDACS flood "centroid" is the centre of the analyst-drawn affected
     polygon, NOT where the event happened (Rasuwa: ~110 km off, in a patch
     south of Kathmandu). -> marked "approximate"; replaced by a linked
     USGS origin when one exists.
  2. GDACS sendai "affected" entries are often "Out of contact" (missing),
     and several entries are cumulative counts at different dates.
     -> relabelled from the description text; only the latest per
     (label, country) is shown; never summed.
  3. GDACS "severity: Magnitude 0" is meaningless for floods/droughts.
     -> dropped.
  4. EONET's copy of a GDACS event has swapped lat/lon and a different
     close date. -> EONET is not used in Phase 1.
  5. USGS first published the Rasuwa collapse as an M4.4 *earthquake*,
     then reclassified it as an M5.2 *landslide*. -> landslides are
     queried separately so they're never lost behind an
     earthquake-only filter.
  6. GDACS's affected polygon (two admin-unit pieces) does NOT contain the
     USGS origin (~6.6 km outside). -> linking uses distance-to-polygon
     with a buffer, not strict containment.

Honesty rules: no invented numbers; every figure carries its source and
as-of date; failures are reported per source, never hidden.
"""

import logging
import math
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

GDACS_SEARCH_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
GDACS_EVENT_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
GDACS_GEOMETRY_URL = "https://www.gdacs.org/gdacsapi/api/polygons/getgeometry"
USGS_QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

GDACS_TYPES = {
    "EQ": "earthquake", "TC": "tropical_cyclone", "FL": "flood",
    "VO": "volcano", "DR": "drought", "WF": "wildfire",
}
HAZARD_LABELS = {
    "earthquake": "Earthquake", "tropical_cyclone": "Tropical cyclone",
    "flood": "Flood", "volcano": "Volcano", "drought": "Drought",
    "wildfire": "Wildfire", "landslide": "Landslide",
}
ALERT_RANK = {"green": 1, "yellow": 1.5, "orange": 2, "red": 3}

GDACS_PAGE_SIZE = 100            # GDACS returns at most 100 records per call
GDACS_MAX_PAGES = 5
MAX_RANGE_DAYS = 366
LIST_CACHE_TTL = 600             # 10 min
DETAIL_CACHE_TTL = 1800          # 30 min
GEOMETRY_CACHE_TTL = 6 * 3600

# Linking rules (see trap 6)
LINK_TIME_WINDOW_H = 48
LINK_CANDIDATE_KM = 200          # centroid-to-point: "possibly related"
LINK_POLY_BUFFER_KM = 25         # distance to polygon edge: "linked"
EQ_DUPLICATE_KM = 100            # GDACS EQ vs USGS earthquake = same quake
EQ_DUPLICATE_H = 1
EQ_DUPLICATE_DMAG = 0.5

_cache: Dict[Tuple, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _cache_get(key, ttl):
    with _cache_lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    return None


def _cache_put(key, value):
    with _cache_lock:
        if len(_cache) > 400:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.time(), value)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    """GDACS dates have no zone; they are UTC (report titles say 'UTC')."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


# ---------------------------------------------------------------------------
# geometry: point-to-polygon distance (local equirectangular projection —
# accurate to well under 1% at the <100 km scales used for linking)
# ---------------------------------------------------------------------------

def _rings(geometry: Dict[str, Any]) -> List[List[List[float]]]:
    """All rings (outer + holes) of a Polygon / MultiPolygon, [lon, lat]."""
    t = geometry.get("type")
    c = geometry.get("coordinates") or []
    if t == "Polygon":
        return list(c)
    if t == "MultiPolygon":
        return [ring for poly in c for ring in poly]
    return []


def _polygons(geometry: Dict[str, Any]) -> List[List[List[List[float]]]]:
    t = geometry.get("type")
    c = geometry.get("coordinates") or []
    if t == "Polygon":
        return [c]
    if t == "MultiPolygon":
        return list(c)
    return []


def _point_in_ring(lon, lat, ring) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            xin = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < xin:
                inside = not inside
    return inside


def point_in_geometry(lat: float, lon: float, geometry: Dict[str, Any]) -> bool:
    for poly in _polygons(geometry):
        if not poly:
            continue
        if _point_in_ring(lon, lat, poly[0]) and not any(
                _point_in_ring(lon, lat, hole) for hole in poly[1:]):
            return True
    return False


def distance_to_geometry_km(lat: float, lon: float, geometry: Dict[str, Any]) -> Optional[float]:
    """0 if inside, else shortest distance (km) to any polygon edge."""
    rings = _rings(geometry)
    if not rings:
        return None
    if point_in_geometry(lat, lon, geometry):
        return 0.0
    kx = 111.320 * math.cos(math.radians(lat))
    ky = 110.574
    best = float("inf")
    for ring in rings:
        for i in range(len(ring) - 1):
            ax, ay = (ring[i][0] - lon) * kx, (ring[i][1] - lat) * ky
            bx, by = (ring[i + 1][0] - lon) * kx, (ring[i + 1][1] - lat) * ky
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
            px, py = ax + t * dx, ay + t * dy
            best = min(best, math.hypot(px, py))
    return round(best, 2)


# ---------------------------------------------------------------------------
# GDACS
# ---------------------------------------------------------------------------

def normalize_gdacs_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    p = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    etype = p.get("eventtype")
    if etype not in GDACS_TYPES or len(coords) < 2 or p.get("eventid") is None:
        return None
    hazard = GDACS_TYPES[etype]
    alert = (p.get("alertlevel") or "").lower() or None
    start, end = _parse_dt(p.get("fromdate")), _parse_dt(p.get("todate"))

    # Trap 1: for area hazards the GDACS point is the polygon centre.
    if etype in ("FL", "DR"):
        point_kind = "area_centre"
        point_note = ("Approximate: centre of GDACS's analyst-drawn affected area, "
                      "not where the event happened.")
    elif etype == "EQ":
        point_kind, point_note = "epicentre", "Epicentre (GDACS)."
    else:
        point_kind, point_note = "event_point", "Event location as published by GDACS."

    # Trap 3: "Magnitude 0" for floods/droughts is meaningless.
    sev = p.get("severitydata") or {}
    severity_text = (sev.get("severitytext") or "").strip()
    if etype in ("FL", "DR") or sev.get("severity") in (0, 0.0, None) \
            or severity_text.lower().startswith("magnitude 0"):
        severity_text = None

    magnitude = None
    if etype == "EQ":
        mm = re.search(r"magnitude\s*([\d.]+)", sev.get("severitytext") or "", re.I)
        magnitude = float(mm.group(1)) if mm else (float(sev["severity"]) if sev.get("severity") else None)

    countries = [c.get("countryname") for c in (p.get("affectedcountries") or []) if c.get("countryname")]
    return {
        "id": f"gdacs:{etype}:{p['eventid']}",
        "source": "GDACS",
        "source_id": str(p["eventid"]),
        "gdacs_type": etype,
        "episode_id": p.get("episodeid"),
        "hazard": hazard,
        "hazard_label": HAZARD_LABELS[hazard],
        "title": f"{HAZARD_LABELS[hazard]} — {p.get('country') or ', '.join(countries) or 'unknown area'}",
        "countries": countries or ([p["country"]] if p.get("country") else []),
        "country_note": "Country field as published by GDACS; impacts may extend across borders.",
        "alert": alert,
        "alert_score": p.get("alertscore"),
        "severity_text": severity_text,
        "glide": p.get("glide") or None,
        "start": _iso(start),
        "end": _iso(end),
        "is_current": str(p.get("iscurrent")).lower() == "true",
        "date_modified": _iso(_parse_dt(p.get("datemodified"))),
        "lat": float(coords[1]),
        "lon": float(coords[0]),
        "point_kind": point_kind,
        "point_note": point_note,
        "magnitude": magnitude,
        "report_url": (p.get("url") or {}).get("report"),
        "data_source": "live_gdacs",
    }


def fetch_gdacs(start: datetime, end: datetime, types: List[str], alerts: List[str]) -> Tuple[List[Dict], Optional[str]]:
    params = {
        "eventlist": ";".join(types),
        "fromdate": start.strftime("%Y-%m-%d"),
        "todate": end.strftime("%Y-%m-%d"),
        "alertlevel": ";".join(alerts),
    }
    events: List[Dict] = []
    seen = set()      # paging can repeat an event across pages
    try:
        for page in range(1, GDACS_MAX_PAGES + 1):
            resp = requests.get(GDACS_SEARCH_URL, params={**params, "pagenumber": page}, timeout=20)
            if resp.status_code == 204 or not resp.content:
                break
            resp.raise_for_status()
            feats = (resp.json() or {}).get("features") or []
            for f in feats:
                ev = normalize_gdacs_feature(f)
                if ev and ev["id"] not in seen:
                    seen.add(ev["id"])
                    events.append(ev)
            if len(feats) < GDACS_PAGE_SIZE:
                break
        else:
            return events, f"GDACS: stopped after {GDACS_MAX_PAGES} pages; narrow the filters to see all."
        return events, None
    except Exception as e:
        logger.warning(f"GDACS search failed: {e}")
        return events, f"GDACS unavailable: {e}"


# ---------------------------------------------------------------------------
# USGS
# ---------------------------------------------------------------------------

def normalize_usgs_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    p = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2 or not feature.get("id"):
        return None
    etype = (p.get("type") or "earthquake").lower()
    hazard = "landslide" if etype == "landslide" else ("earthquake" if etype == "earthquake" else None)
    if hazard is None:
        return None   # explosions, quarry blasts, etc. are not natural hazards
    t = datetime.fromtimestamp(p["time"] / 1000, tz=timezone.utc) if p.get("time") else None
    mag = p.get("mag")
    pager = (p.get("alert") or "").lower() or None
    label = "Landslide (seismic signal)" if hazard == "landslide" else "Earthquake"
    return {
        "id": f"usgs:{feature['id']}",
        "source": "USGS",
        "source_id": feature["id"],
        "hazard": hazard,
        "hazard_label": label,
        "title": f"M{mag} {label} — {p.get('place') or 'unknown location'}" if mag is not None
                 else f"{label} — {p.get('place') or 'unknown location'}",
        "countries": [],
        "alert": pager,   # USGS PAGER level (earthquakes only); None otherwise
        "alert_score": None,
        "severity_text": f"M{mag} ({p.get('magType')})" if mag is not None else None,
        "start": _iso(t),
        "end": None,
        "is_current": None,
        "date_modified": _iso(datetime.fromtimestamp(p["updated"] / 1000, tz=timezone.utc)) if p.get("updated") else None,
        "lat": float(coords[1]),
        "lon": float(coords[0]),
        "point_kind": "origin" if hazard == "landslide" else "epicentre",
        "point_note": ("Source location from USGS (for landslides, estimated from seismic "
                       "data and satellite imagery).") if hazard == "landslide" else "Epicentre (USGS).",
        "magnitude": mag,
        "mag_type": p.get("magType"),
        "usgs_status": p.get("status"),
        "report_url": p.get("url"),
        "data_source": "live_usgs",
    }


def fetch_usgs(start: datetime, end: datetime, eq_min_mag: float, include_eq: bool,
               include_landslide: bool) -> Tuple[List[Dict], Optional[str]]:
    """Two queries (trap 5): earthquakes at the user's magnitude, and
    landslide-type seismic events separately at a low threshold, so a
    reclassified event like Rasuwa is never filtered out."""
    base = {"format": "geojson", "starttime": start.strftime("%Y-%m-%d"),
            "endtime": (end + timedelta(days=1)).strftime("%Y-%m-%d"), "orderby": "time"}
    queries = []
    if include_eq:
        queries.append({**base, "eventtype": "earthquake", "minmagnitude": eq_min_mag, "limit": 2000})
    if include_landslide:
        queries.append({**base, "eventtype": "landslide", "minmagnitude": 3.0, "limit": 500})
    events, errors, seen = [], [], set()
    for q in queries:
        try:
            resp = requests.get(USGS_QUERY_URL, params=q, timeout=20)
            if resp.status_code == 204:
                continue
            resp.raise_for_status()
            for f in (resp.json() or {}).get("features") or []:
                ev = normalize_usgs_feature(f)
                if ev and ev["id"] not in seen:
                    seen.add(ev["id"])
                    events.append(ev)
        except Exception as e:
            logger.warning(f"USGS query ({q.get('eventtype')}) failed: {e}")
            errors.append(f"USGS {q.get('eventtype')}s unavailable: {e}")
    return events, ("; ".join(errors) or None)


# ---------------------------------------------------------------------------
# GDACS geometry (trap 6)
# ---------------------------------------------------------------------------

def get_gdacs_geometry(etype: str, eventid: str, episodeid: Optional[int] = None) -> Dict[str, Any]:
    key = ("geom", etype, str(eventid), episodeid)
    cached = _cache_get(key, GEOMETRY_CACHE_TTL)
    if cached is not None:
        return cached
    try:
        params = {"eventtype": etype, "eventid": eventid}
        if episodeid is not None:
            params["episodeid"] = episodeid
        resp = requests.get(GDACS_GEOMETRY_URL, params=params, timeout=25)
        resp.raise_for_status()
        result = select_affected_polygon(resp.json())
    except Exception as e:
        logger.warning(f"GDACS geometry failed for {etype} {eventid}: {e}")
        result = {"status": "unavailable", "geometry": None, "reason": str(e)[:200]}
    _cache_put(key, result)
    return result


def select_affected_polygon(fc: Dict[str, Any]) -> Dict[str, Any]:
    """Pick the 'Affected area' polygon; the 'Global area' feature is a
    duplicate in the cases we've checked, so it is never drawn twice."""
    feats = (fc or {}).get("features") or []
    polys = [f for f in feats if (f.get("geometry") or {}).get("type") in ("Polygon", "MultiPolygon")]
    chosen = next((f for f in polys if (f.get("properties") or {}).get("Class") == "Poly_Affected"), None) \
        or (polys[0] if polys else None)
    if not chosen:
        return {"status": "none", "geometry": None}
    props = chosen.get("properties") or {}
    return {
        "status": "ok",
        "geometry": chosen["geometry"],
        "polygon_date": _iso(_parse_dt(props.get("polygondate"))),
        "label": props.get("polygonlabel"),
        "caveat": ("GDACS reported area — analyst-drawn from administrative units. "
                   "It is NOT the flooded extent and may omit affected areas."),
        "source": "GDACS",
    }


# ---------------------------------------------------------------------------
# linking
# ---------------------------------------------------------------------------

def _hours_between(a: Optional[str], b: Optional[str]) -> Optional[float]:
    da, db = _parse_dt(a), _parse_dt(b)
    if not da or not db:
        return None
    return abs((da - db).total_seconds()) / 3600


def _max_alert(*alerts):
    best = None
    for a in alerts:
        if a and (best is None or ALERT_RANK.get(a, 0) > ALERT_RANK.get(best, 0)):
            best = a
    return best


def link_events(gdacs: List[Dict], usgs: List[Dict],
                geometry_lookup=None) -> List[Dict]:
    """
    Group events from both sources. Returns groups:
      {primary, related: [{event, relation, ...}], possible_links: [...],
       severity, marker: {lat, lon, kind, note}}

    Audit fixes (2 Oct 2026):
      A. Earthquake de-duplication runs FIRST over all GDACS EQ events, so a
         nearby cyclone/flood can no longer claim the quake before GDACS's
         own record of the same quake does.
      B. Area links are restricted to GDACS flood/drought <-> USGS
         LANDSLIDE events, and only MERGE when confirmed against the GDACS
         affected polygon ('linked'). An unconfirmed match ('possibly
         related') no longer swallows the USGS event: both stay in the
         list, with a cross-reference. Previously any quake within 200 km /
         48 h of a flood vanished from the list and from the counts.
      C. Group severity = the highest alert among the primary and its
         same-event record (GDACS alert vs USGS PAGER), so significance no
         longer depends on which records a query happened to fetch.

    Rules:
      - same quake: GDACS EQ + USGS earthquake within 100 km, 1 h,
        |dMag| <= 0.5 (when both magnitudes are known).
      - area link: GDACS FL/DR + USGS landslide within 48 h and 200 km of the
        GDACS point; distance from the USGS point to the GDACS polygon <=
        max(25 km, 2x USGS horizontal error) -> 'linked' (merged; marker moves
        to the USGS origin). Otherwise 'possibly related' (not merged).
    """
    used_usgs = set()
    related_by_g: Dict[str, List[Dict]] = {g["id"]: [] for g in gdacs}
    possible: Dict[str, List[Dict]] = {}

    # Pass 1 (fix A): same-quake de-duplication, closest match first.
    eq_pairs = []
    for g in gdacs:
        if g["hazard"] != "earthquake":
            continue
        for u in usgs:
            if u["hazard"] != "earthquake":
                continue
            dh = _hours_between(g["start"], u["start"])
            if dh is None or dh > EQ_DUPLICATE_H:
                continue
            dist = haversine_km(g["lat"], g["lon"], u["lat"], u["lon"])
            if dist > EQ_DUPLICATE_KM:
                continue
            if g.get("magnitude") is not None and u.get("magnitude") is not None \
                    and abs(g["magnitude"] - u["magnitude"]) > EQ_DUPLICATE_DMAG:
                continue
            eq_pairs.append((dist, dh, g, u))
    used_g_eq = set()
    for dist, dh, g, u in sorted(eq_pairs, key=lambda x: (x[0], x[1])):
        if g["id"] in used_g_eq or u["id"] in used_usgs:
            continue
        related_by_g[g["id"]].append({"event": u, "relation": "same_event", "distance_km": round(dist, 1)})
        used_g_eq.add(g["id"])
        used_usgs.add(u["id"])

    # Pass 2 (fix B): area hazards <-> USGS landslides only.
    for g in gdacs:
        if g.get("gdacs_type") not in ("FL", "DR"):
            continue
        for u in usgs:
            if u["id"] in used_usgs or u["hazard"] != "landslide":
                continue
            dh = _hours_between(g["start"], u["start"])
            if dh is None or dh > LINK_TIME_WINDOW_H:
                continue
            dist = haversine_km(g["lat"], g["lon"], u["lat"], u["lon"])
            if dist > LINK_CANDIDATE_KM:
                continue
            rel = {"event": u, "relation": "possibly_related", "distance_km": round(dist, 1),
                   "distance_basis": "GDACS point"}
            geom = geometry_lookup(g) if geometry_lookup is not None else None
            if geom and geom.get("geometry"):
                dpoly = distance_to_geometry_km(u["lat"], u["lon"], geom["geometry"])
                buffer_km = max(LINK_POLY_BUFFER_KM, 2 * (u.get("horizontal_error_km") or 0))
                rel["distance_to_area_km"] = dpoly
                rel["buffer_km"] = buffer_km
                if dpoly is not None and dpoly <= buffer_km:
                    rel["relation"] = "linked"
                    rel["distance_basis"] = "GDACS reported area"
            if rel["relation"] == "linked":
                related_by_g[g["id"]].append(rel)
                used_usgs.add(u["id"])
            else:
                note = {"id": u["id"], "distance_km": rel["distance_km"]}
                possible.setdefault(g["id"], []).append(note)
                possible.setdefault(u["id"], []).append({"id": g["id"], "distance_km": rel["distance_km"]})

    groups: List[Dict] = []
    for g in gdacs:
        related = related_by_g[g["id"]]
        marker = {"lat": g["lat"], "lon": g["lon"], "kind": g["point_kind"], "note": g["point_note"]}
        origin = next((r for r in related if r["relation"] == "linked"), None)
        if origin and g["point_kind"] == "area_centre":
            ue = origin["event"]
            marker = {"lat": ue["lat"], "lon": ue["lon"], "kind": "usgs_origin",
                      "note": "Located at the linked USGS origin (more precise than GDACS's area centre)."}
        same = [r["event"].get("alert") for r in related if r["relation"] == "same_event"]
        groups.append({"primary": g, "related": related, "possible_links": possible.get(g["id"], []),
                       "severity": _max_alert(g.get("alert"), *same), "marker": marker})

    for u in usgs:
        if u["id"] not in used_usgs:
            groups.append({"primary": u, "related": [], "possible_links": possible.get(u["id"], []),
                           "severity": u.get("alert"),
                           "marker": {"lat": u["lat"], "lon": u["lon"], "kind": u["point_kind"],
                                      "note": u["point_note"]}})
    return groups


# ---------------------------------------------------------------------------
# status: ACTIVE NOW vs PREVIOUS (source status + end dates, not recency)
# ---------------------------------------------------------------------------

# Max age of the latest episode end-date for an event GDACS still flags as
# current. Guards against stale flags; generous for slow-updating hazards.
ACTIVE_MAX_STALENESS_H = {"TC": 48, "FL": 120, "WF": 120, "VO": 30 * 24, "DR": 60 * 24}


def group_status(group: Dict[str, Any], now: Optional[datetime] = None) -> Tuple[str, str]:
    """
    'active' only when the SOURCE says the event is current AND its own end
    date is consistent with that. Never inferred from "happened recently".
      - GDACS: requires iscurrent == true (verified on real data: GDACS sets
        it from the episode end date — about the last 3-4 days — not from
        record edits), the event must have a duration (from != to;
        earthquakes are instantaneous), and the latest episode must end
        within a hazard-specific window (stale-flag guard).
      - USGS: earthquakes / landslides are instantaneous records with no
        "ongoing" status -> always 'ended' (they appear under Previous).
    """
    now = now or datetime.now(timezone.utc)
    p = group["primary"]
    if p["source"] != "GDACS":
        return "ended", "USGS records an instantaneous event; USGS has no 'ongoing' status."
    start, end = _parse_dt(p.get("start")), _parse_dt(p.get("end"))
    if not p.get("is_current"):
        return "ended", f"GDACS does not list this event as current (episode ended {_iso(end) or 'unknown'})."
    if not start or not end or end <= start:
        return "ended", "Instantaneous event (no duration); GDACS's current flag only means it is recent."
    max_h = ACTIVE_MAX_STALENESS_H.get(p.get("gdacs_type"), 120)
    age_h = (now - end).total_seconds() / 3600
    if age_h > max_h:
        return "ended", (f"GDACS still flags it current, but its latest episode ended {round(age_h / 24, 1)} days ago "
                         f"(> {round(max_h / 24, 1)} days); treated as ended.")
    return "active", f"GDACS lists this event as current; latest episode runs to {_iso(end)}."


# ---------------------------------------------------------------------------
# public: list
# ---------------------------------------------------------------------------

def _overlaps(ev: Dict, start: datetime, end: datetime) -> bool:
    s = _parse_dt(ev.get("start"))
    e = _parse_dt(ev.get("end")) or s
    if not s:
        return False
    return s <= end + timedelta(days=1) and e >= start


def list_disasters(start: datetime, end: datetime, hazards: List[str], min_alert: str,
                   eq_min_mag: float, now: Optional[datetime] = None) -> Dict[str, Any]:
    if (end - start).days > MAX_RANGE_DAYS:
        start = end - timedelta(days=MAX_RANGE_DAYS)
    hazards = [h for h in hazards if h in HAZARD_LABELS] or list(HAZARD_LABELS)
    key = ("list", start.date(), end.date(), tuple(sorted(hazards)), min_alert, eq_min_mag)
    cached = _cache_get(key, LIST_CACHE_TTL)
    if cached is not None:
        return cached

    gdacs_codes = [code for code, hz in GDACS_TYPES.items() if hz in hazards]
    alerts = {"all": ["green", "orange", "red"], "orange": ["orange", "red"], "red": ["red"]}.get(min_alert, ["green", "orange", "red"])

    sources = {}
    gdacs_events, gerr = (fetch_gdacs(start, end, gdacs_codes, alerts) if gdacs_codes else ([], None))
    sources["GDACS"] = {"status": "error" if gerr and not gdacs_events else ("partial" if gerr else "ok"),
                        "count": len(gdacs_events), "message": gerr}
    usgs_events, uerr = fetch_usgs(start, end, eq_min_mag, "earthquake" in hazards, "landslide" in hazards) \
        if ("earthquake" in hazards or "landslide" in hazards) else ([], None)
    sources["USGS"] = {"status": "error" if uerr and not usgs_events else ("partial" if uerr else "ok"),
                       "count": len(usgs_events), "message": uerr}

    gdacs_events = [e for e in gdacs_events if _overlaps(e, start, end)]
    usgs_events = [e for e in usgs_events if _overlaps(e, start, end)]

    # Fetch polygons only for GDACS area events that actually have a USGS
    # candidate nearby (few), so markers can move to a real origin.
    def geometry_lookup(g):
        if g["gdacs_type"] not in ("FL", "DR"):
            return None
        return get_gdacs_geometry(g["gdacs_type"], g["source_id"], g.get("episode_id"))

    groups = link_events(gdacs_events, usgs_events, geometry_lookup=geometry_lookup)
    for gr in groups:
        gr["status"], gr["status_basis"] = group_status(gr, now)
    # Most severe first; within the same level, most recent first.
    groups.sort(key=lambda gr: gr["primary"].get("start") or "", reverse=True)
    groups.sort(key=lambda gr: (-ALERT_RANK.get(gr.get("severity") or "", 0),
                                -(gr["primary"].get("magnitude") or 0)))

    result = {
        "active_count": sum(1 for gr in groups if gr["status"] == "active"),
        "from": start.date().isoformat(),
        "to": end.date().isoformat(),
        "groups": groups,
        "count": len(groups),
        "sources": sources,
        "notes": [
            "Not an official warning system. Always follow national authorities.",
            "No events listed means none were reported by these sources for this filter — not that nothing happened.",
        ],
        "generated_at": _iso(datetime.now(timezone.utc)),
    }
    _cache_put(key, result)
    return result


# ---------------------------------------------------------------------------
# public: details
# ---------------------------------------------------------------------------

_SENDAI_LABELS = [
    (re.compile(r"out of contact|missing", re.I), "Missing / out of contact"),
    (re.compile(r"fatalit|dead|death|killed", re.I), "Deaths"),
    (re.compile(r"injur", re.I), "Injured"),
    (re.compile(r"evacuat", re.I), "Evacuated"),
    (re.compile(r"displac", re.I), "Displaced"),
    (re.compile(r"rescued", re.I), "Rescued"),
    (re.compile(r"bridge", re.I), "Bridges destroyed"),
    (re.compile(r"house|building|home", re.I), "Houses / buildings damaged"),
]


def _sendai_label(entry: Dict[str, Any]) -> str:
    text = f"{entry.get('description') or ''} {entry.get('sendainame') or ''}"
    for pattern, label in _SENDAI_LABELS:
        if pattern.search(text):
            return label
    return (entry.get("sendainame") or "Other").strip().capitalize()


def summarize_sendai(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Trap 2: label from the description; keep only the latest value per
    (label, country) by the period it covers (expires_date, then
    dateinsert only if that is missing); entries covering the same period
    are a genuine tie — keep the highest and say so."""
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    tie_flags = set()
    for e in entries or []:
        try:
            value = int(float(str(e.get("sendaivalue")).replace(",", "")))
        except (TypeError, ValueError):
            continue
        label = _sendai_label(e)
        country = e.get("country") or "Unknown"
        k = (label, country)
        # The period a figure covers is expires_date. dateinsert is only a
        # fallback: entries of one batch differ by milliseconds there, so
        # using it as a tie-break would make "latest" mean "inserted 10 ms
        # later" (Rasuwa: 3,925 would beat 4,247 for the same 31 Aug period).
        period = e.get("expires_date") or e.get("dateinsert") or ""
        cur = best.get(k)
        if cur is None or period > cur["_period"]:
            best[k] = {"_period": period, "value": value, "entry": e}
            tie_flags.discard(k)
        elif period == cur["_period"] and value != cur["value"]:
            tie_flags.add(k)
            if value > cur["value"]:
                best[k] = {"_period": period, "value": value, "entry": e}
    # Display order (matching order of _SENDAI_LABELS is about precedence, not display).
    order = ["Deaths", "Missing / out of contact", "Injured", "Evacuated", "Displaced",
             "Rescued", "Bridges destroyed", "Houses / buildings damaged"]
    out = []
    for (label, country), v in best.items():
        e = v["entry"]
        out.append({
            "label": label,
            "country": country,
            "region": e.get("region"),
            "value": v["value"],
            "covers_until": (e.get("expires_date") or "")[:10] or None,
            "as_of": (e.get("dateinsert") or "")[:10] or None,
            "note": "Several figures reported for the same period; highest shown." if (label, country) in tie_flags else None,
        })
    out.sort(key=lambda r: (order.index(r["label"]) if r["label"] in order else 99, r["country"]))
    return out


def get_gdacs_detail(etype: str, eventid: str) -> Dict[str, Any]:
    key = ("gdacs_detail", etype, str(eventid))
    cached = _cache_get(key, DETAIL_CACHE_TTL)
    if cached is not None:
        return cached
    try:
        resp = requests.get(GDACS_EVENT_URL, params={"eventtype": etype, "eventid": eventid}, timeout=20)
        resp.raise_for_status()
        result = parse_gdacs_detail(resp.json())
    except Exception as e:
        logger.warning(f"GDACS detail failed for {etype} {eventid}: {e}")
        result = {"status": "unavailable", "reason": str(e)[:200]}
    _cache_put(key, result)
    return result


def parse_gdacs_detail(feature: Dict[str, Any]) -> Dict[str, Any]:
    ev = normalize_gdacs_feature(feature)
    if not ev:
        return {"status": "unavailable", "reason": "Unrecognised GDACS response"}
    p = feature.get("properties") or {}
    impacts = summarize_sendai(p.get("sendai") or [])
    as_of = max((r["as_of"] for r in impacts if r["as_of"]), default=None)
    images = p.get("images") or {}
    return {
        "status": "ok",
        "event": ev,
        "impacts": impacts,
        "impacts_as_of": as_of,
        "impacts_source": "GDACS (Sendai framework entries)",
        "alert_explanation": {
            "red": "GDACS estimates a HIGH humanitarian impact (model + analyst estimate, not an official warning).",
            "orange": "GDACS estimates a MEDIUM humanitarian impact (model + analyst estimate).",
            "green": "GDACS estimates a LOW humanitarian impact (model + analyst estimate).",
        }.get(ev["alert"] or ""),
        "maps": {k: images.get(k) for k in ("overviewmap", "floodmap_cached", "populationmap") if images.get(k)},
        "geometry_available": bool((p.get("url") or {}).get("geometry")),
    }


def get_usgs_detail(eventid: str) -> Dict[str, Any]:
    key = ("usgs_detail", eventid)
    cached = _cache_get(key, DETAIL_CACHE_TTL)
    if cached is not None:
        return cached
    try:
        resp = requests.get(USGS_QUERY_URL, params={"format": "geojson", "eventid": eventid}, timeout=20)
        resp.raise_for_status()
        result = parse_usgs_detail(resp.json())
    except Exception as e:
        logger.warning(f"USGS detail failed for {eventid}: {e}")
        result = {"status": "unavailable", "reason": str(e)[:200]}
    _cache_put(key, result)
    return result


def _product_text(products: Dict, name: str) -> Optional[str]:
    for prod in products.get(name) or []:
        contents = prod.get("contents") or {}
        body = contents.get("") if isinstance(contents, dict) else None
        if isinstance(body, dict) and body.get("bytes"):
            return _strip_html(body["bytes"])
    return None


def parse_usgs_detail(feature: Dict[str, Any]) -> Dict[str, Any]:
    # An eventid query returns a single Feature (verified with us7000tbwb);
    # accept a FeatureCollection too rather than reporting "unavailable".
    if (feature or {}).get("type") == "FeatureCollection":
        feats = feature.get("features") or []
        feature = feats[0] if feats else {}
    ev = normalize_usgs_feature(feature)
    if not ev:
        return {"status": "unavailable", "reason": "Unrecognised USGS response"}
    products = (feature.get("properties") or {}).get("products") or {}
    origin_props = ((products.get("origin") or [{}])[0].get("properties") or {})
    herr = origin_props.get("horizontal-error")
    ev["horizontal_error_km"] = float(herr) if herr not in (None, "") else None

    header = _product_text(products, "general-header") or ""
    general = _product_text(products, "general-text") or ""
    m = re.search(r"initially reported as an? magnitude ([\d.]+) (\w+)", header + " " + general, re.I)
    reclass = None
    if m:
        reclass = (f"First published as an M{m.group(1)} {m.group(2)}; USGS later determined it was "
                   f"a {ev['hazard_label'].lower()} (current classification).")

    impact = _product_text(products, "impact-text")
    as_of = None
    if impact:
        dm = re.search(r"As of ([A-Z][a-z]+ \d{1,2}, \d{4})", impact)
        as_of = dm.group(1) if dm else None
    return {
        "status": "ok",
        "event": ev,
        "reclassification": reclass,
        "impact_text": impact,
        "impact_as_of": as_of,
        "impact_source": "USGS event page (impact summary)",
    }
