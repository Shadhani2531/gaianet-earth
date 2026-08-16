const CONFIG = {
    // Auto-detects the backend's origin instead of a hardcoded host:port.
    // main.py serves this frontend from the same FastAPI app it's calling
    // (StaticFiles mounted at "/"), so they're always same-origin — this
    // means the app keeps working unchanged on a LAN IP, a different port,
    // or a real domain later, instead of breaking the moment it's not on
    // localhost:8000. Falls back to localhost:8000 only if opened directly
    // via file:// (window.location.origin would be "null" or "file://").
    API_BASE_URL: (window.location.origin && window.location.origin !== "null")
        ? window.location.origin
        : "http://localhost:8000",

    // Cesium Ion token — powers the search geocoder (Tab-wide) and base
    // imagery. This is NOT hardcoded here on purpose: a real Cesium Ion
    // token used to be committed directly in this file, which meant
    // anyone browsing the public repo could lift it and burn the
    // developer's own Ion quota. Cesium Ion tokens are inherently a
    // client-side credential (Cesium needs it in the browser to fetch
    // tiles), so the real mitigations are (1) never let it sit in git
    // history, and (2) restrict it to specific referrer domains in the
    // Ion dashboard (https://ion.cesium.com/tokens). This app now keeps
    // the token in backend/.env (CESIUM_ION_TOKEN, gitignored) and the
    // frontend fetches it once from GET /api/config at startup — see
    // main.js's bootstrap() and CONFIG.loadRuntimeConfig() below.
    // If /api/config can't be reached or no token is configured server
    // side, the globe still loads (Cesium's own default imagery), just
    // without Ion-specific search/imagery — never a hard crash.
    CESIUM_ION_TOKEN: null,

    // Fetches the one setting (the Cesium Ion token) that has to come
    // from the server rather than being safe to ship in this static
    // file. Called once, before GlobeManager is constructed — see
    // main.js. Never throws: a missing/unreachable backend just means
    // CESIUM_ION_TOKEN stays null and Cesium falls back to its own
    // default (non-Ion) imagery.
    async loadRuntimeConfig() {
        try {
            const res = await fetch(`${this.API_BASE_URL}/api/config`);
            if (!res.ok) return;
            const data = await res.json();
            if (data && data.cesium_ion_token) {
                this.CESIUM_ION_TOKEN = data.cesium_ion_token;
            }
        } catch (e) {
            console.warn("Could not load runtime config from backend (Cesium Ion features will be limited):", e);
        }
    },

    // Initial camera view on load. This is the ONLY place this should be
    // defined — everything else reads from CONFIG.DEFAULT_COORDINATES
    // rather than repeating these numbers.
    DEFAULT_COORDINATES: {
        lat: 20.5937,
        lon: 78.9629,
        height: 5000000 // meters above India
    }
};
