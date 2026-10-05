# Companion Chrome Extension

A Manifest V3 Chrome extension ("Autonomous Planetary Health OS", v0.1.0) that checks air quality and nearby fires in the background using this project's backend. Local development only — it talks to `http://localhost:8000`.

## Files

| File | Purpose |
|---|---|
| `extension/manifest.json` | MV3 manifest |
| `extension/background.js` | Service worker; checks on a timer via `chrome.alarms` |
| `extension/popup.html`, `popup.js` | Toolbar popup with a "Check now" button |
| `extension/sidepanel.html` | Side-panel placeholder |
| `extension/icons/` | Placeholder icons |

It uses one backend endpoint, **`/alerts/summary`** (`backend/services/alerts.py`), which reuses the existing NASA FIRMS and OpenAQ modules — no extra API keys or rate-limit cost.

## Setup

1. Start the backend (`start_project.bat`).
2. Check the endpoint in a browser:
   `http://localhost:8000/alerts/summary?lat=19.99&lon=73.78`
   You should get a small JSON object (e.g. `aqi_max`, `fire_count`).
3. Open `chrome://extensions`, enable **Developer mode**, click **Load unpacked** and select the `extension/` folder.
4. Click the extension icon and press **Check now**. In the extension's service-worker console you should see the request to `/alerts/summary` succeed.

If the browser blocks the request, set `CORS_ALLOWED_ORIGINS` in `backend/.env` and restart the backend. This **replaces** the default list, so include the dashboard's own origin too:
```
CORS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,chrome-extension://<your-extension-id>
```

## Limitations

- Works only while the local backend is running.
- `/alerts/summary` filters whatever the FIRMS/OpenAQ caches currently hold, so a first call after a restart may be slower or sparser.
- Icons and the side panel are placeholders.
