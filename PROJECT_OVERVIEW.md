# GaiaNet Earth — Project Overview

## 1. Vision
GaiaNet Earth is a single-page environmental-intelligence dashboard built on a CesiumJS globe. It combines many real, live data sources with three differentiated features: a cited what-if scenario simulator, a grounded LLM assistant, and a Disasters & Hazards section that links live hazard feeds with sourced historical context.

The project is built around one discipline, applied everywhere: **never present a fabricated number as if it were measured; always state the source, the date and the uncertainty.**

## 2. Capabilities
- **Point analysis** — click or search any place for live temperature, the anomaly against its own 1991–2020 baseline, air quality, CO₂, rainfall, rain probability, NDVI and history charts.
- **Same-name place handling** — "Aurangabad" lists every match instead of silently picking one; Enter always resolves to exactly what was typed.
- **Forecasts** — 7-day weather, 5-day air quality and 7-day rain probability, each labelled with its date.
- **Hazards** — active and recent events from GDACS and USGS, linked across sources, with impacts shown side by side and never summed.
- **Historical context** — the deadliest disasters (since 1900 or all recorded history), heatwaves (estimated excess deaths) and record holders, each with ranges and sources.
- **Composite indices** — a disclosed Sustainability Health Index at point and country level.
- **What-if simulation** — deforestation/emissions projections using cited, published coefficients.

## 3. The eight tabs
1. **Immersive Earth** — globe with live NASA GIBS imagery.
2. **Climate Insight** — point analytics (see above).
3. **Historical Timeline** — NASA Worldview snapshots, 2000–present, with split compare.
4. **Forecast Lab** — forecasts, wildfire-risk score, what-if simulator.
5. **Community Reports** — citizen reports, cross-checked against NASA FIRMS.
6. **Global Health Index** — country-level composite SHI.
7. **Disasters & Hazards** — Active now · Previous · Historical Extremes.
8. **Ask Gaia** — grounded assistant.

## 4. What "AI" means here
- **No trained forecasting or classification model is used.** Forecasts are Open-Meteo's real numerical weather prediction; the wildfire-risk score is a documented formula. Training a model without real labelled history would misrepresent its accuracy.
- **Ask Gaia** is the one LLM feature. It must call this backend's own endpoints for every number. For ambiguous place names it lists the options rather than guessing, and it refuses near-spellings.
- **The scenario simulator is not AI** — it applies cited coefficients to real current data and labels every output `measured`, `estimated` or `modeled`.

## 5. Architecture
- **Backend:** one FastAPI app (`backend/main.py`) that also serves the static frontend. Each data source has its own module in `backend/services/`, with an in-memory TTL cache and an honestly labelled failure state.
- **Disk caches** for data that never changes: 1991–2020 temperature baselines per location, and last-good snapshots of NOAA NCEI / USGS historical catalogues.
- **Frontend:** vanilla JavaScript + CesiumJS (`js/`), one stylesheet (`css/style.css`).
- **Persistence:** SQLite (`backend/reports.db`) for citizen reports.
- **Tests:** `backend/tests/` (101 offline tests).

## 6. Data-honesty rules (as implemented)
- Every figure carries its source and an as-of date; live, archive, forecast, estimate and formula values are badged differently.
- Failures are shown as "unavailable" with a reason — never filled with a default value.
- Temperature: the **current** reading is the live model value at the exact point; the **anomaly** is the last 7 days of ERA5 daily-mean temperature minus the 1991–2020 mean for the same calendar days, from the same dataset on both sides.
- Hazards: "Active now" requires the source's own current status and end date, never just "happened recently"; earthquakes are never "active".
- Casualties: ranges and every source's figure are shown; overlapping ranks are flagged; preliminary figures (events under a year old) are never promoted to a record.
- Heatwaves are a separate category with explicit method labels (excess deaths vs modelled heat deaths), never mixed into the Deadliest ranking.

## 7. Notable design decisions
- **Temperature heatmap removed (Oct 2026).** A real anomaly map needs a dense grid, each cell with its own 30-year baseline — far beyond the free API tier. The 126-point version rendered as misleading discs, so the globe overlay was dropped; the Temperature toggle still drives the exact point anomaly and history.
- **Costliest-disaster record deferred.** No open, authoritative global loss dataset exists.
- **Droughts, famines and epidemics excluded** from Historical Extremes: their deaths cannot be cleanly attributed to the natural hazard.
- **EM-DAT not used.** Its licence forbids redistributing its data online; it is referenced, not embedded.
- **ReliefWeb not integrated yet.** Its API now requires a pre-approved app name; integration is planned once approval is obtained.

## 8. Roadmap
See [`PROJECT_PHASES.md`](PROJECT_PHASES.md).
