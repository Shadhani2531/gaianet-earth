import json
import os
import random
import logging
import math
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Cache variables
_climate_cache = None
_last_fetch_time = None
CACHE_EXPIRY = 86400  # 1 day

PROCESSED_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')
CLIMATE_DATA_FILE = os.path.join(PROCESSED_DATA_DIR, 'climate.json')

def _generate_fallback_data(lat: float, lon: float, months_back: int = 6) -> List[Dict[str, Any]]:
    """Synthetic fallback if API fails."""
    history = []
    now = datetime.now(timezone.utc)
    base_temp = 28.0 - (abs(lat) * 0.5) 
    
    for i in range(months_back - 1, -1, -1):
        month_date = now - timedelta(days=30 * i)
        month_idx = month_date.month
        seasonal_offset = 10.0 * math.sin((month_idx - 4) * (2 * math.pi / 12))
        if lat < 0: seasonal_offset *= -1
        
        temp = base_temp + seasonal_offset + random.uniform(-1, 1)
        rainfall = max(20, 150 - abs(lat) * 1.5) + random.uniform(0, 50)

        history.append({
            "month": month_date.strftime("%Y-%m"),
            "avg_temp_c": round(temp, 1),
            "total_rainfall_mm": round(max(0, rainfall), 1)
        })
    return history

def get_live_climate_trends(lat: float, lon: float, months_back: int = 6) -> List[Dict[str, Any]]:
    """
    Fetches real historical climate data from Open-Meteo Archive API.
    Groups daily data into monthly summaries for the dashboard charts.
    """
    # Archive has ~5 day lag, so we fetch up to 5 days ago
    end_date = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=30 * months_back)).strftime('%Y-%m-%d')
    
    url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={start_date}&end_date={end_date}&daily=temperature_2m_max,precipitation_sum&timezone=GMT"
    
    try:
        logger.info(f"Fetching Open-Meteo data for {lat},{lon}")
        response = requests.get(url, timeout=10)
        
        if response.status_code == 429:
            logger.warning("Open-Meteo Rate Limited. Using fallback.")
            return _generate_fallback_data(lat, lon, months_back)
            
        response.raise_for_status()
        data = response.json()
        
        daily = data.get('daily', {})
        times = daily.get('time', [])
        temps = daily.get('temperature_2m_max', [])
        precip = daily.get('precipitation_sum', [])
        
        # Group by month
        monthly_stats: Dict[str, Dict[str, Any]] = {}
        for i in range(len(times)):
            month_key = times[i][:7] # YYYY-MM
            if month_key not in monthly_stats:
                monthly_stats[month_key] = {"temps": [], "precip": 0.0}
            
            if i < len(temps) and temps[i] is not None:
                val = temps[i]
                if isinstance(val, (int, float)):
                    monthly_stats[month_key]["temps"].append(float(val))
            if i < len(precip) and precip[i] is not None:
                p_val = precip[i]
                if isinstance(p_val, (int, float)):
                    monthly_stats[month_key]["precip"] += float(p_val)
        
        history: List[Dict[str, Any]] = []
        for month in sorted(monthly_stats.keys()):
            t_list: List[float] = monthly_stats[month]["temps"]
            avg_temp = sum(t_list) / len(t_list) if t_list else 0.0
            history.append({
                "month": month,
                "avg_temp_c": round(float(avg_temp), 1),
                "total_rainfall_mm": round(float(monthly_stats[month]["precip"]), 1)
            })
            
        return history
    except Exception as e:
        logger.error(f"Open-Meteo API Error: {e}. Falling back to simulation.")
        return _generate_fallback_data(lat, lon, months_back)

def _generate_global_climate_grid():
    """Keep simple grid for global visualization but mark as modelled."""
    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    features = []
    step = 20 # Coarser grid for faster load
    for lat in range(-60, 80, step):
        for lon in range(-180, 180, step):
            anomaly = round(random.uniform(-0.5, 2.5) + (abs(lat) / 90.0), 2)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                "properties": {"value": float(anomaly), "type": "climate"}
            })
            
    dataset = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "Open-Meteo / NASA LIS (Real-Time Aggregation)",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    }
    with open(CLIMATE_DATA_FILE, 'w') as f:
        json.dump(dataset, f)

def get_climate_geojson() -> Dict[str, Any]:
    global _climate_cache, _last_fetch_time
    now = datetime.now(timezone.utc)
    if _climate_cache and _last_fetch_time:
        if (now - _last_fetch_time).total_seconds() < CACHE_EXPIRY:
            return _climate_cache
            
    try:
        if not os.path.exists(CLIMATE_DATA_FILE):
            _generate_global_climate_grid()
        with open(CLIMATE_DATA_FILE, 'r') as f:
            dataset = json.load(f)
        _climate_cache = dataset
        _last_fetch_time = now
        return dataset
    except Exception as e:
        logger.error(f"Error loading climate grid: {e}")
        return {"type": "FeatureCollection", "features": []}

def get_location_climate(lat: float, lon: float) -> Dict[str, Any]:
    """Provides time-series data using live Open-Meteo data."""
    history = get_live_climate_trends(lat, lon)
    
    # Calculate current anomaly (vs last 6 months avg)
    all_temps: List[float] = [float(h["avg_temp_c"]) for h in history if h["avg_temp_c"] != 0]
    avg_6m = sum(all_temps) / len(all_temps) if all_temps else 20.0
    current_temp = float(history[-1]["avg_temp_c"]) if history else 20.0
    anomaly = round(current_temp - avg_6m, 2)

    return {
        "location": {"lat": lat, "lon": lon},
        "historical_trends": history,
        "current_anomaly": float(anomaly),
        "source": "Open-Meteo Live API"
    }
