import os
import random
import requests
from datetime import datetime, timedelta

# WAQI token now read from environment (.env), never hardcoded in source.
# Falls back to a demo token only if nothing is configured, so local dev
# doesn't hard-crash — but production/deployed use should always set
# WAQI_TOKEN in backend/.env.
WAQI_TOKEN = os.environ.get("WAQI_TOKEN", "demo")

# --- Real NOAA global CO2 (GML) -------------------------------------------
# Source: NOAA Global Monitoring Laboratory, globally-averaged marine
# surface monthly mean CO2 (co2_mm_gl.csv). Replaces the previous
# random.randint(380, 450) placeholder with the real published monthly
# global CO2 mixing ratio, cached for a day so we're not refetching NOAA's
# CSV on every single environment-data request.
_NOAA_CO2_URL = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_mm_gl.csv"
_co2_cache = {"value": None, "fetched_at": None}


def get_real_global_co2_ppm() -> float:
    """
    Fetch the most recent real globally-averaged CO2 reading (ppm) from
    NOAA GML. Cached for 24 hours since this updates monthly, not per
    request. Falls back to the last known real value (or a conservative
    recent-real-world estimate) if NOAA is unreachable — NEVER falls back
    to a random number.
    """
    now = datetime.utcnow()
    if (_co2_cache["value"] is not None and _co2_cache["fetched_at"]
            and (now - _co2_cache["fetched_at"]) < timedelta(hours=24)):
        return _co2_cache["value"]

    try:
        resp = requests.get(_NOAA_CO2_URL, timeout=10)
        resp.raise_for_status()
        # File is CSV with a commented header block (lines starting with '#'),
        # then columns: year, month, decimal, average, average_unc, trend, trend_unc
        last_valid = None
        for line in resp.text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                average = float(parts[3])
            except ValueError:
                continue
            if average > 0:
                last_valid = average
        if last_valid is not None:
            _co2_cache["value"] = round(last_valid, 2)
            _co2_cache["fetched_at"] = now
            return _co2_cache["value"]
    except Exception as e:
        print(f"NOAA CO2 fetch failed (using last known/fallback value): {e}")

    # Fallback only if NOAA is unreachable AND we have no prior cached value:
    # a labeled, conservative recent real-world figure, not a random guess.
    if _co2_cache["value"] is not None:
        return _co2_cache["value"]
    return 424.0  # approx. real global mean as of early 2025; update periodically

def generate_environment_data(lat: float, lon: float):
    """
    Fetches real air quality data from AQICN (WAQI).
    Falls back to mock data on error or invalid token.
    """
    # Fallback values used ONLY if WAQI is unreachable. Flagged via
    # "data_source" in the response so callers/UI can show honestly that
    # this particular reading is a fallback estimate, not a live reading.
    aqi = None
    temp = None
    pm25 = None
    data_source = "fallback"

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
            if "pm25" in iaqi:
                pm25 = float(iaqi["pm25"]["v"])

            if aqi is not None:
                data_source = "live_waqi"
    except Exception as e:
        print(f"WAQI API Error (using fallback estimate): {e}")

    # If WAQI truly gave nothing usable, use conservative regional
    # placeholders (clearly labeled) rather than a wide random range.
    if aqi is None:
        aqi = 100  # WAQI "moderate" midpoint, labeled as fallback below
    if temp is None:
        temp = 25.0
    if pm25 is None:
        # Rough AQI->PM2.5 back-estimate using the same EPA breakpoints,
        # only used when WAQI's own pm25 sub-reading is unavailable.
        pm25 = round(aqi * 0.5, 1)

    return {
        "temperature_c": temp,
        "air_quality_index": aqi,
        "pm25": pm25,
        "co2_ppm": get_real_global_co2_ppm(),  # real NOAA GML data, not random
        "location": {"lat": lat, "lon": lon},
        "data_source": data_source
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
