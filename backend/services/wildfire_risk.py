"""
Wildfire risk index — a transparent, rule-based fire danger score, NOT a
trained ML classifier.

The original brief asked for a Random Forest/XGBoost model trained on
temperature/humidity/NDVI. Training a real one honestly requires labeled
historical outcomes (did a fire actually occur, at this place, under
these conditions) — no such dataset exists in this backend, and this
sandbox has no access to build one. Presenting a made-up "trained model"
would fabricate both the training process and its accuracy, which
contradicts every other data-provenance decision already made in this
project (see: mock_data.py, climate.py, modis_ndvi.py — real data or a
clearly labeled estimate, never a fabricated confident number).

Instead: a documented, published-index-inspired formula (loosely modeled
on the structure of the Fosberg Fire Weather Index and the Canadian Fire
Weather Index — not a literal implementation of either, since both
require inputs, like multi-day drought codes, this backend doesn't have)
combining REAL temperature, humidity, wind (Open-Meteo current
conditions) and REAL vegetation dryness (NDVI, via modis_ndvi.py — real
MODIS where available, honestly-labeled biome estimate otherwise).

If/when real historical fire-outcome data becomes available, a genuine
trained classifier could replace this — that would be strictly better,
and this module's docstring should be updated to say so honestly at that
point, not before.
"""

import logging
import requests
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services import modis_ndvi

logger = logging.getLogger(__name__)

_CURRENT_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# Component weights — documented so the score is auditable, not a black
# box. Humidity weighted highest: it's the single strongest real-world
# driver of fire spread rate among these four inputs.
_WEIGHTS = {"temp": 0.20, "humidity": 0.35, "wind": 0.15, "dryness": 0.30}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def get_wildfire_risk(lat: float, lon: float) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    result: Dict[str, Any] = {
        "lat": lat, "lon": lon,
        "generated_at": now.isoformat(),
        "score": None,
        "category": None,
        "method": "rule_based_fire_danger_index",
        "inputs": {"temp_c": None, "humidity_pct": None, "wind_kmh": None, "ndvi": None},
        "data_source": {"weather": "unavailable", "vegetation": "unavailable"},
    }

    temp_c, humidity_pct, wind_kmh = _get_current_conditions(lat, lon)
    if temp_c is not None:
        result["data_source"]["weather"] = "live_open_meteo"
    result["inputs"]["temp_c"] = temp_c
    result["inputs"]["humidity_pct"] = humidity_pct
    result["inputs"]["wind_kmh"] = wind_kmh

    ndvi_info = None
    try:
        ndvi_info = modis_ndvi.get_ndvi_at_location(lat, lon)
        result["data_source"]["vegetation"] = ndvi_info.get("data_source", "unavailable")
        result["inputs"]["ndvi"] = ndvi_info.get("ndvi")
    except Exception as e:
        logger.warning(f"NDVI lookup failed for wildfire risk at ({lat},{lon}): {e}")

    # If either real input is entirely missing, don't fabricate a score —
    # same honesty rule as everywhere else in this backend.
    if temp_c is None or ndvi_info is None:
        result["category"] = "unavailable"
        return result

    temp_factor = _clamp01(temp_c / 45.0)  # 45C ~ extreme heat ceiling
    humidity_factor = _clamp01((100 - (humidity_pct if humidity_pct is not None else 50)) / 100.0)
    wind_factor = _clamp01((wind_kmh if wind_kmh is not None else 10) / 60.0)  # 60km/h ~ severe fire wind
    ndvi = result["inputs"]["ndvi"]
    dryness_factor = _clamp01(1.0 - _clamp01(ndvi if ndvi is not None else 0.4))

    score = 100 * (
        _WEIGHTS["temp"] * temp_factor
        + _WEIGHTS["humidity"] * humidity_factor
        + _WEIGHTS["wind"] * wind_factor
        + _WEIGHTS["dryness"] * dryness_factor
    )
    score = round(score, 1)

    if score < 25:
        category = "Low"
    elif score < 50:
        category = "Moderate"
    elif score < 75:
        category = "High"
    else:
        category = "Extreme"

    result["score"] = score
    result["category"] = category
    return result


def _get_current_conditions(lat: float, lon: float) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Real current temperature/humidity/wind from Open-Meteo. Returns
    (None, None, None) on failure — no fabricated fallback numbers."""
    try:
        resp = requests.get(
            _CURRENT_WEATHER_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
            },
            timeout=10,
        )
        resp.raise_for_status()
        current = resp.json().get("current", {})
        return (
            current.get("temperature_2m"),
            current.get("relative_humidity_2m"),
            current.get("wind_speed_10m"),
        )
    except Exception as e:
        logger.warning(f"Current-conditions fetch failed for ({lat},{lon}): {e}")
        return None, None, None
