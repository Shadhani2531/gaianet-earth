# GaiaNet Earth — Phases & Checklist

The checklist view of the project. Details per data layer live in [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

---

## Completed

### Phase 1 — Visualisation ✅
- [x] CesiumJS globe, live NASA GIBS imagery, auto-rotate
- [x] Tabbed single-page UI (8 tabs), Docker support

### Phase 2 — Real data layers ✅
- [x] Wildfires (NASA FIRMS), NDVI (MODIS), CO₂ (NOAA), climate (Open-Meteo)
- [x] Air quality chain: WAQI → OpenAQ → CAMS model, with the source named
- [x] Historical Timeline rebuilt on NASA Worldview snapshots (off-globe)

### Phase 3 — Forecasting & simulation ✅
- [x] 7-day weather and 5-day AQI forecasts (Open-Meteo NWP), with dates
- [x] Rule-based wildfire-risk score
- [x] Cited what-if scenario simulator
- [x] Ask Gaia, grounded in this backend's own endpoints

### Phase 4 — Accuracy & trust (seminar feedback round) ✅
- [x] Rain probability (next 24 h + 7 days)
- [x] Temperature matches weather apps: live current value + anomaly vs a real 1991–2020 baseline (not a formula)
- [x] One consistent temperature definition across all tabs (daily mean for history and anomaly)
- [x] Same-name place disambiguation; Enter never replaces the typed name; suggestions only on explicit selection
- [x] Ask Gaia lists ambiguous places instead of guessing
- [x] Source/date badges: LIVE, ARCHIVE, FORECAST, EST, FORMULA
- [x] Offline test suite (101 tests)

### Phase 5 — Disasters & Hazards ✅
- [x] Active now (source status + end dates) and Previous (7 / 30 days / custom)
- [x] GDACS + USGS with cross-source linking and audited de-duplication
- [x] Significant events by default; low-impact behind Filters; clustering; far-side markers hidden
- [x] Historical Extremes: Deadliest (since 1900 / all history), Heatwaves, Record holders
- [x] Casualty ranges with per-figure sources; ≈ for overlapping ranks; possible duplicates flagged; preliminary figures never promoted
- [x] Nepal 26 Aug 2026 (Rasuwa / Bhote Koshi) kept as an automated test case

---

## Next

### Disasters — Phase 2
- [ ] Search integration (e.g. "Nepal flood")
- [ ] "Nearby events" line on the Insight card
- [ ] Ask Gaia disasters tool
- [ ] Copernicus EMS flood extents (real mapped extent, not the analyst-drawn area)

### Disasters — Phase 3
- [ ] ReliefWeb reports (after app-name approval)

### Platform
- [ ] AR/VR model of Earth for Android devices (faculty request; AR preferred)
- [ ] Mobile layout and accessibility pass
- [ ] CI to run the test suite automatically
- [ ] Broader Global Health Index coverage

### Deliberately not planned
- Trained ML forecasting/classification without real labelled history
- Globe temperature heatmap on the free API tier
- Costliest-disaster record without an open authoritative dataset
- Drought/famine and epidemic rankings
