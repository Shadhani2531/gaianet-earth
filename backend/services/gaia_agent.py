"""
Ask Gaia — the conversational assistant described in the product
walkthrough. Deliberately NOT a free-floating chatbot: it answers using
function-calling ("tools") against this backend's OWN real endpoints
(climate, forecast, wildfire risk, alert summary), the same way a human
analyst would look the numbers up rather than guess them. This keeps
Gaia's answers grounded in the same honestly-labeled data — real,
fallback, or unavailable — as every chart and card elsewhere in the app,
instead of an LLM confidently hallucinating a plausible-sounding AQI.

Uses the OpenAI Chat Completions "tools" format via plain HTTP (no SDK
dependency, consistent with the rest of this codebase using `requests`
directly). GAIA_LLM_BASE_URL is configurable specifically so this can
point at OpenAI itself, or any OpenAI-compatible endpoint (OpenRouter,
Gemini's OpenAI-compatibility layer, a self-hosted vLLM server, etc.)
without a code change — see backend/.env.example.

If GAIA_LLM_API_KEY isn't set, this returns an honest "not configured"
response rather than a broken/fake one — the same fallback discipline as
every other service in this backend.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import requests

from services import climate, forecast, wildfire_risk, alerts

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
MAX_TOOL_ITERATIONS = 5
MAX_HISTORY_MESSAGES = 10  # capped defensively — this endpoint has no
                            # persistent session store yet; the caller
                            # (frontend) resends recent turns each time


def _config() -> Dict[str, str]:
    return {
        "api_key": os.environ.get("GAIA_LLM_API_KEY", "").strip(),
        "model": os.environ.get("GAIA_LLM_MODEL", "openrouter/free").strip(),
        "base_url": os.environ.get("GAIA_LLM_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/"),
    }


def is_configured() -> bool:
    return bool(_config()["api_key"])


# --- Tools Gaia can call — thin wrappers around existing real services,
# no new upstream integrations introduced here ---

def _geocode_location(place_name: str) -> Dict[str, Any]:
    """Real geocoding via Open-Meteo's own geocoding API — same provider
    already used for weather/AQI forecasts elsewhere in this backend, so
    no new upstream dependency is introduced just for chat."""
    try:
        resp = requests.get(_GEOCODE_URL, params={"name": place_name, "count": 1}, timeout=8)
        resp.raise_for_status()
        results = resp.json().get("results")
        if not results:
            return {"error": f"Could not find a location matching '{place_name}'."}
        r = results[0]
        name_parts = [r.get("name"), r.get("admin1"), r.get("country")]
        return {
            "lat": r["latitude"],
            "lon": r["longitude"],
            "display_name": ", ".join(p for p in name_parts if p),
        }
    except Exception as e:
        logger.warning(f"Gaia geocode failed for '{place_name}': {e}")
        return {"error": "Geocoding service unavailable right now."}


def _get_current_snapshot(lat: float, lon: float, radius_km: float = 50.0) -> Dict[str, Any]:
    """'What's happening right now' at a point — reuses
    alerts.get_alert_summary() (already built for the browser extension)
    rather than duplicating its FIRMS/OpenAQ radius-filtering logic."""
    result: Dict[str, Any] = {}
    try:
        climate_data = climate.get_location_climate(lat, lon)
        history = climate_data.get("historical_trends", [])
        latest = history[-1] if history else None
        result["temperature_c"] = latest.get("avg_temp_c") if latest else None
        result["temperature_anomaly_c"] = climate_data.get("current_anomaly")
    except Exception as e:
        logger.warning(f"Gaia snapshot: climate lookup failed: {e}")

    try:
        summary = alerts.get_alert_summary(lat, lon, radius_km)
        result["aqi"] = summary.get("aqi_max")
        result["aqi_data_source"] = summary.get("data_source", {}).get("air_quality")
        result["fire_count_nearby"] = summary.get("fire_count")
        result["fire_cluster_detected"] = summary.get("fire_cluster_detected")
    except Exception as e:
        logger.warning(f"Gaia snapshot: alert summary failed: {e}")

    return result


_TOOL_DISPATCH = {
    "geocode_location": lambda a: _geocode_location(a["place_name"]),
    "get_current_snapshot": lambda a: _get_current_snapshot(a["lat"], a["lon"], a.get("radius_km", 50.0)),
    "get_weather_forecast": lambda a: forecast.get_weather_forecast(a["lat"], a["lon"], a.get("days", 7)),
    "get_air_quality_forecast": lambda a: forecast.get_air_quality_forecast(a["lat"], a["lon"], a.get("days", 5)),
    "get_wildfire_risk": lambda a: wildfire_risk.get_wildfire_risk(a["lat"], a["lon"]),
}

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "geocode_location",
            "description": "Convert a place name (city, region, landmark) into latitude/longitude. Call this first whenever the user names a place rather than giving coordinates or referring to 'here'/'this location'.",
            "parameters": {
                "type": "object",
                "properties": {"place_name": {"type": "string", "description": "e.g. 'Nagpur', 'Nagpur, India'"}},
                "required": ["place_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_snapshot",
            "description": "Real current conditions at a point: temperature, temperature anomaly, current AQI, and nearby active fire count. Use this for 'right now' / 'currently' / 'is it safe outside today' questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "radius_km": {"type": "number", "description": "Search radius for AQI stations and fires, default 50km"},
                },
                "required": ["lat", "lon"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": "Real multi-day weather forecast (temperature, precipitation, wind) from Open-Meteo's NWP model. Use for questions about future days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "days": {"type": "integer", "description": "1-16, default 7"},
                },
                "required": ["lat", "lon"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_air_quality_forecast",
            "description": "Real multi-day AQI/PM2.5 forecast. Use for 'will the air quality be bad tomorrow/this weekend' type questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "days": {"type": "integer", "description": "1-5, default 5"},
                },
                "required": ["lat", "lon"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wildfire_risk",
            "description": "A transparent, formula-based fire danger score (0-100, Low/Moderate/High/Extreme) from real temperature, humidity, wind, and vegetation dryness (NDVI). This is NOT a trained ML model — say so if the user asks how it's calculated.",
            "parameters": {
                "type": "object",
                "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                "required": ["lat", "lon"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are Gaia, the conversational assistant built into GaiaNet Earth, a planetary environmental intelligence dashboard.

Rules you must follow:
1. Never guess or estimate a number (temperature, AQI, fire risk, forecast) yourself. Always call the relevant tool to get the real value before answering a question that needs one.
2. If the user names a place, call geocode_location first to get coordinates, unless coordinates were already given to you as the user's currently-selected map location.
3. If a tool returns an error or an "unavailable"/null value, say so honestly in plain language ("I couldn't get live air quality data for that spot right now") — never substitute a plausible-sounding made-up number.
4. get_wildfire_risk is a documented rule-based formula, not a trained ML model — if asked how it works, say that plainly.
5. Keep answers short, plain-language, and directly useful for a real decision (e.g. "should I go outside", "should I reschedule an outdoor event"). Avoid dumping raw JSON at the user.
6. You are not a replacement for official emergency alerts or medical advice — for anything safety-critical, note that the person should also check official local sources.
"""


