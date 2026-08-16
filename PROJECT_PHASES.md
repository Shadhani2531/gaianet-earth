# GaiaNet Earth - Project Phases Status

This document tracks feature-level progress. It's kept in sync with `PROJECT_STATUS.md` (the authoritative current-state doc) rather than duplicating its data table — this file is the checklist view, that one is the detail view.

---

## Current Navigation (5 tabs live; 1 disabled)

### 🌍 Tab: Immersive Earth
- [x] Core Planet Rendering (CesiumJS)
- [x] Real-time Fire Points (NASA FIRMS)
- [x] Auto-rotating cinematic default view
- [ ] Dynamic Atmosphere (night-lights, cloud layers) — not started

### 📍 Tab: Location Insight
- [x] Coordinate Targeting (click anywhere on globe, or search)
- [x] Real Environmental Stats (climate, AQI, CO₂, NDVI)
- [x] Dynamic Charts
- [x] Localized Risk Score (SHI, disclosed formula)

### ⏳ Historical Timeline / "Temporal Engine" — **DISABLED, not a live tab**
- [x] Timeline UI component and slider logic exist in `js/ui.js` (`case 'temporal':`)
- [x] Historical imagery date range plumbing exists
- [ ] **Not reachable from navigation** — removed from `index.html`'s tab dock because the imagery-layer state didn't settle correctly on tab entry (see the comment directly above the nav markup in `index.html`). This needs a proper state-machine fix, not another patch, before it's re-added to the visible nav. Do not describe this as shipped until it's actually back in the tab bar and has been manually verified to load historical imagery correctly on every entry.

### 🧠 Tab: Prediction / Forecast Lab
- [x] Real multi-day weather + AQI forecasts (Open-Meteo NWP — not a custom-trained model, see `PROJECT_OVERVIEW.md` §4)
- [x] Rule-based wildfire-risk score (documented formula, not ML — see `wildfire_risk.py`)
- [x] Cited "what-if" scenario simulator (deforestation/emissions, real coefficients)
- [ ] Probabilistic heatmaps (drought/flood chance) — not started
- [ ] A genuinely trained ML model for any of the above — intentionally not built; would require real historical training data this project doesn't have. See `PROJECT_OVERVIEW.md` §4 for why this isn't on the roadmap as a near-term item.

### 🚀 Tab: Community Reports
- [x] Right-click citizen incident reporting
- [x] Satellite (NASA FIRMS) cross-confirmation for fire-type reports
- [x] SQLite persistence

### 🌐 Tab: Global Health Index
- [x] Country-level composite SHI (real OpenAQ + Open-Meteo + MODIS)
- [x] Per-country transparency on which real components contributed
- [ ] Full country coverage — currently ~90 countries with a capital-coordinate reference; the rest get an AQI-only score or no score

---

## Strategic Recommendations & Add-ons (not yet built — genuine roadmap, not shipped claims)

### 1. Trust & Transparency (highest priority — see full audit for rationale)
- Surface the `data_source`/`confidence` fields the backend already returns as visible UI badges — this is currently computed end-to-end but stops at the API response.
- Add a visible "simulated" indicator when the Atmospheric Sync weather effect is running on its deterministic mock (no `OPENWEATHERMAP_API_KEY` configured).

### 2. Historical Timeline Rebuild
- Fix the imagery-layer state bug and re-enable the tab (see above).

### 3. Predictive Intelligence (real, not fabricated)
- If/when a historical per-region time-series store exists, evaluate a real regional forecasting model as a *complement* to the existing Open-Meteo forecast — never as a "trained model" claim without actual training data.
- Anomaly detection on already-fetched real historical series (statistically simple, e.g. z-score/STL — doesn't require new data).

### 4. User Experience & Collaboration
- Minimum-viable responsive/mobile layout (currently effectively desktop-only).
- Basic accessibility pass (keyboard navigation, ARIA labeling).
- "Save Location" monitoring bookmarks.
- Shareable snapshot URLs (camera position + active layers).

### 5. Data Depth & Export
- Broaden `country_coords.py` coverage.
- ESA Sentinel / Copernicus CAMS as additional real data sources.
- Raw GeoJSON/CSV export.

---
*This file reflects the current `main` branch. Update it in the same PR as any code change that adds/removes/disables a feature — the previous version of this document described the Temporal tab as shipped for months after it was actually disabled, which is exactly the kind of drift this note is here to prevent.*
