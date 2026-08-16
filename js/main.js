document.addEventListener('DOMContentLoaded', async () => {
    // Fetch the Cesium Ion token from the backend BEFORE constructing
    // GlobeManager, which reads CONFIG.CESIUM_ION_TOKEN synchronously in
    // its constructor to set Cesium.Ion.defaultAccessToken. See
    // config.js's loadRuntimeConfig() doc comment for why this isn't
    // just hardcoded here anymore.
    await CONFIG.loadRuntimeConfig();

    // Initialize Globe
    window.globeManager = new GlobeManager();
    window.ui = new UIManager();

    // Trigger default state
    setTimeout(() => {
        // Initial visual state
        console.log("Triggering initial analytics for India...");
        globeManager.loadLocationAnalytics(CONFIG.DEFAULT_COORDINATES.lat, CONFIG.DEFAULT_COORDINATES.lon);
    }, 2000);
});
