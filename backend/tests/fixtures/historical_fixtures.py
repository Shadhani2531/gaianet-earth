"""
Fixtures for Historical Extremes tests.

REAL: two earthquake records copied verbatim from the live NCEI response
(https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/earthquakes, page 1,
retrieved 3 Oct 2026).

SYNTHETIC: every other record uses NCEI's real field names but PLACEHOLDER
values chosen to exercise rules (linking, overlays, eras, preliminary
handling). They are not NCEI's actual figures.
"""

REAL_NCEI_EQ = [
    {"id": 64, "year": 115, "month": 12, "day": 13, "locationName": "TURKEY:  ANTAKYA (ANTIOCH)", "latitude": 36.1,
     "longitude": 36.1, "eqMagnitude": 7.5, "intensity": 11, "deaths": 260000, "deathsAmountOrder": 4,
     "damageAmountOrder": 4, "tsunamiEventId": 4396, "eqMagMs": 7.5, "eqMagMl": 7.4, "publish": True,
     "deathsTotal": 260000, "deathsAmountOrderTotal": 4, "damageAmountOrderTotal": 4, "country": "TURKEY", "regionCode": 140},
    {"id": 30, "year": -186, "month": 2, "day": 22, "locationName": "CHINA:  GANSU PROVINCE", "latitude": 33.8,
     "longitude": 105.6, "eqMagnitude": 7, "deaths": 760, "deathsAmountOrder": 3, "eqMagMs": 7, "publish": True,
     "deathsTotal": 760, "deathsAmountOrderTotal": 3, "country": "CHINA", "regionCode": 30},
]

SYN_NCEI_EQ = [
    {"id": 9001, "year": 1556, "month": 1, "day": 23, "locationName": "CHINA:  SHAANXI PROVINCE", "latitude": 34.5,
     "longitude": 109.7, "eqMagnitude": 8, "deathsTotal": 830000, "deaths": 830000, "publish": True, "country": "CHINA"},
    {"id": 9002, "year": 1976, "month": 7, "day": 27, "locationName": "CHINA:  HEBEI PROVINCE:  TANGSHAN", "latitude": 39.6,
     "longitude": 118.2, "eqMagnitude": 7.6, "deathsTotal": 242769, "deaths": 242769, "publish": True, "country": "CHINA"},
    {"id": 9003, "year": 2010, "month": 1, "day": 12, "locationName": "HAITI:  PORT-AU-PRINCE", "latitude": 18.46,
     "longitude": -72.53, "eqMagnitude": 7.0, "deathsTotal": 316000, "deaths": 316000, "tsunamiEventId": 9502,
     "publish": True, "country": "HAITI"},
    {"id": 9004, "year": 2004, "month": 12, "day": 26, "locationName": "INDONESIA:  SUMATRA:  ACEH:  OFF WEST COAST",
     "latitude": 3.3, "longitude": 95.98, "eqMagnitude": 9.1, "deaths": 1000, "deathsTotal": 227899,
     "tsunamiEventId": 9500, "publish": True, "country": "INDONESIA"},
    {"id": 9005, "year": 2026, "month": 3, "day": 1, "locationName": "TESTLAND:  RECENT CITY", "latitude": 10.0,
     "longitude": 10.0, "eqMagnitude": 7.9, "deathsTotal": 900000, "deaths": 900000, "publish": True, "country": "TESTLAND"},
    {"id": 9006, "year": 1920, "month": 12, "day": 16, "locationName": "CHINA:  NINGXIA:  HAIYUAN", "latitude": 36.6,
     "longitude": 105.3, "eqMagnitude": 7.8, "deathsTotal": 200000, "deaths": 200000, "publish": True, "country": "CHINA"},
    {"id": 9008, "year": 1693, "month": 1, "day": 9, "locationName": "ITALY:  SICILY", "latitude": 37.2,
     "longitude": 15.0, "deathsTotal": 60000, "deaths": 60000, "publish": True, "country": "ITALY"},
    {"id": 9009, "year": 1693, "month": 1, "day": 11, "locationName": "ITALY:  SICILY, CALABRIA", "latitude": 37.14,
     "longitude": 15.01, "deathsTotal": 54000, "deaths": 54000, "publish": True, "country": "ITALY"},
    {"id": 9007, "year": 1999, "month": 1, "day": 1, "locationName": "UNPUBLISHED", "latitude": 0, "longitude": 0,
     "deathsTotal": 5000000, "publish": False, "country": "X"},
]

