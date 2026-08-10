"""
One-Click Impact Report — aggregates everything else this backend already
knows about a location (current conditions, forecasts, fire risk, nearby
citizen reports) into one structured document, plus a short plain-language
summary.

Deliberately does NOT call an LLM to write the summary. Ask Gaia already
demonstrates the LLM-grounded-in-real-data pattern; this feature's whole
value proposition is a report you can generate reliably with one click,
so it shouldn't inherit an external network dependency (and possible
"data not available" flakiness) for something a template can do
deterministically from data this function already has in hand. If Ask
Gaia's reliability improves later, an LLM-polished prose version could be
layered on TOP of this template, not replace it.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services import climate, mock_data, forecast, wildfire_risk


def generate_impact_report(lat: float, lon: float, nearby_reports: Optional[List[Dict[str, Any]]] = None,
                            radius_km: float = 50.0) -> Dict[str, Any]:
    nearby_reports = nearby_reports or []
    now = datetime.now(timezone.utc)

    report: Dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "generated_at": now.isoformat(),
        "current_conditions": None,
        "weather_forecast": None,
        "air_quality_forecast": None,
        "wildfire_risk": None,
        "nearby_reports": nearby_reports,
        "summary": None,
    }

    # --- Current conditions: temperature + AQI/CO2, same sources the
    # Insight panel's stat cards already use ---
    current: Dict[str, Any] = {}
    try:
        climate_data = climate.get_location_climate(lat, lon)
        history = climate_data.get("historical_trends", [])
        latest = history[-1] if history else None
        current["temperature_c"] = latest.get("avg_temp_c") if latest else None
        current["temperature_anomaly_c"] = climate_data.get("current_anomaly")
    except Exception:
        current["temperature_c"] = None
        current["temperature_anomaly_c"] = None

    try:
        env_data = mock_data.generate_environment_data(lat, lon)
        current["aqi"] = env_data.get("air_quality_index")
        current["aqi_data_source"] = env_data.get("data_source")
        current["co2_ppm"] = env_data.get("co2_ppm")
    except Exception:
        current["aqi"] = None
        current["co2_ppm"] = None

    report["current_conditions"] = current

    # --- Forecasts + fire risk: reuse the exact same Phase 2 services
    # powering the dashboard's forecast cards, so the report can never
    # disagree with what's on screen ---
    report["weather_forecast"] = forecast.get_weather_forecast(lat, lon, days=7)
    report["air_quality_forecast"] = forecast.get_air_quality_forecast(lat, lon, days=5)
    report["wildfire_risk"] = wildfire_risk.get_wildfire_risk(lat, lon)

    report["summary"] = _build_summary(current, report["weather_forecast"],
                                        report["air_quality_forecast"],
                                        report["wildfire_risk"], nearby_reports)
    return report


def _build_summary(current: Dict[str, Any], weather_fc: Dict[str, Any], aqi_fc: Dict[str, Any],
                    fire_risk: Dict[str, Any], nearby_reports: List[Dict[str, Any]]) -> str:
    """Deterministic, template-based summary — every sentence traces back
    to a real field above, none of it is generated/guessed."""
    parts: List[str] = []

    aqi = current.get("aqi")
    if aqi is not None:
        band = _aqi_band(aqi)
        parts.append(f"Current air quality is {band} (AQI {aqi}).")
    else:
        parts.append("Current air quality data is unavailable for this location right now.")

    temp = current.get("temperature_c")
    if temp is not None:
        parts.append(f"Current temperature is {temp}°C.")

    risk = fire_risk.get("category")
    if risk and risk != "unavailable":
        parts.append(f"Wildfire danger is rated {risk} ({fire_risk.get('score')}/100).")

    aqi_days = aqi_fc.get("days") if aqi_fc else []
    peak_days = [d for d in aqi_days if d.get("aqi_max") is not None]
    if peak_days:
        worst = max(peak_days, key=lambda d: d["aqi_max"])
        if worst["aqi_max"] >= 150:
            parts.append(f"Air quality is forecast to worsen to AQI {worst['aqi_max']} on {worst['date']} — outdoor activity that day should be reconsidered.")

    weather_days = weather_fc.get("days") if weather_fc else []
    rain_days = [d for d in weather_days if (d.get("precipitation_mm") or 0) >= 10]
    if rain_days:
        dates = ", ".join(d["date"] for d in rain_days[:3])
        parts.append(f"Significant rainfall is expected on: {dates}.")

    if nearby_reports:
        confirmed = sum(1 for r in nearby_reports if r.get("satellite_confirmed"))
        parts.append(f"{len(nearby_reports)} citizen report(s) filed nearby recently ({confirmed} satellite-confirmed).")

    return " ".join(parts)


def _aqi_band(aqi: float) -> str:
    if aqi <= 50: return "Good"
    if aqi <= 100: return "Moderate"
    if aqi <= 150: return "Unhealthy for Sensitive Groups"
    if aqi <= 200: return "Unhealthy"
    if aqi <= 300: return "Very Unhealthy"
    return "Hazardous"
