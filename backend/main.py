import os
import sys
import requests
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Ensure the backend directory is in the path for relative service imports
curr_dir = os.path.dirname(os.path.abspath(__file__))
if curr_dir not in sys.path:
    sys.path.append(curr_dir)

# Load backend/.env (WAQI_TOKEN, etc.) before any service module reads
# environment variables at import time.
load_dotenv(os.path.join(curr_dir, ".env"))

from services import nasa_firms, modis_ndvi, climate, mock_data, weather, scenario_engine, openaq_client, country_coords, alerts, forecast, wildfire_risk, gaia_agent, impact_report, worldbank_client, who_gho_client, shi_composite

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="GaiaNet Earth API", description="Production-grade Environmental Intelligence Gateway")

# Configure CORS. Wide open (["*"]) was fine for early local-only
# development, but was never actually needed — this app serves its own
# frontend same-origin (see the StaticFiles mount at the bottom of this
# file). Now configurable via CORS_ALLOWED_ORIGINS (comma-separated) in
# backend/.env, defaulting to common local-dev origins so nothing breaks
# out of the box. Set CORS_ALLOWED_ORIGINS=* explicitly if you ever need
# the old wide-open behavior back (e.g. testing from an external client).
_cors_origins_env = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
if _cors_origins_env:
    _allowed_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
