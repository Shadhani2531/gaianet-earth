import random
import requests
from datetime import datetime, timedelta

WAQI_TOKEN = "c9b347631e0730d344f9c49101767d214d8e8ff2"

def generate_environment_data(lat: float, lon: float):
    """
    Fetches real air quality data from AQICN (WAQI).
    Falls back to mock data on error or invalid token.
    """
    # Default mock values
    aqi = random.randint(20, 300)
    temp = round(random.uniform(15.0, 35.0), 1)
    
    url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={WAQI_TOKEN}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "ok":
            aqi_val = data["data"].get("aqi")
            if aqi_val != "-" and aqi_val is not None:
                aqi = int(aqi_val)
                
            iaqi = data["data"].get("iaqi", {})
            if "t" in iaqi:
                temp = float(iaqi["t"]["v"])
    except Exception as e:
        print(f"WAQI API Error (using mock instead): {e}")

    return {
        "temperature_c": temp,
        "air_quality_index": aqi,
        "co2_ppm": random.randint(380, 450),
        "location": {"lat": lat, "lon": lon}
    }

def get_base_coordinates():
    # Roughly the center of India for initial viewport, but generate globally
    return {"lat": 20.5937, "lon": 78.9629}

def generate_weather_data(lat: float, lon: float):
    return {
        "temperature_c": round(random.uniform(-10.0, 45.0), 1),
        "humidity_percent": random.randint(10, 100),
        "wind_speed_kph": round(random.uniform(0.0, 100.0), 1),
        "pressure_hpa": random.randint(980, 1050),
        "condition": random.choice(["Clear", "Cloudy", "Rain", "Snow", "Storm", "Partly Cloudy"]),
        "timestamp": datetime.utcnow().isoformat()
    }

def generate_vegetation_data():
    # Return mock NDVI data points (Normalized Difference Vegetation Index)
    # NDVI values range from -1.0 to +1.0
    data = []
    for _ in range(50):
        lat = random.uniform(-60.0, 70.0)
        lon = random.uniform(-180.0, 180.0)
        ndvi = round(random.uniform(-0.2, 0.9), 2)
        data.append({"lat": lat, "lon": lon, "ndvi": ndvi})
    return {"timestamp": datetime.utcnow().isoformat(), "locations": data}

def generate_wildfire_data():
    # Return mock active wildfire locations
    data = []
    for _ in range(20):
        lat = random.uniform(-50.0, 70.0)
        lon = random.uniform(-180.0, 180.0)
        intensity = round(random.uniform(10.0, 100.0), 1) # FRP (Fire Radiative Power)
        data.append({"lat": lat, "lon": lon, "intensity_frp": intensity})
    return {"timestamp": datetime.utcnow().isoformat(), "fires": data}

def generate_climate_data(lat: float, lon: float):
    # Mock historical climate trends for a location
    history = []
    base_temp = random.uniform(10.0, 30.0)
    now = datetime.utcnow()
    for i in range(12): # Last 12 months
        date = now - timedelta(days=30*i)
        temp = base_temp + random.uniform(-5.0, 5.0)
        rainfall = random.uniform(0.0, 200.0)
        history.append({
            "month": date.strftime("%Y-%m"),
            "avg_temp_c": round(temp, 1),
            "total_rainfall_mm": round(rainfall, 1)
        })
    history.reverse()
    return {"location": {"lat": lat, "lon": lon}, "historical_trends": history}

def generate_prediction_data(scenario: str, lat: float, lon: float):
    # Mock prediction data based on what-if scenarios
    base_temp = random.uniform(10.0, 30.0)
    prediction = {
        "scenario": scenario,
        "location": {"lat": lat, "lon": lon},
        "predicted_temp_change_c": 0.0,
        "sea_level_rise_cm": 0.0,
        "risk_level": "Low"
    }
    
    if scenario == "temp_increase_1_5":
        prediction["predicted_temp_change_c"] = 1.5
        prediction["sea_level_rise_cm"] = 25.0
        prediction["risk_level"] = "Medium"
    elif scenario == "temp_increase_2_0":
        prediction["predicted_temp_change_c"] = 2.0
        prediction["sea_level_rise_cm"] = 40.0
        prediction["risk_level"] = "High"
    elif scenario == "deforestation_high":
        prediction["predicted_temp_change_c"] = 3.0
        prediction["risk_level"] = "Critical"
        
    return prediction
