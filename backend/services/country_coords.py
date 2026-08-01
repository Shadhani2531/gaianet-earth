"""
GaiaNet Earth — Country reference coordinates
File: backend/services/country_coords.py

Static reference data: each country's capital city coordinates, used as a
single representative point per country for the Tab 6 composite SHI's
climate and NDVI components (querying every square km of every country
live isn't practical; a representative point is standard practice for
country-level composite indices — e.g. many World Bank / UN indices use
capital or largest-city proxies for exactly this reason).

Source: cross-referenced against public capital-coordinate references
(Wikipedia "List of national capitals", public GIS capital datasets).
Coordinates are real, static facts (a capital's location doesn't change),
not fabricated data — this is reference metadata, the same category as
the EPA AQI breakpoint table used elsewhere in this codebase.

This is NOT exhaustive — it covers a substantial, growing set of
countries. Countries missing from this table simply won't get a climate/
NDVI component in their composite SHI (their AQI component, if real
OpenAQ data exists for them, still applies) — never backfilled with a
guess.
"""

from typing import Optional

# ISO 3166-1 alpha-2 code -> (capital_name, lat, lon, is_tropical)
# is_tropical: within ~23.5 degrees of the equator (Tropic of Cancer/Capricorn)
COUNTRY_CAPITALS: dict[str, tuple] = {
    "US": ("Washington, D.C.", 38.9072, -77.0369, False),
    "CA": ("Ottawa", 45.4215, -75.6972, False),
    "MX": ("Mexico City", 19.4326, -99.1332, True),
    "BR": ("Brasília", -15.7939, -47.8828, True),
    "AR": ("Buenos Aires", -34.6037, -58.3816, False),
    "CL": ("Santiago", -33.4489, -70.6693, False),
    "CO": ("Bogotá", 4.7110, -74.0721, True),
    "PE": ("Lima", -12.0464, -77.0428, True),
    "GB": ("London", 51.5072, -0.1276, False),
    "FR": ("Paris", 48.8566, 2.3522, False),
    "DE": ("Berlin", 52.5200, 13.4050, False),
    "ES": ("Madrid", 40.4168, -3.7038, False),
    "IT": ("Rome", 41.9028, 12.4964, False),
    "PT": ("Lisbon", 38.7223, -9.1393, False),
    "NL": ("Amsterdam", 52.3676, 4.9041, False),
    "BE": ("Brussels", 50.8503, 4.3517, False),
    "CH": ("Bern", 46.9480, 7.4474, False),
    "AT": ("Vienna", 48.2082, 16.3738, False),
    "SE": ("Stockholm", 59.3293, 18.0686, False),
    "NO": ("Oslo", 59.9139, 10.7522, False),
    "FI": ("Helsinki", 60.1699, 24.9384, False),
    "DK": ("Copenhagen", 55.6761, 12.5683, False),
    "PL": ("Warsaw", 52.2297, 21.0122, False),
    "GR": ("Athens", 37.9838, 23.7275, False),
    "RU": ("Moscow", 55.7558, 37.6173, False),
    "UA": ("Kyiv", 50.4501, 30.5234, False),
    "TR": ("Ankara", 39.9334, 32.8597, False),
    "IN": ("New Delhi", 28.6139, 77.2090, False),
    "CN": ("Beijing", 39.9042, 116.4074, False),
    "JP": ("Tokyo", 35.6762, 139.6503, False),
    "KR": ("Seoul", 37.5665, 126.9780, False),
    "ID": ("Jakarta", -6.2088, 106.8456, True),
    "TH": ("Bangkok", 13.7563, 100.5018, True),
    "VN": ("Hanoi", 21.0278, 105.8342, True),
    "PH": ("Manila", 14.5995, 120.9842, True),
    "MY": ("Kuala Lumpur", 3.1390, 101.6869, True),
    "SG": ("Singapore", 1.3521, 103.8198, True),
    "PK": ("Islamabad", 33.6844, 73.0479, False),
    "BD": ("Dhaka", 23.8103, 90.4125, True),
    "NP": ("Kathmandu", 27.7172, 85.3240, False),
    "LK": ("Colombo", 6.9271, 79.8612, True),
    "AU": ("Canberra", -35.2809, 149.1300, False),
    "NZ": ("Wellington", -41.2865, 174.7762, False),
    "ZA": ("Pretoria", -25.7479, 28.2293, False),
    "NG": ("Abuja", 9.0765, 7.3986, True),
    "EG": ("Cairo", 30.0444, 31.2357, False),
    "KE": ("Nairobi", -1.2921, 36.8219, True),
    "ET": ("Addis Ababa", 9.0250, 38.7469, True),
    "GH": ("Accra", 5.6037, -0.1870, True),
    "MA": ("Rabat", 34.0209, -6.8416, False),
    "DZ": ("Algiers", 36.7538, 3.0588, False),
    "TZ": ("Dodoma", -6.1730, 35.7419, True),
    "UG": ("Kampala", 0.3476, 32.5825, True),
    "SA": ("Riyadh", 24.7136, 46.6753, True),
    "AE": ("Abu Dhabi", 24.4539, 54.3773, True),
    "IL": ("Jerusalem", 31.7683, 35.2137, False),
    "IR": ("Tehran", 35.6892, 51.3890, False),
    "IQ": ("Baghdad", 33.3152, 44.3661, False),
    "KZ": ("Astana", 51.1694, 71.4491, False),
    "UZ": ("Tashkent", 41.2995, 69.2401, False),
    "AF": ("Kabul", 34.5553, 69.2075, False),
    "MM": ("Naypyidaw", 19.7633, 96.0785, True),
    "KH": ("Phnom Penh", 11.5564, 104.9282, True),
    "LA": ("Vientiane", 17.9757, 102.6331, True),
    "MN": ("Ulaanbaatar", 47.8864, 106.9057, False),
    "IE": ("Dublin", 53.3498, -6.2603, False),
    "IS": ("Reykjavik", 64.1466, -21.9426, False),
    "RO": ("Bucharest", 44.4268, 26.1025, False),
    "BG": ("Sofia", 42.6977, 23.3219, False),
    "HU": ("Budapest", 47.4979, 19.0402, False),
    "CZ": ("Prague", 50.0755, 14.4378, False),
    "SK": ("Bratislava", 48.1486, 17.1077, False),
    "HR": ("Zagreb", 45.8150, 15.9819, False),
    "RS": ("Belgrade", 44.7866, 20.4489, False),
    "VE": ("Caracas", 10.4806, -66.9036, True),
    "EC": ("Quito", -0.1807, -78.4678, True),
    "BO": ("Sucre", -19.0333, -65.2627, True),
    "PY": ("Asunción", -25.2637, -57.5759, False),
    "UY": ("Montevideo", -34.9011, -56.1645, False),
    "CU": ("Havana", 23.1136, -82.3666, True),
    "DO": ("Santo Domingo", 18.4861, -69.9312, True),
    "GT": ("Guatemala City", 14.6349, -90.5069, True),
    "CR": ("San José", 9.9281, -84.0907, True),
    "PA": ("Panama City", 8.9824, -79.5199, True),
    "JM": ("Kingston", 17.9714, -76.7931, True),
}


def get_country_reference_point(country_code: str) -> Optional[dict]:
    """Returns {'capital': str, 'lat': float, 'lon': float, 'is_tropical': bool}
    for a real country capital, or None if not in our reference table."""
    entry = COUNTRY_CAPITALS.get(country_code.upper())
    if not entry:
        return None
    capital, lat, lon, is_tropical = entry
    return {"capital": capital, "lat": lat, "lon": lon, "is_tropical": is_tropical}
