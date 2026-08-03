/**
 * AppState — single source of truth for cross-cutting UI state.
 *
 * Why this exists: before this file, the same pieces of state were being
 * tracked in multiple places that could drift out of sync with each other:
 *   - "what tab is active" was read via document.body.getAttribute(
 *     'data-active-tab') from 8 different call sites across ui.js/globe.js
 *   - "what location is selected" was tracked TWICE — once as
 *     GlobeManager.currentLat/currentLon, once as UIManager.selectedLat/
 *     selectedLon/selectedIsTropical — synced only by a custom event, with
 *     one spot reaching directly into GlobeManager's internals to patch it
 *   - "which layers are on" only existed as checkbox.checked in the DOM,
 *     with no single place other code (or future AI features) could ask
 *     "what's currently visible on the globe right now?"
 *
 * This doesn't replace how the app renders (Cesium data sources, chart
 * rendering, panel show/hide logic all stay exactly as they were) — it
 * replaces HOW DIFFERENT PARTS OF THE APP FIND OUT about state, so there's
 * one place to read from and one place mutations happen, instead of the
 * same fact being copied and re-synced by hand in several places.
 *
 * Usage:
 *   AppState.setActiveTab('insight');
 *   AppState.activeTab;                          // read
 *   AppState.setLayerActive('layer-wildfires', true);
 *   AppState.isLayerActive('layer-wildfires');    // read
 *   AppState.setSelectedLocation(lat, lon);
 *   AppState.selectedLocation;                    // { lat, lon, isTropical } | null
 *   AppState.setRotating(true);
 *   AppState.subscribe((state) => { ... });       // re-run on every change
 */
class AppStateManager {
    constructor() {
        // Starts null (not 'earth') so the very first setActiveTab('earth')
        // call on page load — which sets the same value 'earth' will end up
        // being — isn't treated as a no-op by the equality guard below and
        // skipped. Without this, the DOM attribute and initial subscriber
        // notification would silently never fire.
        this.activeTab = null;
        this.activeLayers = new Set();
        this.selectedLocation = null; // { lat, lon, isTropical }
        this.isRotating = false;

        this._subscribers = [];
    }

    // --- Reads -------------------------------------------------------

    isLayerActive(layerId) {
        return this.activeLayers.has(layerId);
    }

    getSnapshot() {
        return {
            activeTab: this.activeTab,
            activeLayers: new Set(this.activeLayers),
            selectedLocation: this.selectedLocation,
            isRotating: this.isRotating,
        };
    }

    // --- Writes --------------------------------------------------------
    // Every setter updates the one internal copy of that fact, then fires
    // a single consolidated 'stateChanged' event carrying the full snapshot
    // — so anything that cares can subscribe once instead of listening for
    // several differently-named custom events.

    setActiveTab(tabName) {
        if (this.activeTab === tabName) return;
        this.activeTab = tabName;
        // Kept in sync for CSS that targets body[data-active-tab="..."] —
        // this is now a read-only reflection of AppState for styling
        // purposes, not a second source of truth for application logic.
        document.body.setAttribute('data-active-tab', tabName);
        this._notify();
    }

    setLayerActive(layerId, active) {
        const wasActive = this.activeLayers.has(layerId);
        if (wasActive === active) return;

        if (active) this.activeLayers.add(layerId);
        else this.activeLayers.delete(layerId);
        this._notify();
    }

    setSelectedLocation(lat, lon) {
        this.selectedLocation = {
            lat,
            lon,
            // Tropics of Cancer/Capricorn, ±23.5° — same rule used
            // throughout the app for biome auto-detection.
            isTropical: Math.abs(lat) <= 23.5,
        };
        this._notify();
    }

    setRotating(isRotating) {
        if (this.isRotating === isRotating) return;
        this.isRotating = isRotating;
        this._notify();
    }

    // --- Subscriptions ---------------------------------------------------

    subscribe(callback) {
        this._subscribers.push(callback);
        return () => {
            this._subscribers = this._subscribers.filter(cb => cb !== callback);
        };
    }

    _notify() {
        const snapshot = this.getSnapshot();
        this._subscribers.forEach(cb => cb(snapshot));
        document.dispatchEvent(new CustomEvent('stateChanged', { detail: snapshot }));
    }
}

const AppState = new AppStateManager();
