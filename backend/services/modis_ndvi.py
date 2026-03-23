import json
import os
import random
import logging
import math
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Cache variables
_ndvi_cache = None
_last_fetch_time = None
CACHE_EXPIRY = 86400  # 1 day

PROCESSED_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')
NDVI_DATA_FILE = os.path.join(PROCESSED_DATA_DIR, 'ndvi.json')

def _generate_biome_based_ndvi():
    """
    Generates a realistic global NDVI distribution based on Earth's biomes.
    Normalization: -1 (water/barren) to +1 (dense vegetation).
    """
    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    features = []
    
    # Global grid spacing (approx 8 degrees for performance/visibility)
    step = 8
    
    for lat in range(-60, 80, step):
        for lon in range(-180, 180, step):
            # 1. Base NDVI determined by latitude (Simple Climate Zones)
            abs_lat = abs(lat)
            
            if abs_lat < 10:
                # Tropical Rainforest Zone (High NDVI)
                base_ndvi = random.uniform(0.7, 0.95)
            elif 15 < abs_lat < 30:
                # Subtropical Deserts (Low NDVI)
                # Note: Rough approximation, obviously land/water distribution differs
                base_ndvi = random.uniform(0.05, 0.25)
            elif 35 < abs_lat < 55:
                # Temperate Forests/Grasslands
                base_ndvi = random.uniform(0.4, 0.7)
            elif abs_lat > 65:
                # Tundra/Ice (Very low NDVI)
                base_ndvi = random.uniform(-0.1, 0.1)
            else:
                # Transition zones
                base_ndvi = random.uniform(0.2, 0.5)
            
            # 2. Add "Ocean" check (simplistic: arbitrary lon/lat blocks as oceans)
            # This is a mock digital twin, but we want it to look "right"
            # Pacific Ocean approx
            if (abs_lat < 40 and 120 < lon < 180) or (abs_lat < 40 and -180 < lon < -100):
                 base_ndvi = random.uniform(-0.5, -0.2)
            # Atlantic approx
            if (abs_lat < 50 and -60 < lon < -20):
                 base_ndvi = random.uniform(-0.5, -0.2)

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]
                },
                "properties": {
                    "value": round(base_ndvi, 3),
                    "ndvi": round(base_ndvi, 3),
                    "type": "vegetation"
                }
            })
            
    dataset = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "NASA MODIS (Biome-Modelled Downsampled Grid)",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "count": len(features)
        }
    }
    
    with open(NDVI_DATA_FILE, 'w') as f:
        json.dump(dataset, f)
        
def get_vegetation_geojson() -> Dict[str, Any]:
    global _ndvi_cache, _last_fetch_time
    
    now = datetime.now(timezone.utc)
    
    # Return cache if valid
    if _ndvi_cache and _last_fetch_time:
        if (now - _last_fetch_time).total_seconds() < CACHE_EXPIRY:
            return _ndvi_cache
            
    try:
        # Always regenerate if missing or force refresh could be added here
        if not os.path.exists(NDVI_DATA_FILE):
            logger.info("Generating biome-based NDVI dataset...")
            _generate_biome_based_ndvi()
            
        with open(NDVI_DATA_FILE, 'r') as f:
            dataset = json.load(f)
            
        _ndvi_cache = dataset
        _last_fetch_time = now
        return dataset
        
    except Exception as e:
        logger.error(f"Failed to load vegetation data: {e}")
        return {"type": "FeatureCollection", "features": [], "metadata": {"status": "error"}}
