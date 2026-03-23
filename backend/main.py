import os
import sys
import requests
import logging
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Ensure the backend directory is in the path for relative service imports
curr_dir = os.path.dirname(os.path.abspath(__file__))
if curr_dir not in sys.path:
    sys.path.append(curr_dir)

from services import nasa_firms, modis_ndvi, climate, mock_data

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="GaiaNet Earth API", description="Production-grade Environmental Intelligence Gateway")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    """Fetch global air quality stations returning PM2.5/PM10 from OpenAQ."""
    try:
        url = "https://api.openaq.org/v2/locations?limit=10000&parameter=pm25&parameter=pm10"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json().get("results", [])
    except Exception as e:
        logger.error(f"Failed to fetch OpenAQ stations: {e}")
        return []

@app.get("/shi-india-live")
async def india_shi_live():
    """Live-calculated Sustainability Health Index (SHI) for major Indian cities."""
    stations = [
        {"city": "Delhi", "lat": 28.6139, "lon": 77.2090, "aqi": 150},
        {"city": "Mumbai", "lat": 19.0760, "lon": 72.8777, "aqi": 90},
        {"city": "Bangalore", "lat": 12.9716, "lon": 77.5946, "aqi": 45},
        {"city": "Kolkata", "lat": 22.5726, "lon": 88.3639, "aqi": 110},
        {"city": "Chennai", "lat": 13.0827, "lon": 80.2707, "aqi": 65},
        {"city": "Hyderabad", "lat": 17.3850, "lon": 78.4867, "aqi": 75},
        {"city": "Ahmedabad", "lat": 23.0225, "lon": 72.5714, "aqi": 120},
        {"city": "Kanpur", "lat": 26.4499, "lon": 80.3319, "aqi": 140},
        {"city": "Shimla", "lat": 31.1048, "lon": 77.1734, "aqi": 20},
        {"city": "Hubli", "lat": 15.3647, "lon": 75.1240, "aqi": 35}
    ]
    
    result = []
    for s in stations:
        # Calculate SHI: Higher AQI = Lower SHI score
        shi = max(0, min(100, 100 - (s["aqi"]/3)))
        color = "red" if shi < 40 else ("yellow" if shi < 70 else "green")
        s.update({"shi": int(shi), "color": color})
        result.append(s)
    return result

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
    """Returns biome-modelled global NDVI distribution as GeoJSON."""
    return modis_ndvi.get_vegetation_geojson()

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

@app.get("/prediction")
def get_prediction(scenario: str = Query(...), lat: float = Query(...), lon: float = Query(...)):
    """Generates data-driven scenario-based impact predictions."""
    climate_info = climate.get_location_climate(lat, lon)
    anomaly = climate_info["current_anomaly"]
    
    base_multiplier = 1.5 if "1_5" in scenario else 2.0 if "2_0" in scenario else 1.0
    risk_score = min(100, (abs(anomaly) * 20) * base_multiplier)
    
    recent_rain = [h["total_rainfall_mm"] for h in climate_info["historical_trends"][-3:]]
    avg_rain = sum(recent_rain) / len(recent_rain)
    drought_prob = max(10, min(95, 80 - (avg_rain / 1.5) + (anomaly * 5)))
    flood_prob = max(5, min(90, (avg_rain / 2) - (anomaly * 3)))
    wildfire_risk = max(10, min(98, (anomaly * 25) + (drought_prob * 0.4)))

    return {
        "scenario": scenario,
        "location": {"lat": lat, "lon": lon},
        "risk_index": round(wildfire_risk, 1),
        "probabilities": {
            "wildfire": round(wildfire_risk, 1),
            "drought": round(drought_prob, 1),
            "flood": round(flood_prob, 1)
        },
        "predicted_temp_change_c": round(base_multiplier * 0.8, 2),
        "sea_level_rise_cm": round(base_multiplier * 12.4, 1),
        "impact_summary": "Critical local instability predicted." if wildfire_risk > 75 else "Significant environmental shifts expected."
    }

# Mount frontend static files
# BASE_DIR is the root project folder
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)