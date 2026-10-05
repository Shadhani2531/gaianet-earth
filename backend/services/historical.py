"""
Historical Extremes — hybrid architecture.

LIVE (authoritative, refreshed daily, last-good snapshot on disk):
  - NOAA NCEI / WDS hazards API (HazEL):
      earthquakes        /hazard-service/api/v1/earthquakes      (verified live, 6,697 records)
      tsunami events     /hazard-service/api/v1/tsunamis/events  (path not independently verified)
      volcanic eruptions /hazard-service/api/v1/volcanoes        (path not independently verified)
    Unverified paths fail safely: the source is reported 'unavailable' and
    nothing is invented.
  - USGS earthquake catalogue (FDSN) — instrumental moment magnitudes.

BASELINE (data/historical_baseline.json): small, human-verified, sourced.
  Only what no live dataset provides: floods, tropical cyclones, tornadoes,
  WMO-adjudicated records, and 'overlay' RANGES attached to NCEI records
  where published estimates disagree (NCEI stores one figure).

Rules:
  - Every casualty figure keeps its source; ranges are shown, never merged.
  - Linked records (earthquake -> tsunami -> eruption) are one disaster;
    deaths are NOT summed (NCEI 'deathsTotal' already includes secondary
    effects) — the group takes the largest documented total.
  - Never promote preliminary casualty figures: events less than
    PRELIMINARY_DAYS old cannot enter the Deadliest ranking or take a
    casualty record; they are reported as 'pending review'.
  - Physical records (magnitude) only from USGS-reviewed events at least
    PRELIMINARY_PHYSICAL_DAYS old.
"""

import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

NCEI_BASE = "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1"
NCEI_DATASETS = {
    "earthquakes": f"{NCEI_BASE}/earthquakes",
    "tsunamis": f"{NCEI_BASE}/tsunamis/events",
    "volcanoes": f"{NCEI_BASE}/volcanoes",
}
NCEI_CITATIONS = {
    "earthquakes": "NCEI/WDS Global Significant Earthquake Database, doi:10.7289/V5TD9V7K",
    "tsunamis": "NCEI/WDS Global Historical Tsunami Database, doi:10.7289/V5PN93H7",
    "volcanoes": "NCEI/WDS Global Significant Volcanic Eruptions Database, doi:10.7289/V5JW8BSH",
}
USGS_QUERY = "https://earthquake.usgs.gov/fdsnws/event/1/query"

BACKEND_DIR = Path(__file__).resolve().parents[1]
BASELINE_PATH = BACKEND_DIR / "data" / "historical_baseline.json"
CACHE_DIR = BACKEND_DIR / "data" / "historical_cache"

REFRESH_AFTER_S = 24 * 3600
PRELIMINARY_DAYS = 365            # casualty figures younger than this are 'pending review'
PRELIMINARY_PHYSICAL_DAYS = 30    # magnitude records need USGS 'reviewed' + 30 days
DEADLIEST_MIN_DEATHS = 1000
DEADLIEST_LIMIT = 50            # 50 so e.g. Tambora (~71,000) is reachable in "All recorded history"
ERA_SINCE = 1900

HAZARD_LABELS = {
    "earthquake": "Earthquake", "tsunami": "Tsunami", "volcano": "Volcanic eruption",
    "flood": "Flood", "tropical_cyclone": "Tropical cyclone", "tornado": "Tornado",
    "earthquake_tsunami": "Earthquake & tsunami",
    "volcano_tsunami": "Volcanic eruption & tsunami",
    "volcanic_event": "Volcanic event (non-eruptive)",
    "landslide": "Landslide / debris flow",
    "heatwave": "Heatwave",
}
# Heatwave mortality is never a body count; it is estimated statistically.
METRIC_LABELS = {
    "excess_deaths": "Estimated excess deaths (observed minus expected)",
    "heat_attributable": "Estimated heat-attributable deaths (epidemiological model)",
}
CONFIDENCE_LABELS = {
    "official_record": "WMO-adjudicated record",
    "measured": "Measured",
    "medium": "Moderate — sources broadly agree",
    "low": "Low — historical estimates differ widely",
    "disputed": "Disputed — estimates differ by several times",
    "single_source": "Single figure from NCEI — uncertainty not quantified",
    "chronicle": "Pre-1900 single figure from historical records — low confidence",
}

_locks = {k: threading.Lock() for k in list(NCEI_DATASETS) + ["usgs_largest"]}
_mem: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# last-good snapshot cache
# ---------------------------------------------------------------------------

def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def _load_snapshot(name: str) -> Optional[Dict[str, Any]]:
    if name in _mem:
        return _mem[name]
    try:
        with open(_cache_path(name), "r", encoding="utf-8") as f:
            snap = json.load(f)
        _mem[name] = snap
        return snap
    except (OSError, ValueError):
        return None


def _save_snapshot(name: str, items: List[Dict[str, Any]], source_url: str) -> Dict[str, Any]:
    snap = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "source_url": source_url, "items": items}
    _mem[name] = snap
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _cache_path(name).with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f)
        tmp.replace(_cache_path(name))          # atomic: never leave a half-written cache
    except OSError as e:
        logger.warning(f"Could not write historical cache {name}: {e}")
    return snap


