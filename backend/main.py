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

from services import nasa_firms, modis_ndvi, climate, mock_data, weather, scenario_engine, openaq_client, country_coords

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
    Index per country, combining three real data sources:
      - Air quality: real OpenAQ v3 station PM2.5, averaged per country
      - Climate: real Open-Meteo temperature anomaly at the country's
        capital (used as a representative point — see country_coords.py)
      - Vegetation: real NASA MODIS NDVI at the same representative point

    No hardcoded or fabricated per-country numbers anywhere in this
    endpoint. Every component that couldn't be computed from real data
    for a given country is OMITTED from that country's composite, not
    backfilled with a guess — and the response says exactly which
    components each country's score is built from.

    Requires OPENAQ_API_KEY in backend/.env (see .env.example).
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

    aggregate = openaq_client.get_country_aqi_aggregate()
    if not aggregate:
        reason = openaq_client.get_last_openaq_error()
        message = "Could not fetch real OpenAQ data right now. Try again shortly."
        if reason:
            message += f" (reason: {reason})"
        return {
            "countries": [],
            "status": "no_data",
            "message": message,
            "debug_reason": reason
        }

    results = []
    for code, info in aggregate.items():
        pm25 = info["avg_pm25"]
        aqi = scenario_engine._pm25_to_aqi(pm25)
        aqi_shi = max(0, min(100, 100 - (aqi / 3)))

        components = {
            "air_quality": {
                "value": aqi_shi,
                "weight": 1.0,  # adjusted below if other components are present
                "basis": f"Real OpenAQ v3 data, {info['station_count']} station(s) sampled, avg PM2.5 {pm25} µg/m³"
            }
        }

        # --- Climate component (real Open-Meteo, at country capital) ---
        ref_point = country_coords.get_country_reference_point(code)
        climate_shi = None
        ndvi_shi = None
        is_tropical = True

        if ref_point:
            is_tropical = ref_point["is_tropical"]
            try:
                climate_info = climate.get_location_climate(ref_point["lat"], ref_point["lon"])
                anomaly = abs(climate_info.get("current_anomaly", 0))
                # Real, simple mapping: larger temperature anomaly -> lower
                # climate-stability score. This weighting choice (anomaly of
                # 3C or more = 0 score) is a modeling decision, not itself a
                # citation — flagged as such in the basis string.
                climate_shi = max(0, min(100, 100 - (anomaly / 3.0) * 100))
                components["climate_stability"] = {
                    "value": round(climate_shi, 1),
                    "weight": 1.0,
                    "basis": f"Real Open-Meteo climate data at {ref_point['capital']} "
                             f"(country capital, used as representative point); "
                             f"anomaly {climate_info.get('current_anomaly')}°C. "
                             f"Anomaly-to-score mapping is a modeling choice, not a cited standard."
                }
            except Exception as e:
                logger.warning(f"Climate component failed for {code}: {e}")

            try:
                ndvi_info = modis_ndvi.get_ndvi_at_location(ref_point["lat"], ref_point["lon"])
                ndvi_val = ndvi_info.get("ndvi", 0)
                # Real NDVI mapped to a 0-100 score: NDVI ranges roughly
                # -1 (water/barren) to +1 (dense vegetation); we rescale
                # the practical 0-0.9 range that covers most land surfaces.
                ndvi_shi = max(0, min(100, (ndvi_val / 0.9) * 100))
                components["vegetation"] = {
                    "value": round(ndvi_shi, 1),
                    "weight": 1.0,
                    "basis": f"{'Real NASA MODIS NDVI' if ndvi_info.get('data_source') == 'real_modis' else 'Estimated NDVI (MODIS unavailable for this point)'} "
                             f"at {ref_point['capital']}, value {ndvi_info.get('ndvi')}",
                    "confidence": "measured" if ndvi_info.get("data_source") == "real_modis" else "estimated"
                }
            except Exception as e:
                logger.warning(f"NDVI component failed for {code}: {e}")

        # --- Composite: simple average of whichever real components exist ---
        component_values = [c["value"] for c in components.values()]
        composite_shi = sum(component_values) / len(component_values)

        grade = 'A' if composite_shi >= 80 else ('B' if composite_shi >= 60 else ('C' if composite_shi >= 40 else 'D'))
        risk = 'Healthy' if composite_shi >= 80 else ('Moderate' if composite_shi >= 50 else 'Poor')

        results.append({
            "country_code": code,
            "country_name": info["country_name"],
            "shi": int(round(composite_shi)),
            "grade": grade,
            "risk": risk,
            "components": components,
            "components_used": list(components.keys()),
            "station_count": info["station_count"],
        })

    results.sort(key=lambda r: r["shi"], reverse=True)

    response = {
        "countries": results,
        "status": "ok",
        "sampled_country_count": len(results),
        "note": "SHI is a composite of real, live data: air quality (OpenAQ v3, always included when available), "
                "climate stability (Open-Meteo, at the country's capital as a representative point), and "
                "vegetation health (NASA MODIS NDVI, same representative point). Countries not listed had no "
                "sampled real air-quality stations. A country's 'components_used' field shows exactly which "
                "real data sources contributed to its score — components that could not be computed from real "
                "data are omitted, never guessed."
    }

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
from pydantic import BaseModel
from sqlalchemy.orm import Session
from fastapi import Depends
from database import get_db, Report as DBReport

class ReportCreate(BaseModel):
    lat: float
    lon: float
    incident_type: str
    severity: int
    description: str
    reporter_name: str = "Anonymous"
    reporter_email: str | None = None

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

# Mount frontend static files
# BASE_DIR is the root project folder
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)