else:
    _allowed_origins = [
        "http://localhost:8000", "http://127.0.0.1:8000",
        "http://localhost:5500", "http://127.0.0.1:5500",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/status")
def read_root():
    return {
        "status": "online", 
        "version": "2.1.0",
        "message": "GaiaNet Earth Environmental Intelligence API is running with real-world data feeds."
    }

@app.get("/api/config")
def get_runtime_config():
    """
    The one piece of config the frontend needs but must NOT ship hardcoded
    in a static JS file: the Cesium Ion token. Previously this was a real
    credential committed directly in js/config.js — anyone browsing the
    public repo could lift it. Now it lives in backend/.env
    (CESIUM_ION_TOKEN, gitignored) and is served here instead.

    This does not make the token secret from the browser's own network
    tab — Cesium Ion tokens are inherently a client-side credential, used
    directly by the browser to fetch tiles. What this DOES fix is keeping
    it out of git history and source control, and letting it be rotated
    by editing one gitignored file instead of a commit. For real
    protection against abuse, also restrict the token to specific
    referrer domains in the Ion dashboard (https://ion.cesium.com/tokens).

    Returns null (not an error) if unconfigured — the frontend already
    handles that by falling back to Cesium's own default imagery.
    """
    return {"cesium_ion_token": os.environ.get("CESIUM_ION_TOKEN", "").strip() or None}

@app.get("/stations")
def get_stations():
    """Fetch global air quality stations from real OpenAQ v3 data.
    (v1/v2 were retired Jan 2025 and return HTTP 410 — this endpoint was
    silently broken until migrated to v3, which requires OPENAQ_API_KEY.)
    NOTE: metadata only — does NOT include each station's live reading.
    See /stations-with-readings for that."""
    return openaq_client.get_stations(limit=1000)

@app.get("/stations-with-readings")
def get_stations_with_readings():
    """Real stations WITH each one's actual latest PM2.5 reading resolved
    server-side. Use this (not /stations) for anything that needs to color
    or filter by real air quality — OpenAQ v3's plain /locations list does
    not include live readings inline, which is exactly the bug this
    endpoint fixes for the Air Quality layer toggle."""
    return openaq_client.get_stations_with_readings()

@app.get("/country-boundaries")
def country_boundaries():
    """Real country boundary polygons (Natural Earth, public domain) for
    rendering the Tab 6 SHI heatmap. Cached server-side for a week."""
    return openaq_client.get_country_boundaries_geojson()

import time as _time

# Composite SHI cache — this endpoint does real per-country climate + NDVI
# lookups (on top of the OpenAQ aggregate), which is meaningfully slower
# than AQI alone. Cached for 6 hours since none of these components change
# minute-to-minute at the country level.
_composite_shi_cache = {"data": None, "computed_at": 0}
_COMPOSITE_SHI_CACHE_SECONDS = 6 * 3600


@app.get("/shi-global")
def shi_global():
    """
    Tab 6 — Global SHI Heatmap. Real, live composite Sustainability Health
    Index per country, combining four real data sources with EPI-style
    (Yale/Columbia Environmental Performance Index) methodology — see
    services/shi_composite.py for the full scoring approach:
      - Air quality (40%): OpenAQ v3 real station PM2.5
      - Climate/Emissions (25%): World Bank real CO2 emissions per capita
      - Health Outcomes (20%): WHO GHO real life expectancy at birth
      - Vegetation (15%): NASA MODIS real NDVI at a capital-city reference point

    No hardcoded or fabricated per-country numbers anywhere in this
    endpoint. A country missing one or more components has that
    component's weight redistributed across the ones it does have,
    rather than either guessing a value or comparing it unfairly against
    countries scored on a different number of components.

    Requires OPENAQ_API_KEY in backend/.env (see .env.example). The
    World Bank and WHO GHO sources need no key at all.
    """
    if not os.environ.get("OPENAQ_API_KEY", "").strip():
        return {
            "countries": [],
            "status": "missing_api_key",
            "message": "OPENAQ_API_KEY not set in backend/.env — get a free key at https://explore.openaq.org"
        }

    now = _time.time()
    if (_composite_shi_cache["data"] is not None
            and (now - _composite_shi_cache["computed_at"]) < _COMPOSITE_SHI_CACHE_SECONDS):
        return _composite_shi_cache["data"]

    response = shi_composite.compute_global_shi()

    if response.get("status") == "ok":
        _composite_shi_cache["data"] = response
        _composite_shi_cache["computed_at"] = now

    return response

@app.get("/shi")
def get_shi(lat: float = Query(...), lon: float = Query(...)):
    """Calculate point-specific Sustainability Health Index (SHI) using live data."""
    live_env = mock_data.generate_environment_data(lat, lon)
    aqi = live_env["air_quality_index"]
    
    # SHI Calculation Logic (Matching friend's implementation)
    shi = max(0, min(100, 100 - (aqi/3)))
    grade = 'A' if shi >= 80 else ('B' if shi >= 60 else ('C' if shi >= 40 else 'D'))
    risk = 'Healthy' if shi >= 80 else ('Moderate' if shi >= 50 else 'Poor')
    
    return {
        "shi": int(shi),
        "grade": grade,
        "risk": risk,
        "aqi": aqi
    }

@app.get("/wildfires")
def get_wildfires():
    """Returns top 500 active wildfires from NASA FIRMS as GeoJSON."""
    return nasa_firms.get_wildfires_geojson()

@app.get("/vegetation")
def get_vegetation():
    """Returns biome-modelled global NDVI distribution as GeoJSON for overview."""
    return modis_ndvi.get_vegetation_geojson()

@app.get("/ndvi-value")
def get_ndvi_value(lat: float = Query(...), lon: float = Query(...), date: str = Query(None)):
    """Near real-time NDVI analysis for specific coordinates."""
    return modis_ndvi.get_ndvi_at_location(lat, lon, date)

@app.get("/climate")
def get_climate(lat: float = Query(None), lon: float = Query(None)):
    """
    Returns:
    - Global climate anomaly grid (GeoJSON) if no coordinates provided.
    - Location-specific historical trends (JSON) if lat/lon provided.
    """
    if lat is not None and lon is not None:
        return climate.get_location_climate(lat, lon)
    return climate.get_climate_geojson()

@app.get("/rainfall")
def get_rainfall():
    """Global real-time precipitation grid (GeoJSON) — real current
    readings from Open-Meteo, same underlying fetch as /climate's
    temperature grid."""
    return climate.get_rainfall_geojson()

@app.get("/weather-conditions")
def get_weather_conditions():
    """Global real-time cloud cover grid (GeoJSON) — real current readings
    from Open-Meteo, same underlying fetch as /climate and /rainfall."""
    return climate.get_weather_conditions_geojson()

@app.get("/wind")
def get_wind():
    """Global real-time wind speed + direction grid (GeoJSON) — same
    underlying Open-Meteo fetch as /climate, /rainfall, and
    /weather-conditions (wind fields were added to that shared request
    rather than issuing a separate upstream call). Powers the wind
    arrow-glyph layer on the globe."""
    return climate.get_wind_geojson()

@app.get("/environment")
def get_environment(lat: float = Query(...), lon: float = Query(...)):
    """Aggregate environmental intelligence for a specific point using real-world WAQI data."""
    climate_info = climate.get_location_climate(lat, lon)
    live_env = mock_data.generate_environment_data(lat, lon)
    
    return {
        "location": {"lat": lat, "lon": lon},
        "temperature_c": live_env["temperature_c"], # Real data from WAQI
        "air_quality_index": live_env["air_quality_index"], # Real data from WAQI
        "co2_ppm": live_env["co2_ppm"],
        "rainfall_mm": climate_info["historical_trends"][-1]["total_rainfall_mm"],
        "anomaly_c": climate_info["current_anomaly"],
        "status": "success"
    }

def _compute_shi(aqi: float) -> dict:
    """Shared SHI formula (matches the existing /shi endpoint's logic)."""
    shi = max(0, min(100, 100 - (aqi / 3)))
    grade = 'A' if shi >= 80 else ('B' if shi >= 60 else ('C' if shi >= 40 else 'D'))
    risk = 'Healthy' if shi >= 80 else ('Moderate' if shi >= 50 else 'Poor')
    return {"shi": int(shi), "grade": grade, "risk": risk}


def _aqi_from_pm25(pm25: float) -> int:
    """Convert a PM2.5 value to AQI using the same real EPA breakpoints
    scenario_engine.py uses, so before/after values stay consistent."""
    return scenario_engine._pm25_to_aqi(pm25)


@app.get("/prediction")
def get_prediction(
    lat: float = Query(...),
    lon: float = Query(...),
    forest_loss_pct: float = Query(0.0, ge=0, le=100, description="What-if: additional forest cover lost, 0-100%"),
    emissions_increase_pct: float = Query(0.0, ge=0, le=200, description="What-if: emissions increase, 0-200%"),
    is_tropical: bool = Query(True, description="Whether the clicked location is in a tropical biome"),
    scenario: str = Query(None, description="Deprecated/legacy param, ignored — kept for backward compatibility"),
):
    """
    GaiaNet Digital Twin — What-If Scenario Simulator (Tab 4).

    Applies real, cited climate-science coefficients (see
    services/scenario_engine.py) to this location's REAL current live data
    (Open-Meteo climate + WAQI air quality) to project the effect of a
    deforestation and/or emissions scenario. This is NOT a black-box ML
    prediction — every number returned carries a `confidence` level
    ("measured" / "estimated" / "modeled") and a citation in `basis`,
    because the underlying science does not support false precision.
    """
    # 1. Pull REAL current data for this location.
    climate_info = climate.get_location_climate(lat, lon)
    live_env = mock_data.generate_environment_data(lat, lon)

    current_temp_c = live_env["temperature_c"]
    current_aqi = live_env["air_quality_index"]
    current_pm25 = live_env["pm25"]
    current_co2_ppm = live_env["co2_ppm"]

    shi_before = _compute_shi(current_aqi)

    current_data = {
        "temperature_c": current_temp_c,
        "co2_ppm": current_co2_ppm,
        "pm25": current_pm25,
        "aqi": current_aqi,
        "shi": shi_before["shi"],
    }

    # 2. Run the real scenario engine.
    result = scenario_engine.run_scenario(
        location={"lat": lat, "lon": lon},
        current_data=current_data,
        forest_loss_pct=forest_loss_pct,
        emissions_increase_pct=emissions_increase_pct,
        is_tropical=is_tropical,
    )

    # 3. Compute SHI-after using the projected AQI (if an emissions scenario
    #    was run) or the current AQI unchanged (if only deforestation was run
    #    — deforestation's air-quality effect isn't modeled here, only its
    #    temperature/CO2 effects, so AQI-derived SHI wouldn't honestly move).
    aqi_change = next((c for c in result.changes if c.metric == "aqi"), None)
    projected_aqi = aqi_change.projected_value if aqi_change else current_aqi
    shi_after = _compute_shi(projected_aqi)

    return {
        "location": result.location,
        "scenario": result.scenario,
        "current_data": current_data,
        "current_data_source": live_env.get("data_source", "unknown"),
        "shi_before": shi_before,
        "shi_after": shi_after,
        "changes": [
            {
                "metric": c.metric,
                "current_value": c.current_value,
                "projected_value": c.projected_value,
                "delta": c.delta,
                "unit": c.unit,
                "confidence": c.confidence,
                "basis": c.basis,
            }
            for c in result.changes
        ],
        "narrative": result.narrative,
    }

# --- CITIZEN SCIENCE REPORTING ---
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy.orm import Session
from fastapi import Depends
from database import get_db, Report as DBReport

class ReportCreate(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    incident_type: Literal["Fire", "Pollution", "Deforestation", "Water", "Flooding", "Other"]
    severity: int = Field(..., ge=1, le=5)
    description: str = Field(..., min_length=1, max_length=2000)
    reporter_name: str = Field("Anonymous", max_length=200)
    reporter_email: str | None = Field(None, max_length=320)


class GaiaChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class GaiaChatRequest(BaseModel):
    message: str
    history: list[GaiaChatMessage] = []
    context: dict | None = None  # {"lat": ..., "lon": ...} — currently selected map location, if any

@app.post("/api/reports")
def create_report(report: ReportCreate, db: Session = Depends(get_db)):
    """Saves a user-submitted environmental incident report, cross-checked
    against real NASA FIRMS wildfire detections when relevant."""
    confirmation = nasa_firms.check_satellite_confirmation(
        report.lat, report.lon, report.incident_type
    )

    db_report = DBReport(
        lat=report.lat,
        lon=report.lon,
        incident_type=report.incident_type,
        severity=report.severity,
        description=report.description,
        reporter_name=report.reporter_name or "Anonymous",
        reporter_email=report.reporter_email,
        satellite_confirmed=1 if confirmation.get("confirmed") else 0
    )
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    return db_report

@app.get("/api/weather")
async def get_weather(lat: float, lon: float):
    return await weather.weather_service.get_weather(lat, lon)

@app.get("/api/reports")
def get_reports(db: Session = Depends(get_db)):
    """Returns all citizen science reports."""
    return db.query(DBReport).all()

# --- Planetary Health OS browser extension ---
@app.get("/alerts/summary")
def get_alerts_summary(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(50.0, gt=0, le=500),
):
    """
    Small-payload alert summary for the browser extension's MV3 service
    worker (see extension/background.js). Deliberately returns only a
    handful of numbers — reuses the existing cached FIRMS/OpenAQ clients
    rather than adding new upstream calls, so this endpoint's cost is
    just distance filtering over data the main map endpoints already
    fetch and cache.
    """
    return alerts.get_alert_summary(lat, lon, radius_km)


# --- Predictive AI (Phase 2) ---
@app.get("/forecast/weather")
def get_weather_forecast(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    days: int = Query(7, ge=1, le=16),
):
    """Real multi-day weather forecast (Open-Meteo NWP model output —
    see backend/services/forecast.py for why this isn't a from-scratch
    trained time-series model)."""
    return forecast.get_weather_forecast(lat, lon, days)


@app.get("/forecast/air-quality")
def get_air_quality_forecast(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    days: int = Query(5, ge=1, le=5),
):
    """Real multi-day AQI/PM2.5 forecast (Open-Meteo air quality model)."""
    return forecast.get_air_quality_forecast(lat, lon, days)


@app.get("/wildfire-risk")
def get_wildfire_risk(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """Transparent, rule-based fire danger index from real temp/humidity/
    wind/NDVI — see backend/services/wildfire_risk.py's module docstring
    for why this is formula-based rather than a trained ML classifier."""
    return wildfire_risk.get_wildfire_risk(lat, lon)


# --- Ask Gaia (Phase 3): grounded chat assistant ---
@app.post("/gaia/chat")
def gaia_chat(request: GaiaChatRequest):
    """See backend/services/gaia_agent.py — answers via function-calling
    against this backend's own real endpoints, never a guessed number.
    Stateless: the frontend resends recent conversation history each turn."""
    history = [{"role": m.role, "content": m.content} for m in request.history]
    return gaia_agent.chat(request.message, history=history, context=request.context)


@app.get("/reports/impact")
def get_impact_report(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(50.0, gt=0, le=500),
    db: Session = Depends(get_db),
):
    """One-click Impact Report — see backend/services/impact_report.py.
    Nearby citizen reports are queried here (not in the service module)
    since that's the one part of this feature that needs DB access,
    matching where all other DB queries already live in this file."""
    all_reports = db.query(DBReport).all()
    nearby = [
        {
            "id": r.id, "incident_type": r.incident_type, "severity": r.severity,
            "description": r.description, "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "satellite_confirmed": bool(r.satellite_confirmed),
        }
        for r in all_reports
        if alerts._haversine_km(lat, lon, r.lat, r.lon) <= radius_km
    ]
    return impact_report.generate_impact_report(lat, lon, nearby_reports=nearby, radius_km=radius_km)

# Mount frontend static files
# BASE_DIR is the root project folder
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)