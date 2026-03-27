class WeatherManager {
    constructor(viewer) {
        this.viewer = viewer;
        this.currentStage = null;
        this.initWeatherListener();
    }

    initWeatherListener() {
        // ASE Logic: Listen for camera movement to sync atmospheric state
        this.viewer.camera.moveEnd.addEventListener(async () => {
            const center = this.getGlobeCenter();
            if (center) {
                const weather = await this.fetchWeather(center.lat, center.lon);
                if (weather) {
                    this.applyAtmosphericState(weather);
                }
            }
        });
    }

    getGlobeCenter() {
        const center = this.viewer.camera.pickEllipsoid(
            new Cesium.Cartesian2(
                this.viewer.canvas.clientWidth / 2,
                this.viewer.canvas.clientHeight / 2
            )
        );
        if (!center) return null;
        const cartographic = Cesium.Cartographic.fromCartesian(center);
        return {
            lat: Cesium.Math.toDegrees(cartographic.latitude),
            lon: Cesium.Math.toDegrees(cartographic.longitude)
        };
    }

    async fetchWeather(lat, lon) {
        try {
            const response = await fetch(`${CONFIG.API_BASE_URL}/api/weather?lat=${lat}&lon=${lon}`);
            return await response.json();
        } catch (e) {
            console.error("ASE Weather Sync Failed:", e);
            return null;
        }
    }

    applyAtmosphericState(weather) {
        console.log(`ASE Sync: ${weather.main} at current location.`);
        
        // 1. Scene Visuals (Rain/Snow)
        this.clearWeatherEffects();
        
        if (weather.main === 'Rain') {
            this.currentStage = this.viewer.scene.postProcessStages.add(Cesium.PostProcessStageLibrary.createRainStage());
        } else if (weather.main === 'Snow') {
            this.currentStage = this.viewer.scene.postProcessStages.add(Cesium.PostProcessStageLibrary.createSnowStage());
        }

        // 2. Sky Atmosphere Sync
        // Dynamically adjust brightness based on cloud cover to match real-world visibility
        const cloudFactor = weather.clouds / 100;
        this.viewer.scene.skyAtmosphere.brightnessShift = -0.3 * cloudFactor;
        
        // Dispatch event for UI
        document.dispatchEvent(new CustomEvent('weatherSynced', { detail: weather }));
    }

    clearWeatherEffects() {
        if (this.currentStage) {
            this.viewer.scene.postProcessStages.remove(this.currentStage);
            this.currentStage = null;
        }
    }
}
