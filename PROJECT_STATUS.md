# GaiaNet Earth (v2.2.0) — Project Status

An honest snapshot of the current code (October 2026). If this file and the code disagree, the code is right — fix this file.

---

## Tabs (8, all live)

1. **🌍 Immersive Earth** — CesiumJS globe, live NASA GIBS imagery.
2. **🛰️ Climate Insight** — point analytics for any clicked or searched place; layer toggles gate the related cards and charts.
3. **🕐 Historical Timeline** — NASA Worldview Snapshot images (2000–present) in their own panel, with split compare. Rendered off-globe on purpose: swapping live imagery layers destabilised the shared Cesium scene.
4. **🧠 Forecast Lab** — 7-day weather (dated), 5-day AQI (dated), wildfire-risk score, what-if simulator.
5. **📢 Community Reports** — citizen reports in SQLite, fire reports cross-checked against NASA FIRMS.
6. **🌐 Global Health Index** — country-level composite SHI (~90 countries).
7. **⚠️ Disasters & Hazards** — Active now · Previous (7 days / 30 days / custom) · Historical Extremes (Deadliest · Heatwaves · Record holders).
8. **💬 Ask Gaia** — grounded LLM assistant.

---

## Data layers

| Layer | Source | Type | Notes |
| :--- | :--- | :--- | :--- |
| **Current temperature** | Open-Meteo current conditions | Live (model, ~15 min) | Exact point; shows "feels like" and local as-of time |
| **Temperature anomaly** | Open-Meteo ERA5 archive | Derived | Last 7 days of daily-mean temperature minus the 1991–2020 mean for the same calendar days. Baselines cached per location on disk |
| **Temperature History** | Open-Meteo ERA5 archive | Archive | 7-day mean around today's date in fixed reference years |
| **Monthly chart** | Open-Meteo ERA5 archive | Archive | Monthly mean temperature and rainfall totals |
| **Rainfall card** | Open-Meteo ERA5 archive | Archive | Month-to-date total, with "to <date>" |
| **Rain probability** | Open-Meteo forecast | Forecast (NWP) | Next 24 h hourly + 7-day daily maximum; nulls stay blank |
| **Air quality** | WAQI → OpenAQ v3 → Copernicus CAMS | Live, then model | WAQI station ≤50 km and <24 h; else OpenAQ ≤25 km; else CAMS model (badged EST). The source is always named |
| **CO₂** | NOAA GML | Live (monthly) | Global monthly mean |
| **NDVI** | NASA MODIS MOD13Q1 (ORNL DAAC) | Live (16-day) | Latest available composite |
| **Wildfires** | NASA FIRMS | Live | |
| **Satellite imagery** | NASA GIBS | Live tiles | |
| **Weather / AQI forecasts** | Open-Meteo | Forecast (NWP) | Not a custom-trained model |
| **Wildfire-risk score** | Derived formula | Derived | Uses the same current reading as the Insight card + NDVI |
| **Health Index (SHI)** | Derived formula | Derived | Shows "--" when no real AQI exists; the AQI source is named |
| **What-if simulator** | Real data + cited coefficients | Modelled | Every output labelled measured / estimated / modeled |
| **Place search** | Cesium Ion → Nominatim; Open-Meteo GeoNames for suggestions | Live | Enter resolves exactly what was typed; same-name places are listed, never auto-picked |
| **Active / previous hazards** | GDACS + USGS | Live | "Active" only if GDACS marks the event current and its episode end date is recent; USGS events (instantaneous) are never active. Cross-source duplicates linked, impacts never summed |
| **Historical Deadliest / Records** | NOAA NCEI (earthquakes, tsunamis, eruptions) + USGS + verified baseline | Live + curated | Last-good snapshot cached; ranges and every source's figure shown; overlaps flagged (≈); possible duplicate records flagged; events under a year old held for review |
| **Heatwaves** | Peer-reviewed studies (baseline) | Estimates | Five entries, each labelled excess or modelled heat-attributable deaths, with study and uncertainty |
| **Ask Gaia** | OpenAI-compatible LLM + this backend's endpoints | Grounded LLM | Requires `GAIA_LLM_API_KEY` |
| **Citizen reports** | SQLite | User input | |
| **Atmospheric visual effects** | OpenWeatherMap | Live if keyed | Without the key, runs on a labelled placeholder |

The verified baseline (`backend/data/historical_baseline.json`) holds 22 entries, each with source URLs and a verification date: floods and cyclones outside NCEI's scope, WMO-adjudicated records, casualty-range overlays for disputed NCEI events (e.g. Haiti 2010, Tangshan 1976), Lituya Bay's run-up record and five heatwave summers.

---

## Removed or deferred on purpose

- **Globe temperature heatmap** — removed (Oct 2026); a meaningful anomaly map needs a dense grid far beyond the free API tier. Code kept but switched off (`HEATMAP_ENABLED = False`).
- **Costliest-disaster record** — no open, authoritative global dataset.
- **Droughts, famines, epidemics** — outside Historical Extremes; deaths not cleanly attributable to the hazard.
- **EM-DAT** — licence forbids online redistribution; referenced only.
- **ReliefWeb** — awaiting an approved app name.

---

## Known gaps

- No authentication and no CI pipeline (the 101 offline tests run manually).
- Open-Meteo free tier (10,000 calls/day, 600/min) limits heavy use; limits surface as "unavailable", never as guessed values.
- Historical floods, cyclones and heatwaves come from a small curated baseline, so those hazards are incomplete; heatwave studies are mostly European.
- Global Health Index covers ~90 countries (those with a capital in `country_coords.py`).
- Basic mobile layout only; no dedicated accessibility pass yet.
- Disasters Phase 2 not built: search integration, nearby events on the Insight card, a Gaia disasters tool, Copernicus flood extents.

---

*Update this file in the same change as any feature that is added, removed or disabled.*
