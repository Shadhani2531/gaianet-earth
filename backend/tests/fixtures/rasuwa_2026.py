"""
Fixtures for the 26 Aug 2026 Bhote Koshi / Rasuwagadhi disaster, TRIMMED
from the real API responses retrieved on 2 Oct 2026:
  - GDACS geteventdata  FL 1104124
  - GDACS SEARCH (FL, 20 Aug - 10 Sep 2026) — 3 of ~60 features kept
  - GDACS getgeometry   FL 1104124 ep. 1
  - USGS fdsnws event   us7000tbwb

Values are copied verbatim. The ONLY simplification: the affected-area
polygon is SUBSAMPLED — every vertex below is a real vertex from the
response, but most vertices were dropped (the real rings have thousands).
The southern border edge near the USGS origin is kept densely so
distance-to-area tests stay faithful (~6.6 km).
"""

GDACS_EVENT_PROPS_COMMON = {
    "eventtype": "FL", "eventid": 1104124, "episodeid": 1, "eventname": "",
    "glide": "FL-2026-000167-NPL", "name": "Flood in Nepal",
    "alertlevel": "Red", "alertscore": 3, "episodealertlevel": "Red", "episodealertscore": 2.5,
    "istemporary": "false", "iscurrent": "false", "country": "Nepal",
    "fromdate": "2026-08-26T01:00:00", "todate": "2026-09-01T14:00:00",
    "datemodified": "2026-09-30T09:40:21", "iso3": "NPL", "source": "GLOFAS",
    "polygonlabel": "Centroid", "Class": "Point_Centroid",
    "affectedcountries": [{"iso2": "NP", "iso3": "NPL", "countryname": "Nepal"}],
    "severitydata": {"severity": 0.0, "severitytext": "Magnitude 0 ", "severityunit": ""},
    "url": {
        "geometry": "https://www.gdacs.org/gdacsapi/api/polygons/getgeometry?eventtype=FL&eventid=1104124&episodeid=1",
        "report": "https://www.gdacs.org/report.aspx?eventid=1104124&episodeid=1&eventtype=FL",
    },
}

GDACS_POINT = {"type": "Point", "coordinates": [85.3649, 27.2953]}

_S = lambda typ, name, val, country, region, desc, onset, expires, inserted: {
    "latest": True, "sendaitype": typ, "sendainame": name, "sendaivalue": val,
    "country": country, "region": region, "dateinsert": inserted, "description": desc,
    "onset_date": onset, "expires_date": expires, "effective_date": None}

SENDAI = [
    _S("B", "affected", "826", "Nepal", "Bagmati Province", "826 [people] Out of contact in Bagmati Province, Nepal", "2026-08-26T01:00:00", "2026-08-27T01:00:00", "2026-09-01T15:57:03.83"),
    _S("B", "rescued", "1552", "Nepal", "Bagmati Province", "1,552 [people] Rescued in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-27T02:00:00", "2026-09-01T15:57:03.843"),
    _S("B", "displaced", "3458", "Nepal", "Bagmati Province", "3,458 [people] Evacuated in Bagmati Province, Nepal", "2026-09-26T02:00:00", "2026-08-31T02:00:00", "2026-09-01T15:57:03.853"),
    _S("B", "rescued", "10451", "Nepal", "Bagmati Province", "10,451 [people] Rescued in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-31T02:00:00", "2026-09-01T15:57:03.863"),
    _S("B", "affected", "910", "Nepal", "Bagmati Province", "910 [people] Out of contact in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-27T02:00:00", "2026-09-01T15:57:03.873"),
    _S("B", "rescued", "4451", "Nepal", "Bagmati Province", "4,451 [people] Rescued in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-28T02:00:00", "2026-09-01T15:57:03.883"),
    _S(" ", "transport damaged", "77", "Nepal", "Bagmati Province", "77 [bridges] Bridge destroyed in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-27T02:00:00", "2026-09-01T15:57:03.893"),
    _S("B", "rescued", "239", "Nepal", "Bagmati Province", "239 [people] Rescued in Bagmati Province, Nepal", "2026-08-26T01:00:00", "2026-08-27T01:00:00", "2026-09-01T15:57:03.907"),
    _S("B", "affected", "558", "China", "Gyirong County", "558 [people] Out of contact in Gyirong County, Shigatse, Tibet, China", "2026-08-26T01:00:00", "2026-08-27T01:00:00", "2026-09-01T15:57:03.913"),
    _S("B", "rescued", "3253", "Nepal", "Bagmati Province", "3,253 [people] Rescued in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-28T02:00:00", "2026-09-01T15:57:03.927"),
    _S("B", "affected", "564", "China", "Gyirong County", "564 [people] Out of contact in Gyirong County, Shigatse, Tibet, China", "2026-08-26T02:00:00", "2026-08-30T02:00:00", "2026-09-01T15:57:03.94"),
    _S("B", "injured", "279", "Nepal", "Bagmati Province", "279 [people] Injured in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-31T02:00:00", "2026-09-01T15:57:03.953"),
    _S("B", "affected", "1124", "Nepal", "Bagmati Province", "1,124 [people] Out of contact in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-28T02:00:00", "2026-09-01T15:57:03.967"),
    _S("B", "affected", "777", "Nepal", "Bagmati Province", "777 [people] Out of contact in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-28T02:00:00", "2026-09-01T15:57:03.98"),
    _S("B", "rescued", "8186", "Nepal", "Bagmati Province", "8,186 [people] Rescued in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-30T02:00:00", "2026-09-01T15:57:03.99"),
    _S("A", "death", "16", "China", "Kyirong County", "16 [people] Fatalities in Gyirong Port , Gyirong County, Shigatse, Tibet, China", "2026-08-26T02:00:00", "2026-08-27T02:00:00", "2026-09-01T15:57:04"),
    _S("A", "death", "939", "Nepal", "Bagmati Province", "939 [people] Fatalities in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-31T02:00:00", "2026-09-01T15:57:04.007"),
    _S("B", "affected", "4247", "Nepal", "Bagmati Province", "4,247 [people] Out of contact in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-31T02:00:00", "2026-09-01T15:57:04.017"),
    _S("B", "affected", "2498", "Nepal", "Bagmati Province", "2,498 [people] Out of contact in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-30T02:00:00", "2026-09-01T15:57:04.023"),
    _S("B", "affected", "3925", "Nepal", "Bagmati Province", "3,925 [people] Out of contact in Bagmati Province, Nepal", "2026-08-26T02:00:00", "2026-08-31T02:00:00", "2026-09-01T15:57:04.033"),
]

