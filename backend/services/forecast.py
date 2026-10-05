"""
Real, multi-day forecasts for a point — wraps Open-Meteo's own forecast
models rather than training a time-series model (LSTM/ARIMA/Prophet) from
scratch. That's a deliberate choice, not a shortcut: this backend has no
historical per-region time-series store yet (that's Phase 1 — PostGIS +
Celery ingestion, not built), and training a forecasting model with no
real training data would mean fabricating one. Open-Meteo's forecast
endpoints are real numerical weather prediction (NWP) output — genuinely
predictive, genuinely real, and keyless — so wrapping them honestly beats
faking a from-scratch model on data that doesn't exist.

If/when Phase 1's historical store exists, a real regional
LSTM/Prophet model trained on that data could COMPLEMENT this (e.g. for
longer-horizon or location-specific trend analysis) — but it should never
REPLACE real NWP output with something weaker just to satisfy the "we
have an ML model" checkbox.
"""

import logging
import requests
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_AQI_FORECAST_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

MAX_WEATHER_DAYS = 16  # Open-Meteo's own ceiling for the daily forecast
MAX_AQI_DAYS = 5        # Open-Meteo's air quality API forecast ceiling


def get_weather_forecast(lat: float, lon: float, days: int = 7) -> Dict[str, Any]:
    """
    Real daily weather forecast (temperature range, precipitation, max
    wind) from Open-Meteo's NWP models. Never fabricates a forecast if
    the API is unreachable — returns an honest 'unavailable' status.
    """
    days = max(1, min(days, MAX_WEATHER_DAYS))
    try:
        resp = requests.get(
            _FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,relative_humidity_2m_mean",
                "forecast_days": days,
                "timezone": "auto",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})
        dates = daily.get("time", [])

        days_out = []
        for i, date in enumerate(dates):
            days_out.append({
                "date": date,
                "temp_max_c": _at(daily, "temperature_2m_max", i),
                "temp_min_c": _at(daily, "temperature_2m_min", i),
                "precipitation_mm": _at(daily, "precipitation_sum", i),
                "wind_max_kmh": _at(daily, "wind_speed_10m_max", i),
                "humidity_mean_pct": _at(daily, "relative_humidity_2m_mean", i),
            })

        return {
            "lat": lat, "lon": lon,
            "days": days_out,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Open-Meteo NWP forecast",
            "status": "live",
        }
    except Exception as e:
        logger.warning(f"Weather forecast fetch failed for ({lat},{lon}): {e}")
        return {
            "lat": lat, "lon": lon,
            "days": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Open-Meteo NWP forecast",
            "status": "unavailable",
        }


