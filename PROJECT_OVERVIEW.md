# GaiaNet Earth: Environmental Decision-Support Dashboard

## 1. Project Vision
GaiaNet Earth is a single-page, portfolio-scale environmental intelligence dashboard: a CesiumJS globe combining several real, live data sources with a couple of genuinely differentiated features — a cited "what-if" climate scenario simulator and a grounded LLM assistant. It's built around one core discipline, applied consistently across the backend: **never present a fabricated number as if it were measured, and always say how confident a derived number actually is.**

It is *not* an autonomous monitoring system, a digital twin in the full simulation sense, or an AI-model-driven forecaster — see Section 4 below for exactly what "AI" does and doesn't mean in this codebase, and `PROJECT_STATUS.md` for the full real/estimated/derived breakdown per feature.

## 2. Core Objectives & Capabilities
- **Unified Earth View**: an interactive 3D globe (CesiumJS) layering several real environmental datasets — wildfires, air quality, vegetation, climate — into one view.
- **Point-Level Analysis**: click anywhere for real climate history, current AQI/temperature/CO₂, NDVI, and short-term forecasts at that exact location.
- **Sustainability Health Index (SHI)**: a disclosed, non-black-box composite score combining real air-quality, climate-stability, and vegetation components, at both a point and country level.
- **Cited Scenario Simulation**: a "what-if" tool that projects deforestation/emissions effects using real, individually cited climate-science coefficients applied to a location's real current data — not a trained model, and not guessed constants either.

## 3. The 5-Tab Structure (current)
1. **Immersive Earth** — 3D globe with live satellite imagery and auto-rotate.
2. **Location Insight** — Point-specific analytics: real-time AQI, temperature, CO₂, NDVI, forecasts.
3. **Prediction / Forecast Lab** — Real multi-day forecasts, the wildfire-risk formula, and the what-if simulator.
4. **Community Reports** — Citizen incident reporting, cross-checked against real satellite wildfire data.
5. **Global Health Index** — Country-level composite SHI.

*(A 6th tab, a historical-imagery time slider, existed in an earlier version and is currently disabled pending a rebuild — see `PROJECT_STATUS.md` for the specifics and why it's not counted above.)*

## 4. What "AI" Actually Means Here
This section exists because earlier drafts of this document overstated it — worth saying plainly:

- **No trained forecasting model (LSTM/ARIMA) is used.** `backend/services/forecast.py` wraps Open-Meteo's own real numerical-weather-prediction output. That's a deliberate choice: this backend has no historical per-region time-series store to train on, and fabricating a "trained model" on top of borrowed/synthetic data would violate the project's own honesty principle. If that store gets built later, a real regional model could *complement* this, not replace working real data with something weaker.
- **No trained wildfire classifier (Random Forest/XGBoost) is used.** `backend/services/wildfire_risk.py` is a transparent, documented, weighted formula over real temperature/humidity/wind/NDVI. Training a real classifier requires labeled historical fire-outcome data this project doesn't have; a fabricated "trained model" would misrepresent both the training process and its accuracy.
- **What genuinely is "AI":** "Ask Gaia," a tool-calling LLM assistant that is only allowed to answer factual questions by calling this backend's own real endpoints — it cannot guess a number. This is the one place an LLM is used in the live product, and it's grounded by design.
- **The scenario simulator is not AI at all** — it's real data plus cited published coefficients, and it says so explicitly in its own confidence labels (`measured` / `estimated` / `modeled`).

## 5. System Architecture & Real-World Data Integration
A single FastAPI backend (`backend/main.py`) serving both the API and the static frontend (no separate frontend server needed in the default run mode), backed by small per-feature service modules that each call a real external API with an in-process TTL cache and an honestly-labeled fallback. No background workers, no message queue, no persistent cache beyond SQLite for citizen reports — this is a synchronous, request-driven architecture appropriate for its current scale, not yet a production ingestion pipeline.

### Data Layer Status
See `PROJECT_STATUS.md` for the current, maintained version of this table — kept in one place to avoid the two documents drifting apart again.

## 6. Development Roadmap
- **Phase 1 – Visualization**: ✅ Done. 3D globe, 5-tab UI, Docker support.
- **Phase 2 – Data Layers**: ✅ Done. Real wildfire, air-quality, climate, and vegetation integrations.
- **Phase 3 – Simulation & Forecasting**: ✅ Done. Cited scenario engine, real Open-Meteo forecasts, rule-based wildfire risk, grounded Ask Gaia assistant.
- **Phase 4 – Polish & Trust**: 🚧 In progress. Surfacing data-provenance badges in the UI (the backend already computes them), mobile/responsive layout, accessibility pass, automated tests.
- **Phase 5 – Historical Timeline rebuild**: 📋 Planned, not started. Re-enable the disabled Temporal tab with a properly fixed imagery-layer state machine.

## 7. Key Strengths
- **Authoritative, real data**: NASA, NOAA, Open-Meteo, OpenAQ, MODIS — not placeholder feeds.
- **Disciplined honesty**: every derived number is labeled with its actual confidence level and, where relevant, its citation — genuinely rare at this project's scale.
- **Grounded AI, not a hallucination risk**: Ask Gaia can only report real numbers it actually looked up.
