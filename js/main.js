document.addEventListener('DOMContentLoaded', async () => {
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