def chat(message: str, history: Optional[List[Dict[str, str]]] = None,
         context: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    One turn of conversation with Gaia. `history` is a list of prior
    {role, content} messages the frontend resends each time (no
    server-side session store yet — this endpoint is stateless by
    design, matching the rest of this backend's no-persistent-session
    pattern outside the SQLite reports table).
    """
    config = _config()
    if not config["api_key"]:
        return {
            "reply": "Ask Gaia isn't configured yet — set GAIA_LLM_API_KEY in backend/.env to enable it.",
            "status": "not_configured",
            "location": None,
            "tool_calls_made": [],
        }

    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context and context.get("lat") is not None and context.get("lon") is not None:
        messages.append({
            "role": "system",
            "content": f"The user currently has this location selected on the dashboard's map: lat={context['lat']}, lon={context['lon']}. Use these coordinates for questions about 'here'/'this location' without a named place.",
        })
    if history:
        messages.extend(history[-MAX_HISTORY_MESSAGES:])
    messages.append({"role": "user", "content": message})

    last_location: Optional[Dict[str, Any]] = None
    tool_calls_made: List[Dict[str, Any]] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            resp = requests.post(
                f"{config['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config["model"],
                    "messages": messages,
                    "tools": _TOOLS,
                    "tool_choice": "auto",
                },
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Gaia LLM call failed: {e}")
            return {
                "reply": "I couldn't reach the language model right now — try again shortly.",
                "status": "llm_unavailable",
                "location": last_location,
                "tool_calls_made": tool_calls_made,
            }

        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return {
                "reply": (msg.get("content") or "").strip() or "I'm not sure how to answer that.",
                "status": "ok",
                "location": last_location,
                "tool_calls_made": tool_calls_made,
            }

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                fn_args = {}

            handler = _TOOL_DISPATCH.get(fn_name)
            if handler is None:
                tool_result: Dict[str, Any] = {"error": f"Unknown tool '{fn_name}'"}
            else:
                try:
                    tool_result = handler(fn_args)
                except Exception as e:
                    logger.warning(f"Gaia tool '{fn_name}' failed: {e}")
                    tool_result = {"error": str(e)}

            tool_calls_made.append({"name": fn_name, "args": fn_args})

            if "lat" in fn_args and "lon" in fn_args:
                last_location = {"lat": fn_args["lat"], "lon": fn_args["lon"]}
            elif isinstance(tool_result, dict) and "lat" in tool_result and "lon" in tool_result:
                last_location = {
                    "lat": tool_result["lat"],
                    "lon": tool_result["lon"],
                    "name": tool_result.get("display_name"),
                }

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(tool_result),
            })

    return {
        "reply": "I gathered some data but couldn't finish forming an answer — try rephrasing your question.",
        "status": "max_iterations_reached",
        "location": last_location,
        "tool_calls_made": tool_calls_made,
    }