SYN_NCEI_TSUNAMI = [
    {"id": 9500, "year": 2004, "month": 12, "day": 26, "locationName": "INDONESIA:  OFF WEST COAST OF SUMATRA",
     "latitude": 3.3, "longitude": 95.98, "deaths": 227899, "deathsTotal": 227899, "maxWaterHeight": 50.9,
     "publish": True, "country": "INDONESIA"},
    {"id": 9502, "year": 2010, "month": 1, "day": 12, "locationName": "HAITI:  PETIT PARADIS", "latitude": 18.46,
     "longitude": -72.53, "deaths": 7, "deathsTotal": 316000, "publish": True, "country": "HAITI"},
    {"id": 9503, "year": 1902, "month": 5, "day": 8, "locationName": "MARTINIQUE:  MOUNT PELEE", "latitude": 14.82,
     "longitude": -61.17, "deaths": 0, "deathsTotal": 28000, "volcanoEventId": 9899, "publish": True, "country": "MARTINIQUE"},
    {"id": 9501, "year": 1883, "month": 8, "day": 27, "locationName": "INDONESIA:  KRAKATAU", "latitude": -6.1,
     "longitude": 105.42, "deaths": 36000, "deathsTotal": 36417, "volcanoEventId": 9802, "publish": True, "country": "INDONESIA"},
]

# REAL: two volcano records copied verbatim (selected fields) from the live NCEI
# volcano API (retrieved 4 Oct 2026). Note publish=false on every live record.
REAL_NCEI_VOLCANO = [
    {"id": 1, "year": 1169, "month": 2, "day": 4, "tsunamiEventId": 2852, "earthquakeEventId": 421, "name": "Etna",
     "location": "Italy", "country": "Italy", "latitude": 37.748, "longitude": 14.999, "deathsTotal": 16000,
     "deathsAmountOrderTotal": 4, "significant": True, "publish": False, "eruption": True, "status": "Historical"},
    {"id": 64, "year": 1672, "month": 8, "day": 4, "name": "Merapi", "location": "Java", "country": "Indonesia",
     "latitude": -7.54, "longitude": 110.446, "vei": 3, "agent": "P", "deaths": 3000, "deathsAmountOrder": 4,
     "deathsTotal": 3000, "deathsAmountOrderTotal": 4, "significant": True, "publish": False, "eruption": True,
     "status": "Historical"},
]

# SYNTHETIC volcano records in the live format (publish=false, eruption flag).
SYN_NCEI_VOLCANO = [
    {"id": 9801, "year": 1815, "month": 4, "day": 10, "name": "Tambora", "country": "Indonesia", "latitude": -8.25,
     "longitude": 118.0, "vei": 7, "deaths": 11000, "deathsTotal": 11000, "publish": False, "eruption": True},
    {"id": 9802, "year": 1883, "month": 8, "day": 27, "name": "Krakatau", "country": "Indonesia", "latitude": -6.1,
     "longitude": 105.42, "vei": 6, "deathsTotal": 36417, "tsunamiEventId": 9501, "publish": False, "eruption": True},
    {"id": 9803, "year": 1257, "name": "Samalas (Rinjani)", "country": "Indonesia", "latitude": -8.42,
     "longitude": 116.47, "vei": 7, "publish": False, "eruption": True},
    {"id": 9804, "year": -4350, "name": "Kikai", "country": "Japan", "latitude": 30.79, "longitude": 130.31,
     "vei": 7, "publish": False, "eruption": True},
    {"id": 9806, "year": 1986, "month": 8, "day": 21, "name": "Test gas-release crater", "country": "Testland",
     "latitude": 6.4, "longitude": 10.3, "vei": 7, "deaths": 120000, "deathsTotal": 120000, "publish": False,
     "eruption": False},
]

def usgs(eid, mag, iso_time_ms, place, status="reviewed", lat=0.0, lon=0.0):
    return {"type": "Feature", "id": eid, "geometry": {"type": "Point", "coordinates": [lon, lat, 10]},
            "properties": {"mag": mag, "place": place, "time": iso_time_ms, "status": status,
                           "url": f"https://earthquake.usgs.gov/earthquakes/eventpage/{eid}"}}

# SYNTHETIC USGS records (ids/values are placeholders)
SYN_USGS_LARGEST = [
    usgs("fx1960", 9.5, -305000000000, "Bio-Bio, Chile (fixture)", status="automatic", lat=-38.1, lon=-73.4),
    usgs("fx1964", 9.2, -184000000000, "Southern Alaska (fixture)", status="automatic", lat=60.9, lon=-147.3),
    usgs("fx2004", 9.1, 1104067000000, "Sumatra (fixture)", lat=3.3, lon=95.9),
    usgs("fxnew", 9.6, 1790800000000, "Very recent (fixture)", status="automatic", lat=1, lon=1),
]

ALL = {"earthquakes": REAL_NCEI_EQ + SYN_NCEI_EQ, "tsunamis": SYN_NCEI_TSUNAMI,
       "volcanoes": REAL_NCEI_VOLCANO + SYN_NCEI_VOLCANO, "usgs_largest": SYN_USGS_LARGEST}