GDACS_EVENTDATA = {
    "type": "Feature", "geometry": GDACS_POINT,
    "properties": {**GDACS_EVENT_PROPS_COMMON, "sendai": SENDAI,
                   "images": {"overviewmap": "https://www.gdacs.org/contentdata/resources/FL/1104124/flood_overview_1104124.png"}},
}

# 3 of the ~60 features returned by the real SEARCH call
GDACS_SEARCH = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [84.3739, 26.4211]},
     "properties": {"eventtype": "FL", "eventid": 1104121, "episodeid": 20, "glide": "FL-2026-000165-IND",
                    "alertlevel": "Orange", "alertscore": 2, "iscurrent": "false", "country": "India",
                    "fromdate": "2026-08-09T01:00:00", "todate": "2026-09-28T01:00:00",
                    "affectedcountries": [{"countryname": "India"}],
                    "severitydata": {"severity": 0.0, "severitytext": "Magnitude 0 "}}},
    {"type": "Feature", "geometry": GDACS_POINT, "properties": GDACS_EVENT_PROPS_COMMON},
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-73.3711, 41.119]},
     "properties": {"eventtype": "FL", "eventid": 1103888, "episodeid": 91, "glide": "",
                    "alertlevel": "Green", "alertscore": 1, "iscurrent": "false", "country": "United States",
                    "fromdate": "2026-05-19T01:00:00", "todate": "2026-09-27T01:00:00",
                    "affectedcountries": [{"countryname": "United States"}],
                    "severitydata": {"severity": 0.0, "severitytext": "Magnitude 0 "}}},
]}

# Real vertices, subsampled, in the response's ring order.
_NORTH_RING = [
    [85.6074, 28.2562], [85.6862, 28.3455], [85.6836, 28.3822], [85.5864, 28.7544], [85.5953, 28.8902],
    [85.7117, 28.9394], [86.0817, 28.9244], [86.1584, 29.0456], [86.1112, 29.1637], [85.6122, 29.2044],
    [85.1636, 29.3207], [84.8486, 29.1694], [84.7345, 29.0055], [84.4503, 28.7645], [84.78, 28.6105],
    [84.8568, 28.5703], [85.1912, 28.5683], [85.1847, 28.5329], [85.1129, 28.4775], [85.1078, 28.3461],
    [85.1153, 28.3401], [85.1405, 28.3301], [85.182, 28.3237], [85.2295, 28.3241], [85.2548, 28.2932],
    [85.2925, 28.2874], [85.3301, 28.2997], [85.3483, 28.2939], [85.3622, 28.2855], [85.3773, 28.2779],
    [85.3918, 28.288], [85.4135, 28.3135], [85.4231, 28.3297], [85.4499, 28.3349], [85.4799, 28.3331],
    [85.5013, 28.3333], [85.5129, 28.3312], [85.5143, 28.3308], [85.5159, 28.3305], [85.5182, 28.3305],
    [85.5238, 28.3285], [85.5381, 28.32], [85.5554, 28.3116], [85.5761, 28.3091], [85.5997, 28.3041],
    [85.5963, 28.2988], [85.5987, 28.2846], [85.6062, 28.2565], [85.6074, 28.2562],
]
_SOUTH_RING = [
    [85.4723, 27.1619], [85.5106, 27.1983], [85.5049, 27.2197], [85.4837, 27.2574], [85.4473, 27.3361],
    [85.473, 27.3685], [85.4701, 27.3876], [85.4455, 27.3982], [85.3572, 27.4288], [85.3348, 27.3957],
    [85.3011, 27.3622], [85.2778, 27.3407], [85.2985, 27.2927], [85.3696, 27.2701], [85.3871, 27.2394],
    [85.397, 27.1977], [85.4383, 27.1867], [85.4723, 27.1619],
]
_MULTIPOLY = {"type": "MultiPolygon", "coordinates": [[_NORTH_RING], [_SOUTH_RING]]}

