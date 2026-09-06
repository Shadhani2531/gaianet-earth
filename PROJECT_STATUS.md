# GaiaNet Earth (v2.1.0) — Project Status

This document is meant to be read alongside the actual code, not instead of it — it's an honest status snapshot, updated to match what's currently in `main` rather than what was originally planned.

---

## Current Tab Structure (7 tabs, live in `index.html`)

1. **🌍 Earth** — Immersive CesiumJS globe with live NASA GIBS satellite imagery and auto-rotate.
2. **📍 Insight** — Click anywhere on the globe (or search a place) for real climate/AQI/CO₂/NDVI analytics at that point.
3. **🕐 Historical Timeline** — Scrub or play through 2000–present via flat NASA GIBS Snapshot API images (`js/snapshot-viewer.js`), with a split-compare mode and four curated preset locations (Amazon, Aral Sea, Dubai, Greenland). See below for why this isn't Cesium imagery layers anymore.
4. **🧠 Prediction / Forecast Lab** — Real multi-day weather + AQI forecasts, the rule-based wildfire-risk score, and the "what-if" scenario simulator.
5. **📢 Reports** — Citizen incident reporting (select a location on the globe, then "Submit a Report" in the sidebar — no right-click gesture), cross-checked against real NASA FIRMS wildfire detections.
6. **🌐 Global Health Index** — Country-level composite Sustainability Health Index built from real OpenAQ + Open-Meteo + MODIS data at each country's capital.
7. **💬 Ask Gaia** — Grounded LLM chat assistant, in its own tab/right-panel like every other tab above. Used to be a floating button + small chat bubble parked outside the tab system entirely; moved in so it's reachable the same way as everything else instead of a separate corner widget.

### About the Historical Timeline / "4D Temporal Engine" tab
This used to drive live Cesium WMTS imagery layers (NASA GIBS tiles) directly on the 3D globe, swapping a new layer in on every date change. That caused visible glitching — tiles popping in and out, rendering instability — because every tab shares the *same* Cesium scene, so churning imagery layers on it destabilized rendering globally, not just on this tab. It's been rebuilt from scratch: `js/snapshot-viewer.js` now renders flat images from NASA's Worldview Snapshot API (`wvs.earthdata.nasa.gov/api/v1/snapshot`) in its own panel, and never touches the globe's imagery layers at all. The old approach (`toggleSatelliteView`, `updateTime`, `refreshImageryLayers`, `refreshNdviImagery`, `refreshSatelliteImagery`, `toggleSplitScreen`) has been removed from `js/globe.js` entirely rather than left as dead weight. Trade-off: this is a raw satellite snapshot per date, not a cloud-free composite the way Google's Timelapse tool is — some dates may show cloud cover, and the UI says so.

---

## Data Layer Status — what's actually live vs. estimated vs. not real-time

| Data Layer | Type | Source | Update Freq | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Wildfires** | Real-time | NASA FIRMS (MODIS 24h) | ~10 min cache | ✅ Live |
| **Satellite Imagery** | Real-time | NASA GIBS | Live tiles | ✅ Live |
| **Air Quality (point)** | Real-time, honest fallback | WAQI/AQICN | Live | ✅ Live when `WAQI_TOKEN` is set; falls back to a **labeled** estimate otherwise, never silently fabricated |
| **Air Quality (stations, global)** | Real-time, 1–6h cache | OpenAQ v3 | Live | ✅ Live, requires `OPENAQ_API_KEY` (free) |
| **CO₂ (global)** | Real, monthly | NOAA GML | Daily cache of a monthly figure | ✅ Live |
| **Vegetation / NDVI (point)** | Real, with honest fallback | NASA MODIS (MOD13Q1 via ORNL DAAC) | 16-day composite | ✅ Live where MODIS has coverage; a clearly labeled biome/season **estimate** elsewhere (ocean, persistent cloud, pre-2000 dates) |
| **Climate history & current conditions** | Real | Open-Meteo | Hourly cache | ✅ Live |
| **7-day weather forecast** | Real NWP forecast | Open-Meteo forecast model | Live | ✅ Live — this is Open-Meteo's own real weather-model output, **not** a custom-trained LSTM/ARIMA. See `backend/services/forecast.py`'s docstring for why that's a deliberate choice, not a shortcut. |
| **5-day AQI forecast** | Real, model-derived | Open-Meteo air-quality model | Live | ✅ Live, same caveat as above |
| **Wildfire Risk Score** | Derived (transparent formula) | Real temp/humidity/wind (Open-Meteo) + real/estimated NDVI | Live | ✅ A documented rule-based fire-danger index — **not** a trained Random Forest/XGBoost model. See `backend/services/wildfire_risk.py`'s docstring for the honest reason why. |
| **"What-If" Scenario Simulator** | Derived, cited | Real current data + published climate-science coefficients (PLOS ONE 2019, PNAS 2023, WRI 2021, EPA AQI breakpoints) | On demand | ✅ Every projected number carries a `measured`/`estimated`/`modeled` confidence tag and a citation — see `backend/services/scenario_engine.py` |
| **Composite SHI (point & global)** | Derived from real inputs | Real AQI (+ real climate/NDVI at country level) | Live / 6h cache | ✅ A disclosed formula, not a black-box score |
| **Atmospheric Sync (rain/snow visuals)** | Real *if configured*, else a labeled deterministic mock | OpenWeatherMap | Live | ⚠️ Without `OPENWEATHERMAP_API_KEY`, this silently runs on a deterministic (not random, but not real) placeholder — the API response does say `"status": "mock"`, but the UI doesn't yet surface that visually. Set the key for real weather-driven visuals. |
| **Ask Gaia (chat assistant)** | Grounded LLM | An OpenAI-compatible LLM + this backend's own real endpoints | Live | ✅ Requires `GAIA_LLM_API_KEY`; the assistant is instructed to call a real tool for every number rather than guess |
| **Ground Truth / Citizen Reports** | Real user input | SQLite, cross-checked against real NASA FIRMS for fire-type reports | Live | ✅ Live |

There is no trained machine-learning model wired into any live endpoint in this project today. An earlier ML prototype (`backend/ml/`, trained on synthetic data) was removed rather than kept as unused dead weight — see the git history if you need to reference it. If real historical outcome data (e.g., confirmed fire events) becomes available later, `wildfire_risk.py`'s docstring already lays out how a genuine trained classifier could replace the current formula.

---

## Known Gaps (honest list)

- No authentication, no automated test suite, no CI pipeline.
- In-process caching only (Python dicts with TTLs) — cache resets on every restart, not shared across multiple backend instances.
- `country_coords.py` covers roughly 90 countries; `/shi-global` only scores countries with a capital in that table.
- The frontend has a floor-level responsive/mobile layout (one `@media (max-width: 768px)` breakpoint covering the tab dock, side panels, insight card, and timeline strip via a "bottom sheet + bottom nav" pattern — see the comment above it in `css/style.css`) rather than a full dedicated mobile redesign. This previously only covered the old floating Ask Gaia widget; now that Gaia is a regular tab/right-panel, it's covered by the same general panel rules as everything else, with no separate override needed.
- Accessibility (keyboard navigation, ARIA labeling) has not had a dedicated pass yet.

---

*This file describes the current `main` branch. If something here looks wrong, the code is the source of truth — please open an issue or PR to fix whichever one is out of date.*