def get_air_quality_forecast(lat: float, lon: float, days: int = 5) -> Dict[str, Any]:
    """
    Real hourly AQI/PM2.5 forecast from Open-Meteo's air quality model,
    aggregated to a daily max US AQI per day. Same honesty rule: no data
    on failure, not a fabricated number.
    """
    days = max(1, min(days, MAX_AQI_DAYS))
    try:
        resp = requests.get(
            _AQI_FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "us_aqi,pm2_5",
                "forecast_days": days,
                "timezone": "auto",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        aqi_vals = hourly.get("us_aqi", [])
        pm25_vals = hourly.get("pm2_5", [])

        # Bucket hourly readings into calendar days, keep each day's peak
        # AQI/PM2.5 — the peak, not the average, is what actually matters
        # for an alert-style forecast (a single bad afternoon is the
        # relevant signal, not a smoothed-out daily mean).
        by_day: Dict[str, Dict[str, float]] = {}
        for i, ts in enumerate(times):
            day = ts.split("T")[0]
            aqi = aqi_vals[i] if i < len(aqi_vals) else None
            pm25 = pm25_vals[i] if i < len(pm25_vals) else None
            bucket = by_day.setdefault(day, {"aqi_max": None, "pm25_max": None})
            if aqi is not None and (bucket["aqi_max"] is None or aqi > bucket["aqi_max"]):
                bucket["aqi_max"] = aqi
            if pm25 is not None and (bucket["pm25_max"] is None or pm25 > bucket["pm25_max"]):
                bucket["pm25_max"] = pm25

        days_out = [
            {"date": day, "aqi_max": v["aqi_max"], "pm25_max_ugm3": v["pm25_max"]}
            for day, v in sorted(by_day.items())
        ]

        return {
            "lat": lat, "lon": lon,
            "days": days_out,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Open-Meteo air quality forecast model",
            "status": "live",
        }
    except Exception as e:
        logger.warning(f"AQI forecast fetch failed for ({lat},{lon}): {e}")
        return {
            "lat": lat, "lon": lon,
            "days": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Open-Meteo air quality forecast model",
            "status": "unavailable",
        }


def get_rain_probability(lat: float, lon: float, days: int = 7) -> Dict[str, Any]:
    """
    Real probability of precipitation (PoP, %) from Open-Meteo's NWP
    models: the next 24 hours hourly, plus the daily maximum for each of
    the next `days` days.

    Provenance is FORECAST, never LIVE — PoP is a model prediction, not a
    measurement. Missing values stay None (the UI shows "not available")
    and are never coerced to 0%, because "0% chance of rain" and "the
    model gave no probability here" are very different statements.
    """
    days = max(1, min(days, MAX_WEATHER_DAYS))
    base = {
        "lat": lat, "lon": lon,
        "source": "Open-Meteo NWP forecast",
        "provenance": "FORECAST",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        resp = requests.get(
            _FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "precipitation_probability,precipitation",
                "daily": "precipitation_probability_max,precipitation_sum",
                "forecast_days": days,
                "timezone": "auto",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        hourly = data.get("hourly", {})
        daily = data.get("daily", {})
        h_times = hourly.get("time", [])

        # Open-Meteo returns hourly data from LOCAL midnight of today, so
        # the "next 24h" window has to start at the current LOCAL hour,
        # not at index 0 (which would mostly show hours already past).
        offset_s = data.get("utc_offset_seconds", 0) or 0
        local_now = datetime.now(timezone.utc) + timedelta(seconds=offset_s)
        current_hour = local_now.strftime("%Y-%m-%dT%H:00")
        start = 0
        for i, ts in enumerate(h_times):
            if ts >= current_hour:
                start = i
                break

        next_24h = []
        for i in range(start, min(start + 24, len(h_times))):
            next_24h.append({
                "time": h_times[i],
                "probability_pct": _at(hourly, "precipitation_probability", i),
                "precipitation_mm": _at(hourly, "precipitation", i),
            })

        daily_out = []
        for i, date in enumerate(daily.get("time", [])):
            daily_out.append({
                "date": date,
                "probability_max_pct": _at(daily, "precipitation_probability_max", i),
                "precipitation_sum_mm": _at(daily, "precipitation_sum", i),
            })

        hourly_vals = [h["probability_pct"] for h in next_24h if h["probability_pct"] is not None]
        has_any = bool(hourly_vals) or any(d["probability_max_pct"] is not None for d in daily_out)

        return {
            **base,
            "timezone": data.get("timezone"),
            "local_time": current_hour,
            "today_max_pct": daily_out[0]["probability_max_pct"] if daily_out else None,
            "next_24h_max_pct": max(hourly_vals) if hourly_vals else None,
            "next_24h": next_24h,
            "daily": daily_out,
            # "live" = request succeeded and the model returned PoP values.
            # "no_probability" = request succeeded, but this location/model
            # has no PoP field — an honest "not available", not 0%.
            "status": "live" if has_any else "no_probability",
        }
    except Exception as e:
        logger.warning(f"Rain probability fetch failed for ({lat},{lon}): {e}")
        return {**base, "today_max_pct": None, "next_24h_max_pct": None,
                "next_24h": [], "daily": [], "status": "unavailable"}


def _at(series: Dict[str, list], key: str, i: int):
    values = series.get(key, [])
    return values[i] if i < len(values) else None
