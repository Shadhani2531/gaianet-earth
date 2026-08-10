# Planetary Health OS extension — integrated into GaiaNet backend

This zip is your full `gaianet-earth-backup` project with the extension's
Phase 0 backend support added directly into it, rather than as a separate
service. Extract it over your existing project folder (or use it as the
new working copy — see "What to do" below).

## What's new / changed, file by file

**New files:**
- `extension/manifest.json` — MV3 manifest
- `extension/background.js` — alarm-driven monitoring service worker
- `extension/popup.html` + `extension/popup.js` — toolbar popup
- `extension/sidepanel.html` — side panel stub (map/chat land here in Phase 2-3)
- `extension/icons/*.png` — placeholder icons (swap for real branding whenever)
- `backend/services/alerts.py` — new service powering the extension's
  `/alerts/summary` endpoint. Reuses your existing `nasa_firms` and
  `openaq_client` modules — no new upstream API integration, no new
  rate-limit surface.

**Changed files (from earlier in this conversation, all already applied):**
- `backend/main.py` — added the `/alerts/summary` route, imports `alerts`
- `backend/services/openaq_client.py` — added a public `has_api_key()`
  wrapper (was private `_has_api_key()`) so `alerts.py` doesn't reach into
  another module's internals
- `js/api.js` — fixed the `getWeather()` endpoint-path bug, added error-kind
  tracking (network vs. empty-response)
- `js/globe.js` — accurate error messaging using the above
- `docker-compose.yml` + `backend/Dockerfile` — replaced the orphaned
  Postgres service with a working single-container setup
- `backend/.env.example` — real-looking key values scrubbed to placeholders

**Not included:** `backend/.env` (your real keys — keep your own local copy,
gitignored as before), `.git/` history, and cache/build artifacts.

## What to do

1. Extract this zip.
2. Copy your own `backend/.env` (with your real WAQI/OpenAQ/OpenWeatherMap
   keys) into `backend/`. It's not in this zip on purpose.
3. Start the backend as usual (`start_project.bat` or
   `uvicorn main:app --reload` from `backend/`). Confirm the new route is
   live: open `http://localhost:8000/alerts/summary?lat=19.99&lon=73.78`
   in a browser — you should get back a small JSON object with `aqi_max`,
   `fire_count`, etc.
4. Load the extension: `chrome://extensions` → enable Developer Mode →
   "Load unpacked" → select the `extension/` folder.
5. Open the extension's service worker console (from the extension card on
   `chrome://extensions`) and click "Check now" in the popup — you should
   see the fetch to `http://localhost:8000/alerts/summary` succeed.

## Next integration step (Phase 1, not yet built)

`alerts.py` currently does on-demand distance filtering over whatever the
existing FIRMS/OpenAQ caches already hold — no new scheduled ingestion, no
new database table yet. That's intentionally minimal so Phase 0 could ship
today. Phase 1 (per the roadmap) adds PostGIS-backed persistent storage and
Celery-scheduled ingestion so `/alerts/summary` stops depending on another
endpoint having been called recently to warm the cache.
