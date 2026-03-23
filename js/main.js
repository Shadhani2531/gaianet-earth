document.addEventListener('DOMContentLoaded', async () => {
    // Initialize Globe
    window.globe = new GlobeManager();

    // Trigger default state
    setTimeout(() => {
        // Initial visual state
        console.log("Triggering initial analytics for India...");
        globe.loadLocationAnalytics(CONFIG.DEFAULT_COORDINATES.lat, CONFIG.DEFAULT_COORDINATES.lon);
    }, 2000);
});
