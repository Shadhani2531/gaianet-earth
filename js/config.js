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
    // imagery. RISK: this is a real credential with an expiry; if it stops
    // working, search will fail (see the auth-error handling added in
    // globe.js's searchLocation, which now surfaces this specifically
    // instead of a misleading "Location Not Found"). Get a new one at
    // https://ion.cesium.com/tokens if this ever needs rotating.
    CESIUM_ION_TOKEN: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI1OTY4MzE3Ny1jMjEwLTRhZWYtYTdjYi1hMDczOTViMzczMmMiLCJpZCI6NDAzMDk0LCJpYXQiOjE3NzM0MDgwNzd9.93bdBfm0RJz_h2-ruwPtjmfgjnTiq_Ugn-8thi_qon0",

    // Initial camera view on load. This is the ONLY place this should be
    // defined — everything else reads from CONFIG.DEFAULT_COORDINATES
    // rather than repeating these numbers.
    DEFAULT_COORDINATES: {
        lat: 20.5937,
        lon: 78.9629,
        height: 5000000 // meters above India
    }
};