GDACS_GEOMETRY = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": GDACS_POINT, "properties": {**GDACS_EVENT_PROPS_COMMON}},
    {"type": "Feature", "geometry": _MULTIPOLY,
     "properties": {**GDACS_EVENT_PROPS_COMMON, "polygondate": "2026-08-28T01:00:00",
                    "polygonlabel": "Affected area", "Class": "Poly_Affected"}},
    {"type": "Feature", "geometry": _MULTIPOLY,
     "properties": {**GDACS_EVENT_PROPS_COMMON, "polygondate": "2026-08-28T01:00:00",
                    "polygonlabel": "Global area", "Class": "Poly_Global"}},
]}

USGS_FEATURE = {
    "type": "Feature", "id": "us7000tbwb",
    "geometry": {"type": "Point", "coordinates": [85.515, 28.271, 0]},
    "properties": {
        "mag": 5.2, "place": "55 km NW of Kodāri̇̄, Nepal", "time": 1787712730000, "updated": 1790376350040,
        "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000tbwb",
        "alert": None, "status": "reviewed", "tsunami": 0, "sig": 601, "magType": "ms_vx",
        "type": "landslide", "title": "M 5.2 Landslide - 55 km NW of Kodāri̇̄, Nepal",
        "products": {
            "general-header": [{"contents": {"": {"bytes": "<p class=\"alert info\">This event was initially reported as a magnitude 4.4 earthquake. Additional analysis of long period seismic waves indicate that the seismic energy was instead generated by a glacial collapse and debris flow. The location of this event was estimated from satellite images.</p>"}}}],
            "impact-text": [{"contents": {"": {"bytes": "As of September 20, 2026, at least 1,451 people killed, 9,287 injured and 6,145 missing; 8,317 houses destroyed and extensive damage to bridge, road and power infrastructure in Nepal, including 109 bridges, 69 km of roads and 13 hydropower projects. At least 43 people killed and 519 missing, 27 buildings destroyed and communication, power and road access disrupted in Tibet, China. The landslide location was obtained from satellite imagery.\n"}}}],
            "origin": [{"properties": {"horizontal-error": "13.39", "event-type": "landslide",
                                      "latitude": "28.2710", "longitude": "85.5150"}}],
        },
    },
}

# What the plain list query returns (no products, no horizontal error)
USGS_LIST_FEATURE = {**USGS_FEATURE, "properties": {k: v for k, v in USGS_FEATURE["properties"].items() if k != "products"}}


# Two more REAL features from the same GDACS SEARCH response (verbatim fields),
# used to pin down what GDACS's `iscurrent` flag means. Retrieved ~2 Oct 2026.
GDACS_THAILAND_CURRENT = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [98.9954, 17.1054]},
    "properties": {"eventtype": "FL", "eventid": 1104122, "episodeid": 54, "glide": "FL-2026-000158-THA",
                   "alertlevel": "Green", "alertscore": 1, "iscurrent": "true", "country": "Thailand",
                   "fromdate": "2026-08-18T01:00:00", "todate": "2026-09-29T01:00:00",
                   "datemodified": "2026-10-02T07:23:32",
                   "affectedcountries": [{"countryname": "Thailand"}],
                   "severitydata": {"severity": 0.0, "severitytext": "Magnitude 0 "}}}
GDACS_INDIA_NOT_CURRENT = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [84.3739, 26.4211]},
    "properties": {"eventtype": "FL", "eventid": 1104121, "episodeid": 20, "glide": "FL-2026-000165-IND",
                   "alertlevel": "Orange", "alertscore": 2, "iscurrent": "false", "country": "India",
                   "fromdate": "2026-08-09T01:00:00", "todate": "2026-09-28T01:00:00",
                   "datemodified": "2026-10-02T06:24:56",
                   "affectedcountries": [{"countryname": "India"}],
                   "severitydata": {"severity": 0.0, "severitytext": "Magnitude 0 "}}}
# Approximate time of that SEARCH request (for status tests).
SEARCH_RETRIEVED_AT = "2026-10-02T09:30:00Z"
