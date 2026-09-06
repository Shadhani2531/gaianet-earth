document.addEventListener('DOMContentLoaded', async () => {
    // Fetch the Cesium Ion token from the backend BEFORE constructing
    // GlobeManager, which reads CONFIG.CESIUM_ION_TOKEN synchronously in
    // its constructor to set Cesium.Ion.defaultAccessToken. See
    // config.js's loadRuntimeConfig() doc comment for why this isn't
    // just hardcoded here anymore.
    await CONFIG.loadRuntimeConfig();

    // Initialize Globe
    window.globeManager = new GlobeManager();
    window.snapshotViewer = new SnapshotViewer();
    // NOTE: previously `window.ui = new UIManager();` here — but ui.js
    // ALREADY constructs the one canonical UIManager instance at its own
    // bottom (`const ui = new UIManager();`), which runs earlier (ui.js is
    // a normal blocking script, so it executes during initial HTML parse,
    // well before this DOMContentLoaded callback fires). Constructing a
    // SECOND instance here made Chart.js throw "Canvas is already in use"
    // for every chart (tempChart, precipChart, tempHistoryChart,
    // ndviHistoryChart, aqiForecastChart), since those canvases were
    // already claimed by the first instance. That uncaught exception then
    // silently skipped everything below it in this callback — including
    // the default-view setTimeout — for as long as this bug existed.
    // window.ui now just points at the already-successful instance.
    window.ui = ui;

    // Trigger default state
    setTimeout(() => {
        // Initial visual state
        console.log("Triggering initial analytics for India...");
        globeManager.loadLocationAnalytics(CONFIG.DEFAULT_COORDINATES.lat, CONFIG.DEFAULT_COORDINATES.lon);
    }, 2000);
});
