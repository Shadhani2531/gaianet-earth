import httpx
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# OpenWeatherMap API Configuration
# Defaulting to a mock state if no key is provided to ensure "Dynamic Simulation" works immediately
OWM_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY", "MOCK_KEY_REQUIRED")

class WeatherService:
    async def get_weather(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Fetches real-time weather data for a specific coordinate.
        Falls back to a deterministic mock if the API key is missing.
        """
        if OWM_API_KEY == "MOCK_KEY_REQUIRED":
            return self._get_mock_weather(lat, lon)
            
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OWM_API_KEY}&units=metric"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "status": "success",
                        "main": data["weather"][0]["main"],
                        "description": data["weather"][0]["description"],
                        "temp": data["main"]["temp"],
                        "clouds": data["clouds"]["all"],
                        "wind_speed": data["wind"]["speed"],
                        "visibility": data.get("visibility", 10000)
                    }
                else:
                    logger.warning(f"Weather API error: {response.status_code}")
                    return self._get_mock_weather(lat, lon)
        except Exception as e:
            logger.error(f"Weather fetch failed: {e}")
            return self._get_mock_weather(lat, lon)

    def _get_mock_weather(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Generates deterministic weather based on location for simulation stability.
        """
        # Simple logic: Tropical zones have more 'Rain', high latitudes 'Snow' or 'Clouds'
        abs_lat = abs(lat)
        if abs_lat < 23.5:
            state = "Rain" if (lat + lon) % 2 == 0 else "Clear"
        elif abs_lat > 60:
            state = "Snow" if (lat + lon) % 3 == 0 else "Clouds"
        else:
            state = "Clouds" if (lat + lon) % 2 == 0 else "Clear"
            
        return {
            "status": "mock",
            "main": state,
            "description": f"Mock {state.lower()} for Digital Twin simulation",
            "temp": 25 - (abs_lat * 0.5), # Rough temp gradient
            "clouds": 40 if state == "Clouds" else 10,
            "wind_speed": 5.0,
            "visibility": 10000
        }

weather_service = WeatherService()