def _age_s(snap: Optional[Dict[str, Any]]) -> float:
    if not snap:
        return float("inf")
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(snap["retrieved_at"])).total_seconds()
    except (KeyError, ValueError):
        return float("inf")


def get_dataset(name: str, fetcher: Callable[[], List[Dict[str, Any]]], source_url: str,
                force: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Fresh data if possible; otherwise the last-good snapshot; never invented."""
    snap = _load_snapshot(name)
    if snap and not force and _age_s(snap) < REFRESH_AFTER_S:
        return snap["items"], {"status": "live", "retrieved_at": snap["retrieved_at"]}
    with _locks[name]:
        snap = _load_snapshot(name)
        if snap and not force and _age_s(snap) < REFRESH_AFTER_S:
            return snap["items"], {"status": "live", "retrieved_at": snap["retrieved_at"]}
        try:
            items = fetcher()
            if not items:
                raise ValueError("empty response")
            snap = _save_snapshot(name, items, source_url)
            return items, {"status": "live", "retrieved_at": snap["retrieved_at"]}
        except Exception as e:
            logger.warning(f"Historical source {name} refresh failed: {e}")
            if snap:
                return snap["items"], {"status": "cached", "retrieved_at": snap["retrieved_at"],
                                       "message": f"Refresh failed ({str(e)[:120]}); showing last good copy."}
            return [], {"status": "unavailable", "message": f"Source unreachable and no cached copy ({str(e)[:120]})."}


def _fetch_ncei(url: str) -> List[Dict[str, Any]]:
    first = requests.get(url, params={"page": 1}, timeout=25)
    first.raise_for_status()
    body = first.json()
    items = list(body.get("items") or [])
    total = int(body.get("totalPages") or 1)
    if total > 1:
        def page(n):
            r = requests.get(url, params={"page": n}, timeout=25)
            r.raise_for_status()
            return r.json().get("items") or []
        with ThreadPoolExecutor(max_workers=6) as pool:
            for chunk in pool.map(page, range(2, min(total, 80) + 1)):
                items.extend(chunk)
    return items


def _fetch_usgs_largest() -> List[Dict[str, Any]]:
    r = requests.get(USGS_QUERY, params={"format": "geojson", "starttime": "1900-01-01",
                                         "minmagnitude": 8.6, "orderby": "magnitude", "limit": 40}, timeout=25)
    r.raise_for_status()
    return r.json().get("features") or []


def load_sources(force: bool = False) -> Tuple[Dict[str, List[Dict]], Dict[str, Dict]]:
    data, status = {}, {}
    for name, url in NCEI_DATASETS.items():
        data[name], status[f"NCEI {name}"] = get_dataset(name, lambda u=url: _fetch_ncei(u), url, force)
    data["usgs_largest"], status["USGS catalogue"] = get_dataset("usgs_largest", _fetch_usgs_largest, USGS_QUERY, force)
    return data, status


def load_baseline(path: Path = BASELINE_PATH) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_DIRECTIONS = {"N": "Northern", "S": "Southern", "E": "Eastern", "W": "Western", "NE": "Northeastern",
               "NW": "Northwestern", "SE": "Southeastern", "SW": "Southwestern", "C": "Central"}
_SMALL_WORDS = {"and", "of", "the", "de", "del", "la", "y", "da", "do", "di", "off", "near"}


def _cap_word(w: str, first: bool) -> str:
    low = w.lower()
    if not first and low in _SMALL_WORDS:
        return low
    # Capitalise each hyphen part's first letter only ("CHAO-T'UNG" -> "Chao-T'ung",
    # not Python's .title() result "Chao-T'Ung").
    out, cap_next = [], True
    for ch in low:
        if ch.isalpha():
            out.append(ch.upper() if cap_next else ch)
            cap_next = False
        else:
            out.append(ch)
            if ch in "-(/":
                cap_next = True
    return "".join(out)


_DIRECTION_WORDS = {v.upper() for v in _DIRECTIONS.values()}


def _clean_part(part: str) -> str:
    words = [w for w in part.replace(",", " , ").split() if w]
    result, first, skip_comma = [], True, False
    for i, w in enumerate(words):
        if w == ",":
            if skip_comma:            # "N, XINJIANG" -> "Northern Xinjiang" (abbreviation only)
                skip_comma = False
                continue
            result.append(",")
            continue
        skip_comma = False
        up = w.upper()
        # Direction ABBREVIATIONS before a place: "SW HONSHU" -> "Southwestern Honshu".
        # Spelled-out words ("NORTHERN, PISCO") are left exactly as NCEI wrote them.
        if up in _DIRECTIONS and (i + 1 < len(words)):
            result.append(_DIRECTIONS[up])
            skip_comma = True
            first = False
            continue
        result.append(_cap_word(w, first))
        first = False
    return " ".join(result).replace(" ,", ",").strip(" ,")


def _is_direction_only(part: str) -> bool:
    up = part.strip().upper()
    return up in _DIRECTIONS or up in _DIRECTION_WORDS


def volcano_display_name(name: str) -> str:
    """Smithsonian catalogue names are inverted: 'Ruiz, Nevado del' -> 'Nevado del Ruiz',
    'Fournaise, Piton de la' -> 'Piton de la Fournaise'."""
    parts = [p.strip() for p in str(name).split(",")]
    if len(parts) == 2 and parts[0] and parts[1]:
        return _clean_part(f"{parts[1]} {parts[0]}")
    return _clean_part(str(name))


def format_place(location_name: Optional[str], country: Optional[str] = None) -> str:
    """'CHINA:  HEBEI PROVINCE:  TANGSHAN' -> 'Tangshan, Hebei Province, China'."""
    if not location_name:
        return _clean_part(country or "Unknown location")
    raw = [p.strip() for p in location_name.split(":") if p.strip()]
    raw.reverse()
    # A segment that is only a direction ('N', 'SOUTHEASTERN') qualifies the
    # broader segment after it: '... : XINJIANG : N' -> 'Northern Xinjiang'.
    merged, pending = [], None
    for seg in raw:
        if _is_direction_only(seg):
            up = seg.strip().upper()
            pending = _DIRECTIONS.get(up, up.capitalize())
            continue
        text = _clean_part(seg)
        if pending:
            text = f"{pending} {text}"
            pending = None
        merged.append(text)
    if pending:
        merged.append(pending)
    return ", ".join(p for p in merged[:3] if p)


def _num(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def normalize_ncei(kind: str, rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if rec.get("id") is None:
        return None
    # 'publish' is respected for earthquakes and tsunamis. In the volcano
    # dataset EVERY record has publish=false (verified on the live API,
    # 4 Oct 2026), so there it does not mean "withdrawn" and is ignored.
    if kind != "volcanoes" and not rec.get("publish", True):
        return None
    lat, lon = _num(rec.get("latitude")), _num(rec.get("longitude"))
    hazard = {"earthquakes": "earthquake", "tsunamis": "tsunami", "volcanoes": "volcano"}[kind]
    deaths_total = _num(rec.get("deathsTotal"))
    deaths_direct = _num(rec.get("deaths"))
    place = format_place(rec.get("locationName") or rec.get("location"), rec.get("country"))
    if kind == "volcanoes" and rec.get("name"):
        place = f"{volcano_display_name(rec['name'])}, {_clean_part(str(rec.get('country') or ''))}".strip(", ")
    links = {
        "earthquake": rec.get("earthquakeEventId") or rec.get("eqEventId") or (rec["id"] if kind == "earthquakes" else None),
        "tsunami": rec.get("tsunamiEventId") or (rec["id"] if kind == "tsunamis" else None),
        "volcano": rec.get("volcanoEventId") or (rec["id"] if kind == "volcanoes" else None),
    }
    return {
        "id": f"ncei-{kind}-{rec['id']}",
        "kind": kind,
        "ncei_id": rec["id"],
        "hazard": hazard,
        "year": rec.get("year"), "month": rec.get("month"), "day": rec.get("day"),
        "lat": lat, "lon": lon,
        "place": place,
        "country": (rec.get("country") or "").title() or None,
        "deaths": deaths_total if deaths_total is not None else deaths_direct,
        "deaths_direct": deaths_direct,
        "deaths_order": rec.get("deathsAmountOrderTotal") or rec.get("deathsAmountOrder"),
        "magnitude": _num(rec.get("eqMagnitude")),
        "vei": _num(rec.get("vei")),
        "max_water_height_m": _num(rec.get("maxWaterHeight")),
        # NCEI volcano 'eruption': false marks non-eruptive events (e.g. gas releases)
        "eruption": (rec.get("eruption") is not False) if kind == "volcanoes" else None,
        "links": links,
    }


def group_linked(events: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Union records that NCEI cross-links (earthquake <-> tsunami <-> eruption)."""
    parent: Dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    keyed = {}
    for ev in events:
        own = f"{ev['hazard']}:{ev['ncei_id']}"
        keyed[own] = ev
        find(own)
        for h, lid in ev["links"].items():
            if lid is not None:
                union(own, f"{h}:{lid}")
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for key, ev in keyed.items():
        groups.setdefault(find(key), []).append(ev)
    return list(groups.values())


def _date_tuple(y, m=None, d=None) -> Tuple[int, int, int]:
    return (int(y), int(m or 0), int(d or 0))


def _age_days(y, m=None, d=None, now: Optional[datetime] = None) -> Optional[float]:
    now = now or datetime.now(timezone.utc)
    try:
        if y is None or int(y) < 1:
            return None
        dt = datetime(int(y), int(m or 1), int(d or 1), tzinfo=timezone.utc)
        return (now - dt).total_seconds() / 86400
    except (ValueError, TypeError):
        return None


def build_ncei_disasters(data: Dict[str, List[Dict]]) -> List[Dict[str, Any]]:
    events = []
    for kind in ("earthquakes", "tsunamis", "volcanoes"):
        for rec in data.get(kind) or []:
            ev = normalize_ncei(kind, rec)
            if ev:
                events.append(ev)
    disasters = []
    for members in group_linked(events):
        primary = max(members, key=lambda e: (e["deaths"] or -1, e["hazard"] == "earthquake"))
        hazards = {m["hazard"] for m in members}
        deaths_vals = [m["deaths"] for m in members if m["deaths"] is not None]
        total = max(deaths_vals) if deaths_vals else None
        # Deaths CAUSED BY the tsunami: the tsunami record's own 'deaths'
        # field, not the linked disaster's total (Haiti 2010: ~316,000 total,
        # almost all from shaking; its local tsunami killed very few).
        tsu = [m["deaths_direct"] for m in members if m["hazard"] == "tsunami" and m["deaths_direct"] is not None]
        tsunami_deaths = max(tsu) if tsu else None
        if {"earthquake", "tsunami"} <= hazards and tsunami_deaths is not None and total \
                and tsunami_deaths >= max(1000, 0.1 * total):
            hazard = "earthquake_tsunami"          # the tsunami was a major cause of death
        elif "earthquake" in hazards:
            hazard = "earthquake"                  # a linked minor tsunami is noted in the card
        elif "volcano" in hazards:
            erupted = any(m.get("eruption") for m in members if m["hazard"] == "volcano")
            major_tsunami = tsunami_deaths is not None and total and tsunami_deaths >= max(1000, 0.1 * total)
            hazard = ("volcano_tsunami" if major_tsunami else "volcano") if erupted else "volcanic_event"
        elif hazards == {"tsunami"} and any(m["links"].get("volcano") for m in members):
            # Tsunami record whose source eruption is not in our data (e.g.
            # Mount Pelée 1902): the disaster is the ERUPTION, not a tsunami.
            hazard = "volcano"
        elif hazards == {"tsunami"} and any(m["links"].get("earthquake") for m in members):
            hazard = "earthquake"
        else:
            hazard = primary["hazard"]
        with_coords = [m for m in members if m["lat"] is not None and m["lon"] is not None]
        anchor = next((m for m in with_coords if m["hazard"] in ("earthquake", "volcano")), None) or \
            (with_coords[0] if with_coords else primary)
        disasters.append({
            "id": primary["id"],
            "source": "NCEI",
            "hazard": hazard,
            "hazard_label": HAZARD_LABELS.get(hazard, hazard.title()),
            "year": primary["year"], "month": primary["month"], "day": primary["day"],
            "lat": anchor["lat"], "lon": anchor["lon"], "location_approximate": False,
            "place": anchor["place"],
            "ncei_deaths": total,
            "tsunami_deaths": tsunami_deaths,
            "has_tsunami": "tsunami" in hazards,
            "magnitude": next((m["magnitude"] for m in members if m["magnitude"] is not None), None),
            "vei": next((m["vei"] for m in members if m["vei"] is not None and m.get("eruption", True)), None),
            "members": [{"kind": m["kind"], "ncei_id": m["ncei_id"], "deaths": m["deaths"],
                         "deaths_direct": m["deaths_direct"]} for m in members],
        })
    return disasters


# ---------------------------------------------------------------------------
# baseline overlays + standalone events
# ---------------------------------------------------------------------------

def _hazard_matches(overlay_hazard: str, disaster_hazard: str) -> bool:
    if overlay_hazard == "earthquake":
        return disaster_hazard in ("earthquake", "earthquake_tsunami")
    if overlay_hazard == "tsunami":
        return disaster_hazard in ("tsunami", "earthquake_tsunami", "volcano_tsunami")
    if overlay_hazard == "volcano":
        return disaster_hazard in ("volcano", "volcano_tsunami")
    return overlay_hazard == disaster_hazard


def find_overlay_match(entry: Dict[str, Any], disasters: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    m = entry.get("match") or {}
    loc = entry["location"]
    best, best_d = None, None
    for d in disasters:
        if d["year"] != m.get("year") or not _hazard_matches(entry["hazard"], d["hazard"]):
            continue
        if m.get("month") and d.get("month") and d["month"] != m["month"]:
            continue
        if m.get("day") and d.get("day") and abs(int(d["day"]) - int(m["day"])) > 2:
            continue
        if d["lat"] is None or d["lon"] is None:
            continue
        dist = haversine_km(loc["lat"], loc["lon"], d["lat"], d["lon"])
        if dist <= m.get("radius_km", 150) and (best_d is None or dist < best_d):
            best, best_d = d, dist
    return best


def _baseline_item(entry: Dict[str, Any]) -> Dict[str, Any]:
    dt = entry["date"]
    return {
        "id": f"baseline-{entry['id']}",
        "source": "Baseline",
        "hazard": entry["hazard"],
        "hazard_label": HAZARD_LABELS.get(entry["hazard"], entry["hazard"].title()),
        "year": dt.get("year"), "month": dt.get("month"), "day": dt.get("day"),
        "lat": entry["location"]["lat"], "lon": entry["location"]["lon"],
        "location_approximate": entry["location"].get("approximate", False),
        "place": entry["location"].get("label"),
        "ncei_deaths": None, "magnitude": None, "vei": None, "members": [],
    }


def assemble_items(disasters: List[Dict[str, Any]], baseline: Dict[str, Any],
                   ncei_available: bool) -> List[Dict[str, Any]]:
    """Attach overlays to NCEI records; add standalone baseline events."""
    items = [dict(d) for d in disasters]
    by_id = {d["id"]: d for d in items}
    for entry in baseline["entries"]:
        if entry["kind"] in ("record_only", "heatwave"):
            continue      # heatwaves have their own view; never mixed into Deadliest
        target = None
        if entry["kind"] == "overlay":
            match = find_overlay_match(entry, disasters)
            if match:
                target = by_id[match["id"]]
        if target is None:
            # Standalone event, or an overlay whose NCEI record is missing /
            # unavailable: the verified baseline still stands on its own.
            target = _baseline_item(entry)
            items.append(target)
            by_id[target["id"]] = target
        target["baseline"] = entry
        target["name"] = entry["name"]
        target["location_label"] = entry["location"].get("label")
        if entry["location"].get("approximate"):
            target["location_approximate"] = True
    return items


# ---------------------------------------------------------------------------
# casualty presentation
# ---------------------------------------------------------------------------

def _fmt_int(v) -> str:
    return f"{int(round(v)):,}"


def casualty_view(item: Dict[str, Any]) -> Dict[str, Any]:
    """best/low/high + every figure with its source. Ranking value rule:
    baseline best estimate -> NCEI figure -> lower bound of a documented range."""
    figures = []
    year = item.get("year")
    ncei = item.get("ncei_deaths")
    if ncei is not None:
        kinds = sorted({m["kind"] for m in item.get("members", [])})
        figures.append({"value": ncei, "label": "Total deaths recorded by NCEI (incl. secondary effects)",
                        "source": "; ".join(NCEI_CITATIONS[k] for k in kinds) or "NOAA NCEI",
                        "url": "https://www.ngdc.noaa.gov/hazel/"})
    b = item.get("baseline")
    best = low = high = None
    confidence = None
    notes = None
    if b and b.get("deaths"):
        best, low, high = b["deaths"].get("best"), b["deaths"].get("low"), b["deaths"].get("high")
        figures.extend(b.get("figures") or [])
        confidence = b.get("confidence")
        notes = b.get("notes")
    # A verified range is NOT widened with NCEI's figure: NCEI may count a
    # different measure (e.g. direct deaths only for Tambora). NCEI's value
    # is listed as its own, labelled figure instead.
    if confidence is None:
        confidence = "chronicle" if (year is not None and year < ERA_SINCE) else "single_source"
    rank_value = best if best is not None else (ncei if ncei is not None else low)
    qualifier = (b or {}).get("deaths", {}).get("qualifier") if b else None
    if qualifier == "more_than" and rank_value is not None:
        display = f"more than {_fmt_int(rank_value)}"
    elif low is not None and high is not None and low != high:
        display = f"{_fmt_int(low)}–{_fmt_int(high)}"
    elif rank_value is not None:
        display = _fmt_int(rank_value)
    else:
        display = "Unknown"
    best_note = None
    if qualifier == "more_than":
        best_note = None
    elif best is not None:
        best_note = f"Best estimate: {'at least ' if b and b.get('id') == 'tambora-1815' else ''}{_fmt_int(best)}"
    return {"best": best, "low": low, "high": high, "ncei": ncei, "rank_value": rank_value,
            "display": display, "best_note": best_note, "figures": figures, "confidence": confidence,
            "confidence_label": CONFIDENCE_LABELS.get(confidence, confidence), "notes": notes}


def _date_label(y, m=None, d=None) -> str:
    if y is None:
        return "Unknown date"
    y = int(y)
    ys = f"{-y} BC" if y < 0 else str(y)
    if m and d:
        return f"{int(d)} {datetime(2000, int(m), 1).strftime('%b')} {ys}"
    if m:
        return f"{datetime(2000, int(m), 1).strftime('%b')} {ys}"
    return ys


def present(item: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    cas = casualty_view(item)
    title = item.get("name") or f"{item['hazard_label']} — {item.get('place')}"
    age = _age_days(item.get("year"), item.get("month"), item.get("day"), now)
    return {
        "id": item["id"],
        "title": title,
        "hazard": item["hazard"],
        "hazard_label": item["hazard_label"],
        "date_label": _date_label(item.get("year"), item.get("month"), item.get("day")),
        "date_note": (item.get("baseline") or {}).get("date_note"),
        "year": item.get("year"), "month": item.get("month"), "day": item.get("day"),
        "lat": item.get("lat"), "lon": item.get("lon"),
        "location_label": item.get("location_label") or item.get("place"),
        "location_approximate": item.get("location_approximate", False),
        "magnitude": item.get("magnitude"), "vei": item.get("vei"),
        "tsunami_deaths": item.get("tsunami_deaths"),
        "metric_type": (item.get("baseline") or {}).get("metric_type"),
        "metric_label": METRIC_LABELS.get((item.get("baseline") or {}).get("metric_type")),
        "has_tsunami": item.get("has_tsunami", False),
        "deaths": cas,
        "preliminary": age is not None and age < PRELIMINARY_DAYS,
        "linked_records": item.get("members", []),
        "baseline_id": (item.get("baseline") or {}).get("id"),
        "verified_on": (item.get("baseline") or {}).get("verified_on"),
    }


# ---------------------------------------------------------------------------
# public: Deadliest
# ---------------------------------------------------------------------------

def _flag_range_overlaps(ranked: List[Dict[str, Any]]) -> None:
    def span(p):
        d = p["deaths"]
        lo = d["low"] if d["low"] is not None else d["rank_value"]
        hi = d["high"] if d["high"] is not None else d["rank_value"]
        return lo, hi
    for p in ranked:
        p.setdefault("rank_overlaps", False)
        p.setdefault("overlaps_with", [])
    for i, a in enumerate(ranked):
        lo_a, hi_a = span(a)
        for b in ranked[i + 1:]:
            lo_b, hi_b = span(b)
            if lo_a <= hi_b and lo_b <= hi_a:
                for x, y, ranged in ((a, b, lo_a < hi_a), (b, a, lo_b < hi_b)):
                    if ranged:
                        x["rank_overlaps"] = True
                        x["overlaps_with"].append(y["rank"])


def heatwaves(baseline: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Heatwaves: a SEPARATE list (never mixed into Deadliest). Mortality is
    an estimate (excess deaths or modelled heat-attributable deaths), each
    labelled with its method, study and uncertainty."""
    out = []
    for e in baseline["entries"]:
        if e["kind"] != "heatwave":
            continue
        item = {**_baseline_item(e), "baseline": e, "name": e["name"],
                "location_label": e["location"].get("label"), "location_approximate": True}
        p = present(item, now)
        d = p["deaths"]
        # Show the central estimate WITH its uncertainty, never the interval alone.
        if d["best"] is not None and d["low"] is not None and d["high"] is not None and d["low"] != d["high"]:
            kind = "95% CI" if e.get("metric_type") == "heat_attributable" else "estimates"
            d["display"] = f"{_fmt_int(d['best'])} ({kind} {_fmt_int(d['low'])}–{_fmt_int(d['high'])})"
        out.append(p)
    out.sort(key=lambda p: -(p["deaths"]["rank_value"] or 0))
    for i, p in enumerate(out):
        p["rank"] = i + 1
    _flag_range_overlaps(out)
    return {
        "items": out,
        "method": ("Heatwave deaths are not counted directly; they are estimated statistically. 'Excess deaths' "
                   "compares observed deaths with those expected; 'heat-attributable deaths' come from "
                   "epidemiological models. The two methods are not strictly comparable, and European figures "
                   "cover a whole summer that may include several heatwaves."),
        "coverage": ("Only events with a peer-reviewed or authoritative mortality estimate are listed. Many "
                     "deadly heatwaves, especially outside Europe, lack comparable studies and are not shown."),
    }


def deadliest(items: List[Dict[str, Any]], era: str = "since1900", limit: int = DEADLIEST_LIMIT,
              now: Optional[datetime] = None) -> Dict[str, Any]:
    ranked, pending = [], []
    for it in items:
        p = present(it, now)
        rv = p["deaths"]["rank_value"]
        if rv is None or rv < DEADLIEST_MIN_DEATHS or p["lat"] is None:
            continue
        if era == "since1900" and (p["year"] is None or p["year"] < ERA_SINCE):
            continue
        if p["preliminary"]:
            pending.append(p)            # never auto-promoted
            continue
        ranked.append(p)
    ranked.sort(key=lambda p: -p["deaths"]["rank_value"])
    ranked = ranked[:limit]
    for i, p in enumerate(ranked):
        p["rank"] = i + 1
        p["rank_overlaps"] = False
        p["overlaps_with"] = []
    # An event whose OWN documented range overlaps any other ranked event
    # (not just neighbours) has an uncertain rank. Single-figure events are
    # not flagged: their order relative to each other is as published, and
    # the ranged event carries the uncertainty (otherwise Haiti's wide range
    # would flag nearly every row).
    _flag_range_overlaps(ranked)
    # Possible duplicates: NCEI sometimes lists one historical disaster as two
    # records (e.g. Sicily, 9 and 11 Jan 1693). Flag — never merge — pairs of
    # the same hazard family within 100 km and 7 days.
    def _family(hz):
        return "earthquake" if hz.startswith("earthquake") else ("volcano" if hz.startswith("volcan") else hz)
    def _day(p):
        try:
            if p.get("year") is None or not p.get("month") or not p.get("day") or int(p["year"]) < 1:
                return None
            return datetime(int(p["year"]), int(p["month"]), int(p["day"]))
        except ValueError:
            return None
    for i, a in enumerate(ranked):
        for b in ranked[i + 1:]:
            if _family(a["hazard"]) != _family(b["hazard"]):
                continue
            da, db = _day(a), _day(b)
            if not da or not db or abs((da - db).days) > 7:
                continue
            if haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) <= 100:
                a.setdefault("possible_duplicate_of", []).append(b["rank"])
                b.setdefault("possible_duplicate_of", []).append(a["rank"])
    return {
        "era": era,
        "items": ranked,
        "pending_review": [{"id": p["id"], "title": p["title"], "date_label": p["date_label"]} for p in pending],
        "method": ("Ranked by the best estimate where a verified source states one; otherwise by NCEI's recorded "
                   "total; otherwise by the lower bound of the documented range (conservative). Where ranges "
                   "overlap, the ranks are not statistically distinguishable. Events less than a year old are "
                   "held for review and never ranked automatically."),
        "coverage": ("Earthquakes, tsunamis and volcanic eruptions come from NOAA NCEI's databases. Floods, "
                     "tropical cyclones and tornadoes come from a small verified baseline, so those hazards may "
                     "be incomplete. Heatwaves are shown separately (estimated deaths). Droughts/famines and "
                     "epidemics are not included."),
    }


# ---------------------------------------------------------------------------
# public: Record Holders
# ---------------------------------------------------------------------------

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _usgs_date(ms) -> str:
    # NOT datetime.fromtimestamp(): on Windows it raises OSError [Errno 22]
    # for negative (pre-1970) timestamps — e.g. the 1960 Valdivia earthquake.
    dt = _EPOCH + timedelta(milliseconds=ms)
    return f"{dt.day} {dt.strftime('%b %Y')}"      # no '%-d': unsupported on Windows


def _record(category, title, metric_label, holder, value_display, basis, authority,
            since1900=None, status="confirmed", candidates=None, shared=None):
    return {"category": category, "title": title, "metric_label": metric_label, "holder": holder,
            "value_display": value_display, "basis": basis, "authority": authority,
            "since1900": since1900, "status": status, "pending_candidates": candidates or [],
            "shared_with": shared or []}


def _top_by(items, hazards, key, now, since=None):
    pool = []
    for it in items:
        if it["hazard"] not in hazards:
            continue
        p = present(it, now)
        v = key(p)
        if v is None or p["lat"] is None:
            continue
        if since and (p["year"] is None or p["year"] < since):
            continue
        pool.append((v, p))
    pool.sort(key=lambda t: -t[0])
    confirmed = [(v, p) for v, p in pool if not p["preliminary"]]
    pending = [p for v, p in pool if p["preliminary"] and (not confirmed or v > confirmed[0][0])]
    return (confirmed[0][1] if confirmed else None), pending


def record_holders(items: List[Dict[str, Any]], usgs_largest: List[Dict[str, Any]],
                   baseline: Dict[str, Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Each category is computed independently; if one fails it is returned
    as 'unavailable' instead of failing the whole Record Holders view."""
    now = now or datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    for name, fn in (("strongest_earthquake", _rec_strongest_quake),
                     ("ncei_deadliest", _rec_ncei_deadliest),
                     ("largest_eruption", _rec_largest_eruption),
                     ("baseline", _rec_baseline)):
        try:
            out.extend(fn(items, usgs_largest, baseline, now))
        except Exception as e:
            logger.exception(f"Record category {name} failed: {e}")
            out.append(_record(name, _CATEGORY_FALLBACK_TITLES.get(name, name), "", None, None,
                               f"Unavailable right now ({type(e).__name__}).", "", status="unavailable"))
    return out


_CATEGORY_FALLBACK_TITLES = {"strongest_earthquake": "Strongest recorded earthquake",
                             "ncei_deadliest": "Deadliest earthquake / tsunami / eruption",
                             "largest_eruption": "Largest eruption (Common Era)",
                             "baseline": "WMO and baseline records"}


def _rec_strongest_quake(items, usgs_largest, baseline, now):
    out = []
    deaths_key = lambda p: p["deaths"]["rank_value"]

    # 1. Strongest earthquake — USGS, reviewed and settled only.
    best_q, pending_q = None, []
    for f in usgs_largest or []:
        pr = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if pr.get("mag") is None or len(coords) < 2:
            continue
        age = (now.timestamp() * 1000 - (pr.get("time") or 0)) / 8.64e7
        q = {"id": f"usgs-{f.get('id')}", "title": f"M{pr['mag']} — {pr.get('place') or 'unknown'}",
             "hazard": "earthquake", "hazard_label": "Earthquake",
             "date_label": _usgs_date((pr.get("time") or 0)),
             "lat": coords[1], "lon": coords[0], "location_label": pr.get("place"), "location_approximate": False,
             "magnitude": pr["mag"], "usgs_url": pr.get("url"), "usgs_status": pr.get("status")}
        # A recent magnitude must be USGS-reviewed and 30+ days old. Decades-old
        # catalogue events (1960 Valdivia, 1964 Alaska) are settled science
        # even when their catalogue status isn't 'reviewed'.
        settled = age >= PRELIMINARY_DAYS or (pr.get("status") == "reviewed" and age >= PRELIMINARY_PHYSICAL_DAYS)
        if settled:
            if best_q is None or pr["mag"] > best_q["magnitude"]:
                best_q = q
        else:
            pending_q.append(q)
    pending_q = [q for q in pending_q if best_q is None or q["magnitude"] > best_q["magnitude"]]
    out.append(_record("strongest_earthquake", "Strongest recorded earthquake", "Moment magnitude (Mw)",
                       best_q, f"M{best_q['magnitude']}" if best_q else None,
                       "Instrumental era (since 1900). Events from the last year qualify only once USGS has reviewed them (and 30+ days have passed).",
                       "USGS", candidates=pending_q))
    return out


def _rec_ncei_deadliest(items, usgs_largest, baseline, now):
    out = []
    deaths_key = lambda p: p["deaths"]["rank_value"]
    # 2-4. Deadliest earthquake / tsunami / eruption — NCEI (+ baseline ranges).
    tsunami_key = lambda p: p.get("tsunami_deaths")
    for cat, title, hazards, key, metric, auth in (
            ("deadliest_earthquake", "Deadliest earthquake", {"earthquake", "earthquake_tsunami"}, deaths_key,
             "Deaths incl. secondary effects (all recorded history)", "NOAA NCEI"),
            ("deadliest_tsunami", "Deadliest tsunami", {"tsunami", "earthquake", "earthquake_tsunami", "volcano", "volcano_tsunami"}, tsunami_key,
             "Deaths caused by the tsunami (all recorded history)", "NOAA NCEI tsunami database"),
            ("deadliest_eruption", "Deadliest volcanic eruption", {"volcano", "volcano_tsunami"}, deaths_key,
             "Deaths (all recorded history)", "NOAA NCEI")):
        holder, pending = _top_by(items, hazards, key, now)
        recent, _ = _top_by(items, hazards, key, now, since=ERA_SINCE)
        if cat == "deadliest_tsunami":
            value = f"{_fmt_int(holder['tsunami_deaths'])} (tsunami deaths)" if holder else None
        else:
            value = holder["deaths"]["display"] if holder else None
        out.append(_record(cat, title, metric, holder, value,
                           "Ranked as in Deadliest. Historical figures can be highly uncertain.", auth,
                           since1900=recent if recent and holder and recent["id"] != holder["id"] else None,
                           candidates=[{"id": p["id"], "title": p["title"], "date_label": p["date_label"]} for p in pending]))
    return out


def _rec_largest_eruption(items, usgs_largest, baseline, now):
    out = []
    # 5. Largest eruption by VEI — ties are shown as shared.
    vei_pool = [present(it, now) for it in items if it["hazard"] in ("volcano", "volcano_tsunami") and it.get("vei") is not None
                and it.get("year") is not None and int(it["year"]) >= 1 and it.get("lat") is not None]
    if vei_pool:
        top = max(p["vei"] for p in vei_pool)
        tied = sorted([p for p in vei_pool if p["vei"] == top], key=lambda p: -int(p["year"]))
        holder = next((p for p in tied if p.get("baseline_id") == "tambora-1815"), tied[0])
        out.append(_record("largest_eruption", "Largest eruption (Common Era)", "Volcanic Explosivity Index",
                           holder, f"VEI {int(top)}",
                           "VEI is a coarse logarithmic scale, so several eruptions can share the top value.",
                           "NOAA NCEI (VEI from Smithsonian GVP)",
                           shared=[{"id": p["id"], "title": p["title"], "date_label": p["date_label"]}
                                   for p in tied if p["id"] != holder["id"]]))
    else:
        out.append(_record("largest_eruption", "Largest eruption (Common Era)", "Volcanic Explosivity Index",
                           None, None, "Volcano data unavailable right now.", "NOAA NCEI"))
    return out


def _rec_baseline(items, usgs_largest, baseline, now):
    out = []
    # 6+. Baseline-only records (WMO etc.).
    items_by_baseline = {(it.get("baseline") or {}).get("id"): it for it in items if it.get("baseline")}
    entries = {e["id"]: e for e in baseline["entries"]}
    titles = {"deadliest_tropical_cyclone": "Deadliest tropical cyclone", "deadliest_tornado": "Deadliest tornado",
              "deadliest_flood": "Deadliest flood", "highest_tsunami_runup": "Highest tsunami run-up",
              "deadliest_heatwave": "Deadliest heatwave"}
    for rec in baseline["records"]:
        e = entries[rec["baseline_id"]]
        if e["kind"] == "heatwave":
            holder = present({**_baseline_item(e), "baseline": e, "name": e["name"],
                              "location_label": e["location"].get("label"), "location_approximate": True}, now)
            value = holder["deaths"]["display"]
            out.append(_record(rec["category"], titles[rec["category"]], rec["metric_label"], holder, value,
                               ("Statistical estimate, not a count. Later European summers (e.g. 2022: 61,672, "
                                "95% CI 37,643–86,807) overlap within uncertainty and use a different method."),
                               rec["authority"], status="estimated"))
            continue
        if e["kind"] == "record_only":
            holder = present({**_baseline_item(e), "baseline": e, "name": e["name"],
                              "location_label": e["location"].get("label")}, now)
            holder["figures"] = e.get("figures")
            value = f"{e['metric']['runup_m']} m"
        else:
            # Fall back to the baseline entry itself if the event isn't in the
            # assembled list, so one missing item can't blank every record.
            item = items_by_baseline.get(e["id"]) or {**_baseline_item(e), "baseline": e, "name": e["name"],
                                                      "location_label": e["location"].get("label")}
            holder = present(item, now)
            value = holder["deaths"]["display"]
        out.append(_record(rec["category"], titles[rec["category"]], rec["metric_label"], holder, value,
                           e.get("notes") or "", rec["authority"],
                           status="contested" if e.get("confidence") in ("low", "disputed") else "confirmed"))
    return out


# ---------------------------------------------------------------------------
# public entry points
# ---------------------------------------------------------------------------

def build(force: bool = False, now: Optional[datetime] = None):
    data, status = load_sources(force)
    baseline = load_baseline()
    disasters = build_ncei_disasters(data)
    ncei_ok = any(status[f"NCEI {k}"]["status"] != "unavailable" for k in NCEI_DATASETS)
    items = assemble_items(disasters, baseline, ncei_ok)
    return items, data, baseline, status


def deadliest_response(era: str = "since1900", now: Optional[datetime] = None) -> Dict[str, Any]:
    items, _, _, status = build(now=now)
    res = deadliest(items, era=era, now=now)
    res["sources"] = status
    return res


def heatwaves_response(now: Optional[datetime] = None) -> Dict[str, Any]:
    res = heatwaves(load_baseline(), now)
    res["sources"] = {"Verified baseline": {"status": "live", "message": "Peer-reviewed heat-mortality studies"}}
    return res


def records_response(now: Optional[datetime] = None) -> Dict[str, Any]:
    items, data, baseline, status = build(now=now)
    return {"records": record_holders(items, data.get("usgs_largest"), baseline, now), "sources": status}
