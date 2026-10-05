# GaiaNet Earth — Run Instructions

One FastAPI server serves both the API and the frontend, so there is only one thing to start.

## Quick start (Windows)

Double-click **`start_project.bat`** in the project root. It:
1. creates `backend/venv` (first run only) and installs `backend/requirements.txt`;
2. starts the server in a new window;
3. opens **http://localhost:8000** in your browser.

## Manual start (any OS)

```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python main.py
```
Then open http://localhost:8000. Interactive API docs: http://localhost:8000/docs.

Docker alternative: `docker compose up --build` from the project root (uses `backend/.env`).

## API keys (`backend/.env`)

Copy `backend/.env.example` to `backend/.env`. **Never commit `.env`.**

| Variable | Used for | Without it |
|---|---|---|
| `WAQI_TOKEN` | Air quality from the nearest WAQI station | Falls back to OpenAQ, then the CAMS model (labelled EST) |
| `OPENAQ_API_KEY` | OpenAQ stations (AQI fallback, Global Health Index) | Fewer real station readings |
| `CESIUM_ION_TOKEN` | Globe imagery/terrain and place search (Enter key) | Search falls back to OpenStreetMap Nominatim |
| `GAIA_LLM_API_KEY` | Ask Gaia assistant | Gaia replies that it isn't configured |
| `GAIA_LLM_BASE_URL` | Any OpenAI-compatible endpoint (default `https://openrouter.ai/api/v1`) | Default used |
| `GAIA_LLM_MODEL` | Model name (default `openrouter/free`) | Default used |
| `OPENWEATHERMAP_API_KEY` | Atmospheric visual effects | Effects run on a labelled placeholder |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed origins — **replaces** the defaults, so include `http://localhost:8000` | Local defaults (`localhost:8000`, `:5500`) |

Open-Meteo, NOAA, NASA, GDACS and USGS need no key.

## Running the tests

```powershell
cd backend
python -m unittest tests.test_temperature_anomaly tests.test_historical tests.test_disasters_rasuwa
```
Expected: `Ran 101 tests ... OK`. No network access is needed.

## After updating any files

1. Stop every Python process: `taskkill /F /IM python.exe`
2. Start again with `start_project.bat`
3. Hard-refresh the browser: **Ctrl + Shift + R**

An old server process left running keeps serving old code — if a traceback's line numbers don't match the file, that is the cause.

## Free-tier API limits (Open-Meteo)

10,000 calls/day, 5,000/hour, 600/minute; a multi-location request counts once per location, and a request longer than two weeks counts as several calls.
- The Insight temperature anomaly costs about **31 calls the first time a place is checked**; its 1991–2020 baseline is then saved and reused.
- If the limit is reached, figures show as unavailable with a reason — never as a guessed value. Wait a minute (or until the next day) and retry.

## Local cache folders (safe to delete, never committed)

| Folder | Contents | If deleted |
|---|---|---|
| `backend/data/historical_cache/` | Last good copy of NOAA NCEI / USGS historical data | Re-downloaded on next Historical view (a few seconds) |
| `backend/data/anomaly_baseline_cache/` | One small file per location with its 1991–2020 baselines | Re-fetched when a place is next clicked (~31 calls) |
| `__pycache__/` folders | Python bytecode | Recreated automatically |

`backend/data/historical_baseline.json` is **not** a cache — it is the verified Historical Extremes data. Keep it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Changes not visible | Restart the server (see above) and hard-refresh |
| "Could not reach the backend" | The server window is closed or crashed — check it for errors |
| Port 8000 in use | `taskkill /F /IM python.exe`, then start again |
| Values show "n/a" / unavailable | Usually a free-tier rate limit; the reason is shown on hover or in the server log |
| Historical view slow the first time | It downloads NOAA's full catalogues once, then serves the saved copy |
