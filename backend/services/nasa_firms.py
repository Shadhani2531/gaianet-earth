import csv
import logging
from io import StringIO
import requests
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Cache variables
_firms_cache = None
_last_fetch_time = None
CACHE_EXPIRY = 600  # 10 minutes (600 seconds)

# NASA FIRMS MODIS 24h Global Data
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Global_24h.csv"
MAX_FEATURES = 500

# Headers to prevent blocking
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/csv'
}

def get_wildfires_geojson() -> Dict[str, Any]:
    global _firms_cache, _last_fetch_time
    
    now = datetime.now(timezone.utc)
    
    # Return cache if valid (10-minute expiry)
    if _firms_cache and _last_fetch_time:
        if (now - _last_fetch_time).total_seconds() < CACHE_EXPIRY:
            logger.info("Returning cached FIRMS data")
            return _firms_cache
            
    try:
        logger.info(f"Fetching FIRMS data from {FIRMS_URL}")
        response = requests.get(FIRMS_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        
        # Parse CSV content
        csv_file = StringIO(response.text)
        reader = csv.DictReader(csv_file)
        rows = list(reader)
        
        if not rows:
            logger.warning("No wildfire data found in FIRMS response")
            return {"type": "FeatureCollection", "features": [], "metadata": {"status": "empty"}}
            
        # Parse and sort by frp (Fire Radiative Power) descending
        def get_frp_value(row):
            try:
                return float(row.get('frp', 0))
            except (ValueError, TypeError):
                return 0.0
                
        # Sort by FRP descending to prioritize intense fires
        rows.sort(key=get_frp_value, reverse=True)
        top_rows = rows[:MAX_FEATURES]
        
        features = []
        for row in top_rows:
            try:
                # Essential fields
                lat = float(row['latitude'])
                lon = float(row['longitude'])
                frp = float(row['frp'])
                acq_date = row.get('acq_date', 'Unknown')
                acq_time = row.get('acq_time', '0000')
                
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lon, lat]
                    },
                    "properties": {
                        "value": frp,
                        "frp": frp,
                        "acq_date": acq_date,
                        "acq_time": acq_time,
                        "type": "wildfire",
                        "satellite": row.get('satellite', 'Unknown'),
                        "confidence": row.get('confidence', 'Unknown')
                    }
                })
            except (ValueError, KeyError, TypeError) as e:
                logger.debug(f"Skipping invalid FIRMS row: {e}")
                continue
                
        geojson = {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "source": "NASA FIRMS (MODIS 24h)",
                "timestamp": now.isoformat(),
                "count": len(features),
                "status": "success"
            }
        }
        
        # Update cache
        _firms_cache = geojson
        _last_fetch_time = now
        
        return geojson
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching NASA FIRMS data: {e}")
        # Return fallback empty collection on failure to keep frontend stable
        return _firms_cache if _firms_cache else {
            "type": "FeatureCollection", 
            "features": [], 
            "metadata": {"status": "error", "message": str(e)}
        }
    except Exception as e:
        logger.error(f"Unexpected error in FIRMS service: {e}")
        return {"type": "FeatureCollection", "features": [], "metadata": {"status": "error"}}
