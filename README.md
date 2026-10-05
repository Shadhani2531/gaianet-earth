# GaiaNet Earth (v2.2.0)

**GaiaNet Earth** is a 3D environmental-intelligence dashboard: a CesiumJS globe that brings together real, live Earth data — current conditions, air quality, vegetation, wildfires, natural hazards and historical disasters — with a cited "what-if" scenario tool and a grounded AI assistant.

It is an academic/portfolio project, not an official monitoring or warning system. Its defining rule: **never present a fabricated number as if it were measured, and always say where a number comes from and how certain it is.** See [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for exactly what is live, derived or estimated.

## The eight tabs

| Tab | What it does |
|---|---|
| 🌍 **Immersive Earth** | 3D globe with live NASA satellite imagery |
| 🛰️ **Climate Insight** | Click or search any place: live temperature (+ anomaly vs 1991–2020), air quality, CO₂, rainfall, rain probability, vegetation (NDVI), history charts |
| 🕐 **Historical Timeline** | NASA satellite snapshots from 2000 to today, with side-by-side compare |
| 🧠 **Forecast Lab** | 7-day weather and 5-day air-quality forecasts (with dates), wildfire-risk score, what-if simulator |
| 📢 **Community Reports** | Citizen incident reports, cross-checked against NASA FIRMS fire detections |
| 🌐 **Global Health Index** | Country-level composite Sustainability Health Index |
| ⚠️ **Disasters & Hazards** | **Active now** and **Previous** events (GDACS + USGS), plus **Historical Extremes**: deadliest disasters, heatwaves and record holders with sourced casualty ranges |
| 💬 **Ask Gaia** | LLM assistant that answers only from this backend's own real data |

## Where the data comes from

- **Live:** Open-Meteo (current conditions, forecasts, ERA5 archive), WAQI / OpenAQ / CAMS (air quality), NOAA GML (CO₂), NASA FIRMS (fires), NASA GIBS (imagery), NASA MODIS via ORNL DAAC (NDVI), GDACS and USGS (current hazards), NOAA NCEI (historical earthquakes, tsunamis, eruptions)
- **Verified baseline:** a small, sourced file of historical events no live API covers (major floods and cyclones, WMO-adjudicated records, peer-reviewed heatwave mortality) — `backend/data/historical_baseline.json`
- **Derived, with disclosed methods:** temperature anomaly, Sustainability Health Index, wildfire-risk score, what-if projections
- **No trained ML model** is used in any live feature — see [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) §4 for why

## Quick start (Windows)

1. Install Python 3.11+.
2. Copy `backend/.env.example` to `backend/.env` and add your keys (all have free tiers — see [`RUN_INSTRUCTIONS.md`](RUN_INSTRUCTIONS.md)).
3. Double-click **`start_project.bat`**.
4. The dashboard opens at **http://localhost:8000** (API docs at `/docs`).

## Tests

```
cd backend
python -m unittest tests.test_temperature_anomaly tests.test_historical tests.test_disasters_rasuwa
```
101 tests, no network needed. They include a regression suite built from the real 26 Aug 2026 Rasuwa / Bhote Koshi (Nepal) disaster data.

## Documentation

- [`RUN_INSTRUCTIONS.md`](RUN_INSTRUCTIONS.md) — setup, keys, troubleshooting, API limits
- [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) — purpose, architecture, design decisions
- [`PROJECT_STATUS.md`](PROJECT_STATUS.md) — every data layer: source, status, caveats
- [`PROJECT_PHASES.md`](PROJECT_PHASES.md) — feature checklist and roadmap
- [`EXTENSION_INTEGRATION.md`](EXTENSION_INTEGRATION.md) — companion Chrome extension

> Disaster information is shown for awareness only. It is **not an official warning system** — always follow national authorities.
