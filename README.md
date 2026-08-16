# GaiaNet Earth (v2.1.0)

**GaiaNet Earth** is a 3D environmental-intelligence dashboard: a CesiumJS globe overlaying real, live data (wildfires, air quality, vegetation, climate) plus a transparent "what-if" scenario tool and a grounded AI assistant. It's a portfolio/demo project, not a production monitoring platform — see `PROJECT_STATUS.md` for an honest list of what's real, what's a labeled estimate, and what's not built yet.

## What's actually real here
Every number this app shows carries a `data_source`/`confidence` label in the API response (see `PROJECT_STATUS.md`'s data table). The short version:
- **Real, live:** NASA FIRMS wildfires, NASA GIBS satellite imagery, NASA MODIS NDVI (via ORNL DAAC), Open-Meteo climate/weather/rainfall/forecasts, OpenAQ v3 air-quality stations, NOAA global CO₂
- **Derived from real data (not fabricated, not "AI"):** the composite Sustainability Health Index, the wildfire-risk score (a documented rule-based formula), and the "what-if" scenario engine (cited real climate-science coefficients — see `backend/services/scenario_engine.py`)
- **Not built yet:** any trained ML/forecasting model. `forecast.py` wraps Open-Meteo's own forecast (real NWP output); `wildfire_risk.py` is a transparent formula, not a Random Forest/XGBoost classifier — both explain why in their own docstrings

## Features
- Real-time NASA FIRMS wildfires + GIBS satellite imagery on a 3D Cesium globe
- Click anywhere to pull real climate/AQI/NDVI/forecast data for that point
- A cited "what-if" scenario simulator (deforestation / emissions impact)
- "Ask Gaia" — an LLM assistant that only answers using this backend's own real endpoints, never a guessed number
- Citizen incident reporting, cross-checked against real satellite wildfire detections
- A one-click Impact Report (printable/PDF)
- A companion Chrome extension for background AQI/wildfire alerts (local-dev only currently — see `EXTENSION_INTEGRATION.md`)

## Quick Start
1. Ensure Python is installed.
2. Copy `backend/.env.example` to `backend/.env` and fill in at least `WAQI_TOKEN` and `OPENAQ_API_KEY` (both have free tiers — see the comments in `.env.example` for what breaks without each one).
3. Double-click **`start_project.bat`** in the root folder (Windows) or follow `RUN_INSTRUCTIONS.md` for manual/other-OS steps.
4. The dashboard opens at `http://localhost:8000`.

For the full, current feature-by-feature status (what's live vs. estimated vs. not-yet-built), see **[PROJECT_STATUS.md](PROJECT_STATUS.md)**. For run details see **[RUN_INSTRUCTIONS.md](RUN_INSTRUCTIONS.md)**.
