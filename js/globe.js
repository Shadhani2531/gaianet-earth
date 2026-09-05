class GlobeManager {
    constructor() {
        if (CONFIG.CESIUM_ION_TOKEN) {
            Cesium.Ion.defaultAccessToken = CONFIG.CESIUM_ION_TOKEN;
        }

        this.viewer = new Cesium.Viewer('cesiumContainer', {
            terrain: Cesium.Terrain.fromWorldTerrain(),
            baseLayer: Cesium.ImageryLayer.fromProviderAsync(
                Cesium.createWorldImageryAsync({
                    style: Cesium.IonWorldImageryStyle.AERIAL_WITH_LABELS
                })
            ),
            baseLayerPicker: false,
            animation: false,
            timeline: false,
            homeButton: false,
            infoBox: false,
            selectionIndicator: false,
            navigationHelpButton: false,
            sceneModePicker: false,
            geocoder: false,
            fullscreenButton: false
            // Removed requestRenderMode to restore native smooth zooming/panning
        });

        // Disable the native browser context menu app-wide — previously
        // this only applied to the globe canvas, so right-clicking over any
        // UI panel (sidebar, reports feed, etc.) still showed the OS/browser
        // menu, which looks like a jarring, out-of-place white box against
        // this UI. Text inputs/textareas are excluded so copy/paste/select-all
        // still work the normal way where people expect them to.
        document.addEventListener('contextmenu', (e) => {
            const tag = e.target.tagName;
            if (tag !== 'INPUT' && tag !== 'TEXTAREA') {
                e.preventDefault();
            }
        });

        // Dark sky/space background for aesthetic
        this.viewer.scene.skyAtmosphere.hueShift = -0.5;
        this.viewer.scene.skyAtmosphere.saturationShift = 0.5;
        this.viewer.scene.skyAtmosphere.brightnessShift = -0.3;

        this.layers = {
            temperatureAnomalyImagery: null,
            co2: null,
            pollution: null,
            weather: null,
            vegetationImagery: null,
            wind: null,
            wildfires: [],
            sensors: null,
            reports: []
        };

        this.initCamera();
        this.initInteraction();
        this.listenForScenarios();
        this.loadUserReports(); // Load existing reports on startup

        // Canvas glyphs (glow dots, flame icons, wind arrows) are drawn
        // once per unique color/size and reused — with up to ~500
        // wildfires or ~100 stations on screen, regenerating a canvas
        // per entity per render would be wasteful. See
        // _getGlyphCanvas()/_createGlowDotCanvas()/etc. below.
        this._glyphCache = {};

        // Shared pulse animation for "urgent" point markers (severe/
        // extreme wildfires). A plain rAF loop rather than Cesium's own
        // clock.onTick — onTick's firing depends on the viewer's
        // shouldAnimate state, which isn't guaranteed on here, while a
        // manual loop is simple and predictable regardless of that
        // setting. No-ops (no wasted renders) when nothing is pulsing.
        this._pulsingBillboards = [];
        const pulseLoop = () => {
            if (this._pulsingBillboards.length) {
                const t = performance.now() / 450;
                this._pulsingBillboards.forEach((p) => {
                    if (!p.billboard) return;
                    p.billboard.scale = p.baseScale * (1 + 0.22 * Math.sin(t + p.phase));
                });
                this.viewer.scene.requestRender();
            }
            requestAnimationFrame(pulseLoop);
        };
        requestAnimationFrame(pulseLoop);

        // Atmospheric Synchronization Engine (ASE)
        this.weather = new WeatherManager(this.viewer);
        
        // Auto-rotation state
        this.isAutoRotating = false;
        this.lastTime = Date.now();
        
        document.addEventListener('minimalModeChanged', (e) => {
            this.isAutoRotating = e.detail.active;
            if (this.isAutoRotating) {
                this.startAutoRotation();
            }
        });

        // Tab 1 (Earth) is the cinematic, hands-off entry view: auto-rotate
        // starts the moment the tab becomes active, and any manual camera
        // movement (drag, zoom, tilt) — not just clicks — interrupts it.
        AppState.subscribe((state) => {
            if (state.activeTab === 'earth') {
                this.startAutoRotation();
            } else {
                this.stopAutoRotation();
            }
        });

        this.viewer.camera.moveStart.addEventListener(() => {
            if (this._programmaticFlight) return;
            if (AppState.activeTab === 'earth') {
                clearTimeout(this._resumeRotationTimeout);
                this.stopAutoRotation();
            }
        });

        // Resume the cinematic auto-rotate a short moment after the user
        // stops dragging/zooming/tilting — previously nothing ever
        // restarted it, so one manual nudge silently killed it forever.
        this.viewer.camera.moveEnd.addEventListener(() => {
            if (this._programmaticFlight) return;
            if (AppState.activeTab !== 'earth') return;

            clearTimeout(this._resumeRotationTimeout);
            this._resumeRotationTimeout = setTimeout(() => {
                if (AppState.activeTab === 'earth') {
                    this.startAutoRotation();
                }
            }, 2000);
        });

        // Listen for new reports submitted
        document.addEventListener('reportSubmitted', (e) => {
            this.addReportEntity(e.detail);
        });
    }

    async searchLocation(query) {
        const foundViaIon = await this._tryIonGeocode(query);
        if (foundViaIon) return true;

        // Fallback: free, key-free OpenStreetMap search. Runs whenever Ion's
        // geocoder throws OR simply returns zero results, so search doesn't
        // have a single point of failure tied to one paid service's token.
        return this.searchLocationViaNominatim(query);
    }

    async _tryIonGeocode(query) {
        try {
            const geocoder = new Cesium.IonGeocoderService();
            const results = await geocoder.geocode(query);

            if (results && results.length > 0) {
                this.flyToDestination(results[0].destination, results[0].displayName);
                return true;
            }
            return false;
        } catch (error) {
            console.error("Cesium Ion geocoding failed:", error);

            // Distinguish "the token/service failed" from "no results found"
            // — these need different messages. An expired/invalid Cesium Ion
            // token surfaces as a 401/403 here.
            const status = error?.statusCode || error?.response?.status;
            const message = (error?.message || "").toLowerCase();
            const looksLikeAuthFailure = status === 401 || status === 403
                || message.includes("unauthorized") || message.includes("token");

            if (looksLikeAuthFailure) {
                document.dispatchEvent(new CustomEvent('layerNotice', {
                    detail: { message: 'Cesium Ion search token may have expired — trying a backup search instead.' }
                }));
            }
            return false;
        }
    }

    async searchLocationViaNominatim(query) {
        try {
            const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=1`;
            const response = await fetch(url, { headers: { 'Accept': 'application/json' } });
            if (!response.ok) return false;

            const results = await response.json();
            if (!results || results.length === 0) return false;

            const { lat, lon, display_name } = results[0];
            // 500km altitude reads as "zoomed to city/region level," similar
            // to how Google Maps settles after a search — not a wide fit,
            // not a claustrophobic close-up.
            const destination = Cesium.Cartesian3.fromDegrees(parseFloat(lon), parseFloat(lat), 500000);
            this.flyToDestination(destination, display_name);
            return true;
        } catch (error) {
            console.error("Nominatim geocoding failed:", error);
            return false;
        }
    }

    flyToDestination(destination, name) {
        this.viewer.camera.flyTo({
            destination: destination,
            duration: 2.0,
            complete: () => {
                // Determine lat/lon from destination for analytics
                // flyTo destinations can be Cartesian3 or Rectangle
                let coords;
                if (destination instanceof Cesium.Cartesian3) {
                    const carto = Cesium.Cartographic.fromCartesian(destination);
                    coords = {
                        lat: Cesium.Math.toDegrees(carto.latitude),
                        lon: Cesium.Math.toDegrees(carto.longitude)
                    };
                } else if (destination instanceof Cesium.Rectangle) {
                    const center = Cesium.Rectangle.center(destination);
                    coords = {
                        lat: Cesium.Math.toDegrees(center.latitude),
                        lon: Cesium.Math.toDegrees(center.longitude)
                    };
                }

                if (coords) {
                    this.loadLocationAnalytics(coords.lat, coords.lon);
                    if (window.ui) window.ui.showNeuralScan(`SYNCED: ${name}`);
                }
            }
        });
    }

    // Loads all real reports once at startup and creates their pins —
    // visibility is controlled separately by setReportsVisible(), tied to
    // the 'reports' tab via ui.js's TAB_SCOPED_TEARDOWN, same as every
    // other tab-specific globe layer. (An earlier version of this
    // comment treated report pins as a deliberate global exception to
    // tab isolation — that was wrong; they follow the same rule now.)
    async loadUserReports() {
        const reports = await api.getReports();
        if (reports && reports.length) {
            reports.forEach(report => this.addReportEntity(report));
        }
    }

    addReportEntity(data) {
        const colorMap = {
            'Fire': Cesium.Color.ORANGERED,
            'Pollution': Cesium.Color.PURPLE,
            'Deforestation': Cesium.Color.LIMEGREEN,
            'Water': Cesium.Color.DODGERBLUE,
            'Flooding': Cesium.Color.ROYALBLUE,
            'Other': Cesium.Color.YELLOW
        };

        const color = colorMap[data.incident_type] || Cesium.Color.WHITE;
        
        const entity = this.viewer.entities.add({
            position: Cesium.Cartesian3.fromDegrees(data.lon, data.lat),
            // Report pins previously showed on every tab regardless of
            // which was active — the one layer that slipped through the
            // tab-isolation rule everything else already follows (see
            // ui.js's TAB_SCOPED_TEARDOWN). Starts visible only if
            // 'reports' happens to already be the active tab; setReportsVisible()
            // (called from TAB_SCOPED_TEARDOWN / switchTab's 'reports' case)
            // is what actually controls this going forward.
            show: AppState.activeTab === 'reports',
            point: {
                pixelSize: 10,
                color: color,
                outlineColor: Cesium.Color.BLACK,
                outlineWidth: 2,
                heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                disableDepthTestDistance: Number.POSITIVE_INFINITY
            },
            label: {
                text: data.incident_type,
                font: '12px Outfit',
                fillColor: Cesium.Color.WHITE,
                outlineColor: Cesium.Color.BLACK,
                outlineWidth: 2,
                style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                pixelOffset: new Cesium.Cartesian2(0, -15),
                distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 1000000)
            }
        });

        // Simple pulse animation for reports
        let startTime = Date.now();
        const pulse = () => {
            if (!entity) return;
            const elapsed = (Date.now() - startTime) / 1000;
            const scale = 1.0 + Math.sin(elapsed * 4) * 0.3;
            entity.point.pixelSize = 10 * scale;
            requestAnimationFrame(pulse);
        };
        pulse();

        entity._customData = {
            type: 'user_report',
            name: `User Report: ${data.incident_type}`,
            lat: data.lat,
            lon: data.lon,
            details: {
                "Type": data.incident_type,
                "Severity": `${data.severity}/5`,
                "Description": data.description,
                "Date": new Date(data.timestamp).toLocaleString()
            }
        };

        this.layers.reports.push(entity);
    }

    // Shows/hides every citizen report pin at once. Called from
    // ui.js's TAB_SCOPED_TEARDOWN (hide, on every tab switch) and from
    // switchTab()'s 'reports' case (show, when that tab is actually
    // active) — the same pattern every other tab-specific layer already
    // follows, which report pins had been missing.
    setReportsVisible(visible) {
        this.layers.reports.forEach((e) => { e.show = visible; });
    }

    startAutoRotation() {
        console.log("Auto Rotation module activated");
        this.isAutoRotating = true;
        AppState.setRotating(true);
        // Guard against the flyTo used to (re)start rotation immediately
        // triggering moveStart and cancelling itself.
        this._programmaticFlight = true;
        setTimeout(() => { this._programmaticFlight = false; }, 3200);

        if (!this.autoRotateSubscription) {
            this.autoRotateSubscription = this.viewer.scene.preRender.addEventListener(() => {
                // Belt-and-suspenders: only ever rotate while isAutoRotating
                // is true AND AppState confirms Tab 1 (Earth) is genuinely
                // the active tab right now. Checking AppState directly here,
                // rather than trusting isAutoRotating alone, means rotation
                // can't keep running on another tab even if some other
                // event path fails to call stopAutoRotation() in time.
                const onEarthTab = AppState.activeTab === 'earth';

                if (this.isAutoRotating && onEarthTab) {
                    const speed = this.rotationSpeedMultiplier || 1;

                    // Rotate the camera around the global Z-axis (North Pole).
                    // Slowed from 0.005 to 0.0015 rad/frame (~1 full spin per
                    // ~70s instead of ~21s) — the old speed was fast enough
                    // to cause motion discomfort for a cinematic idle view.
                    this.viewer.scene.camera.rotate(Cesium.Cartesian3.UNIT_Z, 0.0015 * speed);
                    
                    // Force the scene to render if it's sluggish 
                    this.viewer.scene.requestRender();
                } else if (this.isAutoRotating && !onEarthTab) {
                    // Flag says "rotating" but we're not on Tab 1 anymore —
                    // force it off now rather than spinning silently forever.
                    this.isAutoRotating = false;
                    AppState.setRotating(false);
                }
            });
        }
    }

    stopAutoRotation() {
        this.isAutoRotating = false;
        AppState.setRotating(false);
    }

    initCamera() {
        this._programmaticFlight = true;
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(
                CONFIG.DEFAULT_COORDINATES.lon,
                CONFIG.DEFAULT_COORDINATES.lat,
                CONFIG.DEFAULT_COORDINATES.height
            ),
            duration: 3.0, // Cinematic fly-in
            complete: () => {
                this._programmaticFlight = false;
                // App loads on Tab 1 by default — begin the cinematic
                // auto-rotate once the initial fly-in settles.
                if (AppState.activeTab === 'earth') {
                    this.startAutoRotation();
                }
            }
        });
    }

    initInteraction() {
        const handler = new Cesium.ScreenSpaceEventHandler(this.viewer.scene.canvas);
        
        handler.setInputAction((movement) => {
            const activeTab = AppState.activeTab;

            // Tab 1 (Earth) is a pure cinematic viewer — clicking just
            // interrupts auto-rotation, it never opens analytics/popups.
            if (activeTab === 'earth') {
                this.stopAutoRotation();
                return;
            }

            const pickedObject = this.viewer.scene.pick(movement.position);
            
            if (Cesium.defined(pickedObject)) {
                const entity = pickedObject.id || (pickedObject.primitive ? pickedObject.primitive.id : null);
                if (entity && entity._customData) {
                    // Show custom analytics in right panel
                    this.loadLocationAnalytics(entity._customData.lat, entity._customData.lon);
                    
                    // Show standard info box or custom popup
                    this.showEntityInfo(entity);
                    return;
                }
            }

            // If no data point picked, get the coordinates of the Earth surface
            const cartesian = this.viewer.camera.pickEllipsoid(movement.position, this.viewer.scene.globe.ellipsoid);
            if (cartesian) {
                const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
                const lat = Cesium.Math.toDegrees(cartographic.latitude);
                const lon = Cesium.Math.toDegrees(cartographic.longitude);
                
                console.log(`Globe click detected at: Lat ${lat.toFixed(4)}, Lon ${lon.toFixed(4)}`);
                
                // Show location title instead of generic "Data Insight"
                this.loadLocationAnalytics(lat, lon);
            }
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

        // Citizen reporting used to have its own right-click gesture here,
        // dispatching openReportModal with whatever point was clicked.
        // Removed — the sidebar's "Submit a Report" button (js/ui.js) is
        // now the only entry point, using AppState.selectedLocation
        // (already set by the LEFT_CLICK handler above) rather than a
        // separate, less discoverable interaction. Kept the app to one
        // consistent way to trigger every action instead of two.

        // Update layers based on UI toggles
        document.getElementById('layer-wildfires').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-wildfires', e.target.checked);
            this.toggleWildfires(e.target.checked);
        });
        document.getElementById('layer-temp').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-temp', e.target.checked);
            this.toggleTemperatureAnomalyRaster(e.target.checked);
        });
        document.getElementById('layer-ndvi').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-ndvi', e.target.checked);
            this.toggleVegetationRaster(e.target.checked);
        });
        document.getElementById('layer-rainfall').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-rainfall', e.target.checked);
            this.toggleEnvironmentalLayer(e.target.checked, 'rainfall');
        });
        document.getElementById('layer-weather').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-weather', e.target.checked);
            this.toggleEnvironmentalLayer(e.target.checked, 'weather');
        });
        document.getElementById('layer-sensors').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-sensors', e.target.checked);
            this.toggleSensors(e.target.checked);
        });
        document.getElementById('layer-wind').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-wind', e.target.checked);
            this.toggleWindLayer(e.target.checked);
        });

        // Level of Detail (LOD) based on camera height
        this.viewer.camera.moveEnd.addEventListener(() => {
            this.applyLOD();
        });
    }

    // The temporal 4D engine (toggleSatelliteView, updateTime, rotateToTime,
    // refreshImageryLayers, refreshNdviImagery, refreshSatelliteImagery,
    // toggleSplitScreen, initSplitDividerInteraction) used to live here,
    // driving live Cesium WMTS imagery layers on this same shared globe.
    // That approach caused visible glitching (rapid layer add/remove
    // fighting over the one shared scene, bleeding into every other tab)
    // and has been replaced entirely by js/snapshot-viewer.js, which
    // renders flat NASA GIBS snapshot images in its own panel and never
    // touches the globe. See PROJECT_STATUS.md for the historical note.


    showEntityInfo(entity) {
        const data = entity._customData;
        if (!data) return;
        
        let html = `<h3>${data.type.toUpperCase()} Data</h3>`;
        
        if (data.type === 'wildfire') {
            html += `
                <p><strong>FRP:</strong> ${data.frp.toFixed(1)} MW</p>
                <p><strong>Severity:</strong> ${data.tier ? data.tier.charAt(0).toUpperCase() + data.tier.slice(1) : 'N/A'}</p>
                <p><strong>Date:</strong> ${data.acq_date}</p>
                <p><strong>Conf:</strong> ${data.confidence}%</p>
            `;
        } else if (data.type === 'vegetation') {
            html += `<p><strong>NDVI Index:</strong> ${data.value.toFixed(3)}</p>`;
        } else if (data.type === 'climate') {
            html += `<p><strong>Temp Anomaly:</strong> ${data.value.toFixed(2)}°C</p>`;
        } else if (data.type === 'wind') {
            html += `
                <p><strong>Speed:</strong> ${data.speed_kmh.toFixed(1)} km/h</p>
                <p><strong>Direction:</strong> from ${data.direction_deg.toFixed(0)}°</p>
            `;
        }
        
        // Points are gone from most layers now (billboards/rectangles/
        // cylinders instead — see toggleWildfires/toggleEnvironmentalLayer/
        // toggleSensors). Billboard-based entities (wildfires, sensors)
        // don't have a queryable Cesium color property the way point/
        // rectangle/cylinder do — their color lives baked into the glyph
        // canvas image — so those store their real color directly in
        // _customData.colorHex at creation time, checked first here.
        let popupColor = data.colorHex || '#38bdf8';
        if (!data.colorHex) {
            if (entity.point) popupColor = entity.point.color.getValue().toCssColorString();
            else if (entity.rectangle) popupColor = entity.rectangle.material.getValue().color.toCssColorString();
            else if (entity.cylinder) popupColor = entity.cylinder.material.getValue().color.toCssColorString();
        }

        ui.showSensorPopup(entity.id, {
            name: `${data.type.charAt(0).toUpperCase() + data.type.slice(1)} Insight`,
            details: data,
            color: popupColor
        });
    }

    applyLOD() {
        if (!this.viewer) return;
        const height = this.viewer.camera.positionCartographic.height;
        const scale = height > 10000000 ? 0.5 : height > 2000000 ? 0.8 : 1.2;
        
        Object.values(this.layers).forEach(layer => {
            if (layer && layer.entities) {
                layer.entities.values.forEach(e => {
                    if (e.point) {
                        e.point.scaleByDistance = new Cesium.NearFarScalar(1.5e2, 2.0, 1.5e7, 0.5);
                    }
                    if (e.billboard) {
                        e.billboard.scaleByDistance = new Cesium.NearFarScalar(1.5e2, 1.4, 1.5e7, 0.4);
                    }
                });
            }
        });

        // Sensors used to need bespoke manual column-height scaling here
        // (CylinderGraphics has no built-in scaleByDistance the way
        // points/billboards do) — removed along with the 3D column
        // rendering itself. Sensors is now a real billboard DataSource,
        // same as wildfires/wind, so the generic loop above already
        // handles its distance scaling automatically.
    }

    async loadLocationAnalytics(lat, lon) {
        try {
            // AppState.setSelectedLocation is now the single source of truth
            // for "what location is selected" — previously this was tracked
            // here AND separately in UIManager, kept in sync only by a
            // custom event (plus one spot that reached directly into this
            // object's fields from ui.js).
            AppState.setSelectedLocation(lat, lon);

            // Screen 2: Top-Down Camera View (No Tilt as per User Request).
            // Preserve the user's EXACT current zoom level — no forced
            // zoom-out, no forced zoom-in. The previous version clamped a
            // 50,000m minimum "so the view doesn't feel claustrophobic,"
            // but that itself forced a zoom-out for anyone closer than
            // 50km, which is most of the time when inspecting a specific
            // spot. Only keeping the upper cap, which guards against the
            // original "always jumps to a fixed 2,000,000m" bug.
            const currentHeight = this.viewer.camera.positionCartographic.height;
            const targetHeight = Math.min(currentHeight, 2000000);

            this.viewer.camera.flyTo({
                destination: Cesium.Cartesian3.fromDegrees(lon, lat, targetHeight),
                orientation: {
                    heading: Cesium.Math.toRadians(0),
                    pitch: Cesium.Math.toRadians(-90),
                    roll: 0
                },
                duration: 2.0
            });

            const climateData = await api.getClimate(lat, lon);
            const envData = await api.getEnvironment(lat, lon);
            const shiData = await api.getShi(lat, lon);
            const ndviData = await api.getNdviValue(lat, lon, this.currentDate);

            // Predictive AI (Phase 2): fetched alongside the existing calls
            // above rather than blocking on them — these three hit
            // different upstream services (Open-Meteo, MODIS) than the
            // existing calls, so there's no shared rate limit to worry
            // about by running them concurrently.
            const [forecastData, aqiForecastData, wildfireRiskData] = await Promise.all([
                api.getWeatherForecast(lat, lon, 7),
                api.getAirQualityForecast(lat, lon, 5),
                api.getWildfireRisk(lat, lon),
            ]);

            if (ui) {
                ui.updateAnalyticsPanel(climateData, envData, shiData, ndviData);
                ui.updateForecastPanels(forecastData, aqiForecastData, wildfireRiskData);
            }
        } catch (e) {
            console.error("Failed to load analytics:", e);
        }
    }

    // LAYER MANAGEMENT
    async toggleWildfires(visible) {
        if (!visible) {
            if (this.layers.wildfires) {
                this.viewer.dataSources.remove(this.layers.wildfires);
                this.layers.wildfires = null;
            }
            // Drop any pulsing entries this layer registered — otherwise
            // toggling wildfires off/on repeatedly leaks stale billboard
            // references into the shared pulse loop.
            this._pulsingBillboards = this._pulsingBillboards.filter((p) => p.layer !== 'wildfires');
            return;
        }

        const data = await api.getWildfires();
        if (!data) {
            document.dispatchEvent(new CustomEvent('layerNotice', {
                detail: { message: 'Could not reach the wildfire data feed — check that the backend server is running.' }
            }));
            return;
        }
        if (!data.features || data.features.length === 0) {
            document.dispatchEvent(new CustomEvent('layerNotice', {
                detail: { message: 'No active wildfires detected in the last 24 hours — this is a real "all clear," not an error.' }
            }));
            return;
        }

        try {
            const dataSource = await Cesium.GeoJsonDataSource.load(data, {
                clampToGround: true
            });

            const entities = dataSource.entities.values;
            for (let i = 0; i < entities.length; i++) {
                const entity = entities[i];
                const frp = entity.properties.frp ? entity.properties.frp.getValue() : 10;

                // 5-tier severity spectrum by Fire Radiative Power (MW),
                // not just 3 buckets — low-intensity detections (the
                // majority of real ones) now read distinctly from
                // moderate/high/severe/extreme instead of collapsing into
                // one "yellow" bucket.
                let colorHex, tier;
                if (frp <= 10) { colorHex = '#f5b942'; tier = 'low'; }
                else if (frp <= 40) { colorHex = '#f2792e'; tier = 'moderate'; }
                else if (frp <= 100) { colorHex = '#e6432c'; tier = 'high'; }
                else if (frp <= 300) { colorHex = '#b31f1f'; tier = 'severe'; }
                else { colorHex = '#6e0f0f'; tier = 'extreme'; }

                // Glyph size scales gently with FRP within its tier —
                // magnitude still reads through size, same as before,
                // but now on a recognizable flame icon with a glow halo
                // instead of a flat colored circle.
                const glyphSize = Math.round(Math.min(40, 22 + frp / 45));
                const canvas = this._getGlyphCanvas(`fire-${colorHex}-${glyphSize}`,
                    () => this._createFlameGlyphCanvas(colorHex, glyphSize));

                entity.point = undefined;
                entity.billboard = {
                    image: canvas,
                    scale: 1,
                    verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                    disableDepthTestDistance: Number.POSITIVE_INFINITY,
                };

                // Add custom data for tooltips
                entity._customData = {
                    type: 'wildfire',
                    frp: frp,
                    tier,
                    colorHex,
                    acq_date: entity.properties.acq_date ? entity.properties.acq_date.getValue() : 'N/A',
                    confidence: entity.properties.confidence ? entity.properties.confidence.getValue() : 0,
                    lat: Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(entity.position.getValue()).latitude),
                    lon: Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(entity.position.getValue()).longitude)
                };

                // Only the two most urgent tiers pulse — motion stays
                // reserved for things that actually warrant attention,
                // rather than every single fire on the map breathing at
                // once (which would just read as visual noise).
                if (tier === 'severe' || tier === 'extreme') {
                    this._pulsingBillboards.push({
                        billboard: entity.billboard,
                        baseScale: 1,
                        phase: Math.random() * Math.PI * 2,
                        layer: 'wildfires',
                    });
                }
            }
            
            // NASA-style clustering
            dataSource.clustering.enabled = true;
            dataSource.clustering.pixelRange = 40;
            dataSource.clustering.minimumClusterSize = 2;
            
            dataSource.clustering.clusterEvent.addEventListener((clusteredEntities, cluster) => {
                cluster.label.show = true;
                cluster.label.text = clusteredEntities.length.toString();
                cluster.billboard.show = true;
                cluster.billboard.image = this.createClusterCanvas(clusteredEntities.length);
            });

            this.viewer.dataSources.add(dataSource);
            this.layers.wildfires = dataSource;
            this.viewer.scene.requestRender();

        } catch (e) {
            console.error("Wildfire load error:", e);
        }
    }

    createClusterCanvas(count) {
        const canvas = document.createElement('canvas');
        canvas.width = 32; canvas.height = 32;
        const ctx = canvas.getContext('2d');
        ctx.beginPath(); ctx.arc(16, 16, 12, 0, 2 * Math.PI);
        ctx.fillStyle = 'rgba(239, 68, 68, 0.9)'; ctx.fill();
        ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
        ctx.fillStyle = '#fff'; ctx.font = 'bold 10px Inter'; ctx.textAlign = 'center';
        ctx.fillText(count > 99 ? '99+' : count, 16, 20);
        return canvas;
    }

    // Cache + retrieve a generated glyph canvas by key, so a given
    // color/size combination is only ever drawn once (see this._glyphCache
    // in the constructor).
    _getGlyphCanvas(key, drawFn) {
        if (!this._glyphCache[key]) {
            this._glyphCache[key] = drawFn();
        }
        return this._glyphCache[key];
    }

    // Soft radial glow behind a solid ringed core — the shared "real
    // point sensor" glyph used for AQI station tops and any other
    // single-value point marker. A plain Cesium PointGraphics can't glow
    // on its own (no blur/shadow support), so this bakes the glow into
    // the billboard image itself instead.
    _createGlowDotCanvas(hexColor, coreRadius = 5, glowRadius = 14) {
        const size = glowRadius * 2;
        const canvas = document.createElement('canvas');
        canvas.width = size; canvas.height = size;
        const ctx = canvas.getContext('2d');
        const cx = size / 2, cy = size / 2;

        const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowRadius);
        glow.addColorStop(0, hexColor + 'aa');
        glow.addColorStop(1, hexColor + '00');
        ctx.fillStyle = glow;
        ctx.fillRect(0, 0, size, size);

        ctx.beginPath();
        ctx.arc(cx, cy, coreRadius, 0, Math.PI * 2);
        ctx.fillStyle = hexColor;
        ctx.fill();
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = 'rgba(255,255,255,0.75)';
        ctx.stroke();

        return canvas;
    }

    // Stylized flame glyph for wildfire points, with the same glow-halo
    // treatment as the AQI dot so both "real point event" layers share
    // one visual grammar instead of two unrelated dot styles. A
    // recognizable icon reads faster at a glance than an abstract
    // colored circle for something as identifiable as fire.
    _createFlameGlyphCanvas(hexColor, size = 28) {
        const canvas = document.createElement('canvas');
        canvas.width = size; canvas.height = size;
        const ctx = canvas.getContext('2d');
        const cx = size / 2;

        const glow = ctx.createRadialGradient(cx, size * 0.6, 0, cx, size * 0.6, size / 1.7);
        glow.addColorStop(0, hexColor + '99');
        glow.addColorStop(1, hexColor + '00');
        ctx.fillStyle = glow;
        ctx.fillRect(0, 0, size, size);

        ctx.save();
        const s = size / 28;
        ctx.translate(cx, size * 0.82);
        ctx.scale(s, s);
        ctx.beginPath();
        ctx.moveTo(0, -22);
        ctx.bezierCurveTo(7, -14, 9, -6, 5, 0);
        ctx.bezierCurveTo(9, -2, 11, 4, 6, 9);
        ctx.bezierCurveTo(8, 6, 7, 2, 4, 3);
        ctx.bezierCurveTo(5, 8, 0, 12, -3, 9);
        ctx.bezierCurveTo(-7, 6, -6, 1, -3, -1);
        ctx.bezierCurveTo(-6, -6, -5, -13, 0, -22);
        ctx.closePath();
        ctx.fillStyle = hexColor;
        ctx.fill();
        ctx.restore();

        return canvas;
    }

    // Directional arrow for the wind layer. Drawn pointing "up" (screen
    // north) once per speed tier; per-entity direction is applied via
    // Cesium's billboard.rotation at render time, not baked into the
    // canvas, so this stays in the small cache like every other glyph.
    _createWindArrowCanvas(hexColor, size = 20) {
        const canvas = document.createElement('canvas');
        canvas.width = size; canvas.height = size;
        const ctx = canvas.getContext('2d');
        const cx = size / 2;
        ctx.strokeStyle = hexColor;
        ctx.fillStyle = hexColor;
        ctx.lineWidth = Math.max(1.5, size / 12);
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(cx, size * 0.88);
        ctx.lineTo(cx, size * 0.22);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(cx, size * 0.02);
        ctx.lineTo(cx - size * 0.24, size * 0.36);
        ctx.lineTo(cx + size * 0.24, size * 0.36);
        ctx.closePath();
        ctx.fill();
        return canvas;
    }

    async toggleEnvironmentalLayer(visible, type) {
        if (!visible) {
            if (this.layers[type]) {
                this.viewer.dataSources.remove(this.layers[type]);
                this.layers[type] = null;
            }
            return;
        }

        // All four render as real colored data points from our own
        // backend — reliable, since we control the data end to end, unlike
        // the GIBS imagery tile layer NDVI used to rely on (that endpoint's
        // exact tile matrix conventions proved unreliable even under
        // direct testing, and is still used separately for Tab 3's
        // historical imagery comparison, where an actual image layer adds
        // real value).
        // Temperature/anomaly used to render here too, as grid-cell
        // rectangles like the other three — moved to its own dedicated
        // toggleTemperatureAnomalyRaster() (interpolated raster imagery
        // layer) because at only 126 real points on a 20° grid with a
        // latitude-only baseline model, rectangle cells visually banded
        // by latitude rather than reading as real geographic variation.
        // NDVI/rainfall/weather don't have that same problem (their
        // values vary genuinely by both lat and lon, not just lat), so
        // they're unchanged here.
        // NDVI used to render here too, alongside rainfall/weather —
        // moved to its own dedicated toggleVegetationRaster() so it can
        // honestly represent real MODIS pixels without any spatial
        // interpolation between them (real MODIS coverage has real
        // gaps — ocean, persistent cloud — that should read as
        // transparent, not blended with a neighboring real cell).
        const fetchers = {
            rainfall: () => api.getRainfall(),
            weather: () => api.getWeatherConditions(),
        };
        const labels = {
            rainfall: 'rainfall', weather: 'weather conditions',
        };
        const data = await fetchers[type]();
        const label = labels[type];

        if (!data || !data.features || data.features.length === 0) {
            // Distinguish "server unreachable" from "server responded but
            // had nothing to give us" — these have different causes and
            // different fixes, and used to show the same misleading
            // message regardless of which one actually happened.
            const message = api.lastErrorKind === 'network'
                ? `Could not reach the backend — check that the FastAPI server is running (e.g. via start_project.bat or "uvicorn main:app") and reachable at ${CONFIG.API_BASE_URL}.`
                : `The backend is running, but couldn't get real ${label} data from its upstream source (Open-Meteo) right now — check the backend server's console log for the actual error, or try again in a minute.`;
            document.dispatchEvent(new CustomEvent('layerNotice', {
                detail: { message }
            }));
            return;
        }

        try {
            const dataSource = await Cesium.GeoJsonDataSource.load(data, { clampToGround: true });
            const entities = dataSource.entities.values;

            // Half-width of each grid cell, in degrees — matches the
            // backend's sampling step (climate.py's shared grid
            // conditions fetch, used by rainfall/weather, steps every
            // 20°). Rendering a filled cell at this size instead of a
            // small dot is what actually fixes the "continuous field
            // shown as scattered dots" problem: these are gridded field
            // samples, not discrete point events, so they should read as
            // a continuous shaded surface, not a sparse scatter plot.
            const halfStepDeg = 10;

            for (let i = 0; i < entities.length; i++) {
                const entity = entities[i];
                const val = entity.properties.value ? entity.properties.value.getValue() : 0;
                const pointSource = entity.properties.data_source ? entity.properties.data_source.getValue() : null;

                let colorHex;
                if (type === 'rainfall') {
                    // Dry -> light rain -> heavy rain (mm in the last hour)
                    if (val <= 0) colorHex = '#78716c'; // Dry
                    else if (val < 2.5) colorHex = '#7dd3fc'; // Light
                    else if (val < 10) colorHex = '#0ea5e9'; // Moderate
                    else colorHex = '#1e3a8a'; // Heavy
                } else {
                    // Weather conditions: cloud cover %, clear -> overcast
                    if (val < 25) colorHex = '#fde047'; // Clear
                    else if (val < 60) colorHex = '#cbd5e1'; // Partly cloudy
                    else colorHex = '#64748b'; // Overcast
                }

                const cartographic = Cesium.Cartographic.fromCartesian(entity.position.getValue());
                const lat = Cesium.Math.toDegrees(cartographic.latitude);
                const lon = Cesium.Math.toDegrees(cartographic.longitude);

                // A fallback/estimated sample (currently only possible on
                // the NDVI grid — see modis_ndvi.py's real_modis vs.
                // estimated_fallback split) renders at reduced opacity
                // rather than a dashed outline (Cesium rectangle outlines
                // don't support dash patterns) — dimmer visually reads as
                // "less certain," consistent with the LIVE/EST badge
                // language used in the side panels.
                const isEstimated = pointSource && pointSource !== 'real_modis' && pointSource !== 'real_openmeteo';
                const fillAlpha = isEstimated ? 0.22 : 0.62;

                entity.point = undefined;
                entity.billboard = undefined; // Cesium's GeoJsonDataSource default is a billboard pin, not .point — only nulling .point left every grid cell's default blue marker fully visible
                // A grid cell centered near the antimeridian (lon close to
                // ±180°) or a pole (lat close to ±90°) can compute an edge
                // past the valid range once halfStepDeg is added/
                // subtracted — Cesium.Rectangle.fromDegrees does not wrap
                // or clip this itself, it throws a hard DeveloperError
                // ("Expected west to be greater than or equal to -PI...")
                // that stops the entire render loop, not just that one
                // cell. Clamping slightly distorts the handful of cells
                // right at that edge, which is a far better tradeoff than
                // crashing the whole tab over it.
                const west = Math.max(-180, lon - halfStepDeg);
                const east = Math.min(180, lon + halfStepDeg);
                const south = Math.max(-90, lat - halfStepDeg);
                const north = Math.min(90, lat + halfStepDeg);
                if (west >= east || south >= north) continue; // degenerate cell, skip rather than guess

                entity.rectangle = {
                    coordinates: Cesium.Rectangle.fromDegrees(west, south, east, north),
                    material: Cesium.Color.fromCssColorString(colorHex).withAlpha(fillAlpha),
                    outline: true,
                    outlineColor: Cesium.Color.fromCssColorString('#94a3b8').withAlpha(0.18),
                    outlineWidth: 1,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                };

                entity._customData = {
                    type: label,
                    value: val,
                    dataSource: pointSource,
                    lat, lon,
                };
            }

            this.viewer.dataSources.add(dataSource);
            this.layers[type] = dataSource;
            this.viewer.scene.requestRender();
        } catch (e) {
            console.error(`Error loading layer ${type}:`, e);
        }
    }

    // Diverging color scale for temperature anomaly, centered at 0°C —
    // dark blue (<=-4) -> light blue (-2) -> near-neutral/transparent (0)
    // -> orange (+2) -> red (>=+4). Piecewise-linear RGB interpolation
    // between these five real control points, not a hard bucket split,
    // so the color itself varies smoothly with the interpolated value.
    _anomalyToColor(value) {
        const stops = [
            { v: -4, rgb: [8, 48, 107] },    // dark blue
            { v: -2, rgb: [107, 174, 214] }, // light blue
            { v: 0, rgb: [230, 230, 230] },  // neutral (near-transparent via alpha, not pure white)
            { v: 2, rgb: [253, 141, 60] },   // orange
            { v: 4, rgb: [165, 15, 21] },    // red
        ];
        const clamped = Math.max(-4, Math.min(4, value));
        let lo = stops[0], hi = stops[stops.length - 1];
        for (let i = 0; i < stops.length - 1; i++) {
            if (clamped >= stops[i].v && clamped <= stops[i + 1].v) {
                lo = stops[i]; hi = stops[i + 1];
                break;
            }
        }
        const span = hi.v - lo.v;
        const t = span === 0 ? 0 : (clamped - lo.v) / span;
        const rgb = lo.rgb.map((c, i) => Math.round(c + (hi.rgb[i] - c) * t));

        // Alpha grows with |anomaly| magnitude rather than being fixed —
        // near-baseline areas fade toward transparent ("approximately
        // normal" reads as barely-there), strongly anomalous areas reach
        // the spec's ~0.45-0.60 ceiling. Never fully opaque, so the base
        // imagery, coastlines, and borders stay visible underneath.
        const magnitude = Math.min(1, Math.abs(clamped) / 4);
        const alpha = 0.10 + magnitude * 0.50; // 0.10 at anomaly=0 .. 0.60 at |anomaly|>=4

        return [rgb[0], rgb[1], rgb[2], Math.round(alpha * 255)];
    }

    // Builds a smooth interpolated raster from the real grid points using
    // Inverse Distance Weighting (IDW) — a standard, honest spatial
    // interpolation method: every output pixel is a distance-weighted
    // blend of REAL nearby measurements, never a value invented outside
    // what the real data supports. A point falling exactly on a real
    // sample returns that real value unchanged (see the near-zero-
    // distance short-circuit below).
    async toggleTemperatureAnomalyRaster(visible, offset = 0) {
        if (!visible) {
            if (this.layers.temperatureAnomalyImagery) {
                this.viewer.imageryLayers.remove(this.layers.temperatureAnomalyImagery);
                this.layers.temperatureAnomalyImagery = null;
            }
            return;
        }

        const data = await api.getClimate();
        if (!data || !data.features || data.features.length === 0) {
            const message = api.lastErrorKind === 'network'
                ? `Could not reach the backend — check that the FastAPI server is running and reachable at ${CONFIG.API_BASE_URL}.`
                : `The backend is running, but couldn't get real temperature data from its upstream source (Open-Meteo) right now — check the backend server's console log for the actual error, or try again in a minute.`;
            document.dispatchEvent(new CustomEvent('layerNotice', { detail: { message } }));
            return;
        }

        // Real (lat, lon, anomaly) tuples — this is the actual spatial
        // data the interpolation is built from, nothing else.
        const points = data.features.map(f => ({
            lon: f.geometry.coordinates[0],
            lat: f.geometry.coordinates[1],
            value: f.properties.value,
        }));

        // Real data's actual latitude range (matches
        // backend/services/climate.py's _build_grid_points: -60..80) —
        // used below to leave rows outside this range fully transparent,
        // never to restrict the imagery layer's own rectangle.
        const dataSouth = Math.min(...points.map(p => p.lat));
        const dataNorth = Math.max(...points.map(p => p.lat));

        // Full-globe extent for both the canvas and the imagery
        // rectangle — NOT a custom rectangle restricted to where real
        // data exists. SingleTileImageryProvider assumes a
        // GeographicTilingScheme, and its standard, well-tested usage is
        // covering the full globe rectangle; an earlier version of this
        // code used a smaller custom rectangle (just the real data's
        // latitude range) and that combination produced a severe
        // tiling/repeating artifact — the same single image rendering
        // several times across the globe instead of stretching once.
        // Using the full extent here removes that variable entirely.
        // Coverage honesty is preserved a different way: rows outside
        // the real data's actual latitude range are painted fully
        // transparent (alpha 0) rather than given a color, so nothing
        // is visually claimed for the poles where there's no real
        // sample — see the transparency check in the pixel loop below.
        const west = -180, east = 180, south = -90, north = 90;

        // One pixel per degree across the FULL globe (360x180) — still
        // cheap: see the performance note below, ~127ms measured for a
        // comparable pixel count with 126 real points.
        const width = 360;
        const height = 180;
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        const imageData = ctx.createImageData(width, height);

        const POWER = 2; // standard IDW exponent
        for (let py = 0; py < height; py++) {
            const lat = north - py - 0.5; // canvas row 0 = north edge, sample at pixel center
            for (let px = 0; px < width; px++) {
                const lon = west + px + 0.5;
                const idx = (py * width + px) * 4;

                // No real data exists outside the sampled latitude band
                // (poles) — leave fully transparent rather than color it,
                // instead of restricting the rectangle to avoid this.
                if (lat < dataSouth || lat > dataNorth) {
                    imageData.data[idx] = 0;
                    imageData.data[idx + 1] = 0;
                    imageData.data[idx + 2] = 0;
                    imageData.data[idx + 3] = 0;
                    continue;
                }

                // Sparse-point data (126 real samples, ~20° grid spacing,
                // confirmed by inspecting backend/services/climate.py's
                // _build_grid_points directly) does not support a
                // full-globe continuous fill — a pixel far from every
                // real sample has no real information behind it, and
                // coloring it anyway (the previous version had no
                // distance cutoff at all) is exactly the "default value
                // filling unsampled pixels" this is required not to do.
                // Only real points within MAX_INFLUENCE_DEG of this pixel
                // are even considered; farther points don't get
                // down-weighted, they're excluded from the average
                // entirely. Roughly grid-spacing + 10% so neighboring
                // real cells' influence zones overlap enough to blend
                // into each other smoothly, without reaching into
                // unrelated distant regions.
                const MAX_INFLUENCE_DEG = 22;

                let weightedSum = 0;
                let weightTotal = 0;
                let exact = null;
                let nearestDist = Infinity;
                for (const p of points) {
                    const dLat = lat - p.lat;
                    let dLon = Math.abs(lon - p.lon);
                    if (dLon > 180) dLon = 360 - dLon; // shortest path across the antimeridian, e.g. 170 vs -170 is really 20 apart, not 340
                    const dist = Math.sqrt(dLat * dLat + dLon * dLon);
                    if (dist > MAX_INFLUENCE_DEG) continue; // outside the real data's local reach — ignored, not down-weighted
                    if (dist < nearestDist) nearestDist = dist;
                    if (dist < 1e-3) { exact = p.value; break; } // essentially on a real sample point
                    const w = 1 / Math.pow(dist * dist, POWER / 2);
                    weightedSum += w * p.value;
                    weightTotal += w;
                }

                if (nearestDist === Infinity) {
                    // No real sample anywhere within reach of this pixel
                    // — transparent, not a fallback color of any kind.
                    imageData.data[idx] = 0;
                    imageData.data[idx + 1] = 0;
                    imageData.data[idx + 2] = 0;
                    imageData.data[idx + 3] = 0;
                    continue;
                }

                const interpolated = (exact !== null ? exact : weightedSum / weightTotal) + offset;
                const [r, g, b, a] = this._anomalyToColor(interpolated);

                // Soft fade from full alpha (right at a real point) to
                // zero (at the edge of its influence radius) — a hard
                // cutoff here would just trade the old sharp color-blob
                // edge for an equally artificial sharp transparent edge.
                const coverageFade = Math.max(0, Math.min(1, 1 - nearestDist / MAX_INFLUENCE_DEG));
                imageData.data[idx] = r;
                imageData.data[idx + 1] = g;
                imageData.data[idx + 2] = b;
                imageData.data[idx + 3] = Math.round(a * coverageFade);
            }
        }
        ctx.putImageData(imageData, 0, 0);

        // Remove any previous layer before adding the new one — never
        // stack multiple temperature imagery layers on top of each other.
        if (this.layers.temperatureAnomalyImagery) {
            this.viewer.imageryLayers.remove(this.layers.temperatureAnomalyImagery);
            this.layers.temperatureAnomalyImagery = null;
        }

        try {
            const provider = await Cesium.SingleTileImageryProvider.fromUrl(
                canvas.toDataURL('image/png'),
                { rectangle: Cesium.Rectangle.fromDegrees(west, south, east, north) }
            );
            const layer = new Cesium.ImageryLayer(provider);
            this.viewer.imageryLayers.add(layer);
            this.layers.temperatureAnomalyImagery = layer;
        } catch (e) {
            console.error('Failed to build temperature anomaly raster layer:', e);
        }
    }

    // Diverging-by-density color scale for NDVI: <0 is handled by the
    // caller (transparent, never reaches here) — this only maps the real
    // 0..1 vegetation range: brown (bare) -> yellow-green (low) -> green
    // (moderate) -> dark green (dense), per the exact NDVI scale
    // specified. Smooth color blending WITHIN this value-based scale is
    // not the same thing as spatial interpolation between measurement
    // locations (which this layer never does) — every pixel in a real
    // cell gets the exact same value and therefore the exact same color.
    _ndviToColor(value) {
        const stops = [
            { v: 0.0, rgb: [161, 98, 7] },    // brown/tan — sparse/bare
            { v: 0.2, rgb: [190, 190, 40] },  // yellow — low vegetation
            { v: 0.4, rgb: [132, 204, 22] },  // light green — low-moderate
            { v: 0.6, rgb: [34, 139, 34] },   // green — moderate
            { v: 1.0, rgb: [10, 65, 20] },    // dark green — dense
        ];
        const clamped = Math.max(0, Math.min(1, value));
        let lo = stops[0], hi = stops[stops.length - 1];
        for (let i = 0; i < stops.length - 1; i++) {
            if (clamped >= stops[i].v && clamped <= stops[i + 1].v) { lo = stops[i]; hi = stops[i + 1]; break; }
        }
        const span = hi.v - lo.v;
        const t = span === 0 ? 0 : (clamped - lo.v) / span;
        return lo.rgb.map((c, i) => Math.round(c + (hi.rgb[i] - c) * t));
    }

    // Real per-location classification, used both for the raster color
    // (indirectly, via _ndviToColor) and for the Insight panel's text
    // label — kept as one shared source of truth so the map and the
    // panel never disagree about what "Moderate" means.
    _ndviClassification(value) {
        if (value < 0) return 'Water/Snow/Non-vegetated';
        if (value < 0.2) return 'Sparse';
        if (value < 0.4) return 'Low';
        if (value < 0.6) return 'Moderate';
        return 'Dense';
    }

    async toggleVegetationRaster(visible, factor = 1.0) {
        if (!visible) {
            if (this.layers.vegetationImagery) {
                this.viewer.imageryLayers.remove(this.layers.vegetationImagery);
                this.layers.vegetationImagery = null;
            }
            return;
        }

        const data = await api.getVegetation();
        if (!data || !data.features || data.features.length === 0) {
            const message = api.lastErrorKind === 'network'
                ? `Could not reach the backend — check that the FastAPI server is running and reachable at ${CONFIG.API_BASE_URL}.`
                : `The backend is running, but couldn't get real NDVI data from NASA MODIS (via ORNL DAAC) right now — check the backend server's console log for the actual error, or try again in a minute.`;
            document.dispatchEvent(new CustomEvent('layerNotice', { detail: { message } }));
            return;
        }

        // Diagnostic: real vs fallback counts and a sample of actual
        // values, logged directly rather than guessed at — if real_pct
        // is low, most of the grid is falling back to the (genuinely
        // latitude-based) biome estimate model in modis_ndvi.py, which
        // would explain banding even though the render code itself
        // filters fallback cells to transparent. If real_pct is high but
        // banding still shows, the bug is elsewhere and this rules out
        // the data-coverage theory.
        const realCount = data.features.filter(f => f.properties.data_source === 'real_modis').length;
        const fallbackCount = data.features.length - realCount;
        console.log(`[NDVI diagnostic] ${realCount} real MODIS pixels, ${fallbackCount} fallback (${Math.round(100 * realCount / data.features.length)}% real)`);
        console.log('[NDVI diagnostic] sample of 10 real points:',
            data.features.filter(f => f.properties.data_source === 'real_modis').slice(0, 10)
                .map(f => ({ lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0], ndvi: f.properties.value })));
        console.log('[NDVI diagnostic] sample of 10 fallback points:',
            data.features.filter(f => f.properties.data_source !== 'real_modis').slice(0, 10)
                .map(f => ({ lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0], ndvi: f.properties.value })));

        // Real grid is on a known REGULAR step (10°, confirmed against
        // backend/services/modis_ndvi.py's get_vegetation_geojson), so
        // "nearest real cell" can be computed directly by rounding to
        // the grid index — no distance search needed, and critically, no
        // blending between cells: every pixel inside one real cell gets
        // that cell's exact real value, nothing else.
        const STEP = 10;
        const LAT_START = -60, LON_START = -180;
        const cellByIndex = {};
        data.features.forEach(f => {
            const lon = f.geometry.coordinates[0];
            const lat = f.geometry.coordinates[1];
            const latIdx = Math.round((lat - LAT_START) / STEP);
            const lonIdx = Math.round((lon - LON_START) / STEP);
            cellByIndex[`${latIdx},${lonIdx}`] = {
                value: f.properties.value,
                isReal: f.properties.data_source === 'real_modis',
            };
        });

        const west = -180, east = 180, south = -90, north = 90;
        const width = 360, height = 180;
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        const imageData = ctx.createImageData(width, height);

        for (let py = 0; py < height; py++) {
            const lat = north - py - 0.5;
            for (let px = 0; px < width; px++) {
                const lon = west + px + 0.5;
                const idx = (py * width + px) * 4;

                const latIdx = Math.round((lat - LAT_START) / STEP);
                const lonIdx = Math.round((lon - LON_START) / STEP);
                const cell = cellByIndex[`${latIdx},${lonIdx}`];

                // Transparent, not colored, when: outside the real
                // sampled grid range entirely; the cell is a biome
                // estimate rather than a real MODIS pixel (ocean/cloud/
                // timeout fallback — see modis_ndvi.py); or the real
                // value is negative (water/snow/non-vegetated, per the
                // specified scale). Never a fallback color of any kind.
                if (!cell || !cell.isReal || cell.value < 0) {
                    imageData.data[idx] = 0;
                    imageData.data[idx + 1] = 0;
                    imageData.data[idx + 2] = 0;
                    imageData.data[idx + 3] = 0;
                    continue;
                }

                const [r, g, b] = this._ndviToColor(cell.value * factor);
                imageData.data[idx] = r;
                imageData.data[idx + 1] = g;
                imageData.data[idx + 2] = b;
                imageData.data[idx + 3] = Math.round(0.50 * 255); // flat ~0.50 opacity, within the specified 0.45-0.55 range
            }
        }
        ctx.putImageData(imageData, 0, 0);

        if (this.layers.vegetationImagery) {
            this.viewer.imageryLayers.remove(this.layers.vegetationImagery);
            this.layers.vegetationImagery = null;
        }

        try {
            const provider = await Cesium.SingleTileImageryProvider.fromUrl(
                canvas.toDataURL('image/png'),
                { rectangle: Cesium.Rectangle.fromDegrees(west, south, east, north) }
            );
            const layer = new Cesium.ImageryLayer(provider);
            this.viewer.imageryLayers.add(layer);
            this.layers.vegetationImagery = layer;
        } catch (e) {
            console.error('Failed to build vegetation raster layer:', e);
        }
    }

    listenForScenarios() {
        document.addEventListener('scenarioRan', (e) => {
            const prediction = e.detail;
            const pos = Cesium.Cartesian3.fromDegrees(prediction.location.lon, prediction.location.lat);
            
            this.viewer.camera.flyTo({
                destination: Cesium.Cartesian3.fromDegrees(prediction.location.lon, prediction.location.lat, 2000000),
                duration: 2.0
            });

            // Screen 4: Heatmap Visualization
            const entity = this.viewer.entities.add({
                position: pos,
                ellipse: {
                    semiMinorAxis: 500000,
                    semiMajorAxis: 500000,
                    material: Cesium.Color.RED.withAlpha(0.4),
                    outline: true,
                    outlineColor: Cesium.Color.RED,
                    height: 50000
                }
            });

            // Pulse effect
            let size = 500000;
            const pulse = () => {
                if (!entity) return;
                size += 10000;
                entity.ellipse.semiMinorAxis = size;
                entity.ellipse.semiMajorAxis = size;
                entity.ellipse.material = Cesium.Color.RED.withAlpha(Math.max(0, 0.4 - (size-500000)/2000000));
                
                if (size < 2000000) {
                    requestAnimationFrame(pulse);
                } else {
                    this.viewer.entities.remove(entity);
                }
            };
             pulse();
        });

        document.addEventListener('globalSimulationApplied', (e) => {
             const { tempOffset, rainOffset } = e.detail;

             // Intensify Temperature Layer — regenerates the interpolated
             // raster with the simulated offset applied to every real
             // point before coloring (see toggleTemperatureAnomalyRaster's
             // offset parameter), rather than poking individual rectangle
             // entities the way this used to work before temperature
             // moved to a raster imagery layer. Only re-renders if the
             // layer is currently on — a running simulation shouldn't
             // spontaneously turn on a layer the user hasn't enabled.
             if (this.layers.temperatureAnomalyImagery) {
                 this.toggleTemperatureAnomalyRaster(true, tempOffset);
             }

             // Intensify NDVI Layer — regenerates the raster with the
             // simulated multiplicative factor applied to every real
             // cell's value before coloring (see toggleVegetationRaster's
             // factor parameter), rather than poking individual rectangle
             // entities the way this used to work before NDVI moved to a
             // raster imagery layer. Only re-renders if the layer is
             // currently on, same "don't spontaneously enable a layer
             // the user hasn't turned on" rule as temperature.
             if (this.layers.vegetationImagery) {
                 const factor = 1.0 + (rainOffset / 100);
                 this.toggleVegetationRaster(true, factor);
             }
        });
    }

    async toggleSensors(visible) {
        if (!visible) {
            if (this.layers.sensors) {
                this.viewer.dataSources.remove(this.layers.sensors);
                this.layers.sensors = null;
            }
            // Drop any pulsing entries this layer registered — same
            // cleanup wildfires does on toggle-off, otherwise repeated
            // on/off leaks stale billboard references into the shared
            // pulse loop.
            this._pulsingBillboards = this._pulsingBillboards.filter((p) => p.layer !== 'sensors');
            return;
        }

        // Real per-station readings, resolved server-side — NOT /stations,
        // which is metadata only. The old code read s.parameters[].lastValue
        // directly from /stations, but that field never existed in OpenAQ
        // v3's response shape, so pmValue silently defaulted to 0 for every
        // single station — which is why every dot rendered green regardless
        // of real air quality.
        const stations = await api.getStationsWithReadings();
        if (!stations || !stations.length) {
            const message = api.lastErrorKind === 'network'
                ? `Could not reach the backend — check that the FastAPI server is running and reachable at ${CONFIG.API_BASE_URL}.`
                : 'No live air-quality readings available — check that OPENAQ_API_KEY is set in backend/.env (get a free key at https://explore.openaq.org), then restart the backend. If it is set, OpenAQ may just be rate-limiting or briefly down — try again shortly.';
            document.dispatchEvent(new CustomEvent('layerNotice', {
                detail: { message }
            }));
            return;
        }

        // A real DataSource (not a plain viewer.entities array, which is
        // what this used to be) — needed because .clustering is only
        // available on DataSources, and native clustering is what
        // actually solves whole-earth clutter, the same way it already
        // does for wildfires, rather than the manual per-distance column
        // height scaling this layer used to need.
        const dataSource = new Cesium.CustomDataSource('sensors');

        stations.forEach((s) => {
            if (!s.coordinates) return;

            const pmValue = s.pm25;

            // Standard EPA PM2.5 AQI color spectrum (6 tiers) rather than a
            // coarse 3-bucket split — the actual full color/severity scale.
            let colorHex, tier;
            if (pmValue <= 12) { colorHex = '#22c55e'; tier = 'good'; }
            else if (pmValue <= 35.4) { colorHex = '#eab308'; tier = 'moderate'; }
            else if (pmValue <= 55.4) { colorHex = '#f97316'; tier = 'unhealthy_sensitive'; }
            else if (pmValue <= 150.4) { colorHex = '#ef4444'; tier = 'unhealthy'; }
            else if (pmValue <= 250.4) { colorHex = '#a855f7'; tier = 'very_unhealthy'; }
            else { colorHex = '#7f1d1d'; tier = 'hazardous'; }

            // Single glow-dot billboard glyph, same visual language as
            // every other point-marker layer (wildfires, reports) —
            // replaces the old two-entity column+cap pair. Size nudges up
            // slightly with severity, same "magnitude still reads through
            // size" principle the wildfire flame glyphs use.
            const glyphSize = tier === 'hazardous' || tier === 'very_unhealthy' ? 15 : 11;
            const canvas = this._getGlyphCanvas(`aqi-${colorHex}-${glyphSize}`,
                () => this._createGlowDotCanvas(colorHex, 4, glyphSize));

            const entity = dataSource.entities.add({
                position: Cesium.Cartesian3.fromDegrees(s.coordinates.longitude, s.coordinates.latitude),
                billboard: {
                    image: canvas,
                    verticalOrigin: Cesium.VerticalOrigin.CENTER,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                    disableDepthTestDistance: Number.POSITIVE_INFINITY,
                },
            });

            entity._customData = {
                type: 'air_quality_station',
                name: s.name || "Station",
                lat: s.coordinates.latitude,
                lon: s.coordinates.longitude,
                colorHex,
                details: {
                    "Country": s.country || "Unknown",
                    "City": s.city || "Unknown",
                    "PM2.5": pmValue.toFixed(1) + " µg/m³",
                    "Status": "Online"
                }
            };

            // Only the two worst tiers pulse — same "motion reserved for
            // things that actually warrant attention" principle as
            // wildfires, rather than every station breathing at once.
            if (tier === 'very_unhealthy' || tier === 'hazardous') {
                this._pulsingBillboards.push({
                    billboard: entity.billboard,
                    baseScale: 1,
                    phase: Math.random() * Math.PI * 2,
                    layer: 'sensors',
                });
            }
        });

        // Same native clustering setup as wildfires — solves whole-earth
        // clutter without the manual distance-based column scaling this
        // layer used to rely on.
        dataSource.clustering.enabled = true;
        dataSource.clustering.pixelRange = 40;
        dataSource.clustering.minimumClusterSize = 2;

        dataSource.clustering.clusterEvent.addEventListener((clusteredEntities, cluster) => {
            cluster.label.show = true;
            cluster.label.text = clusteredEntities.length.toString();
            cluster.billboard.show = true;
            cluster.billboard.image = this.createClusterCanvas(clusteredEntities.length);
        });

        this.viewer.dataSources.add(dataSource);
        this.layers.sensors = dataSource;
        this.viewer.scene.requestRender();
    }

    async toggleWindLayer(visible) {
        if (!visible) {
            if (this.layers.wind) {
                this.viewer.dataSources.remove(this.layers.wind);
                this.layers.wind = null;
            }
            return;
        }

        const data = await api.getWind();
        if (!data || !data.features || data.features.length === 0) {
            const message = api.lastErrorKind === 'network'
                ? `Could not reach the backend — check that the FastAPI server is running and reachable at ${CONFIG.API_BASE_URL}.`
                : `The backend is running, but couldn't get real wind data from Open-Meteo right now — try again in a minute.`;
            document.dispatchEvent(new CustomEvent('layerNotice', { detail: { message } }));
            return;
        }

        try {
            const dataSource = await Cesium.GeoJsonDataSource.load(data, { clampToGround: true });
            const entities = dataSource.entities.values;

            for (let i = 0; i < entities.length; i++) {
                const entity = entities[i];
                const speed = entity.properties.speed_kmh ? entity.properties.speed_kmh.getValue() : 0;
                const direction = entity.properties.direction_deg ? entity.properties.direction_deg.getValue() : 0;

                let colorHex, size;
                if (speed < 10) { colorHex = '#7dd3fc'; size = 14; }       // Calm
                else if (speed < 25) { colorHex = '#38bdf8'; size = 18; }  // Moderate
                else if (speed < 45) { colorHex = '#e8c547'; size = 22; }  // Strong
                else { colorHex = '#e6432c'; size = 26; }                  // Severe

                const canvas = this._getGlyphCanvas(`wind-${colorHex}-${size}`,
                    () => this._createWindArrowCanvas(colorHex, size));

                // direction_deg is the direction wind blows FROM (standard
                // meteorological convention — see climate.py's
                // get_wind_geojson docstring). Arrows here point where the
                // wind is blowing TOWARD (direction + 180), which reads
                // more intuitively as a flow indicator. This is a
                // simplified north-up rotation, not a true 3D-globe vector
                // alignment — adequate for the zoom levels this layer is
                // meant to be viewed at, not claimed to be more precise
                // than that.
                const towardBearing = (direction + 180) % 360;

                entity.point = undefined;
                entity.billboard = {
                    image: canvas,
                    rotation: Cesium.Math.toRadians(-towardBearing),
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                    disableDepthTestDistance: Number.POSITIVE_INFINITY,
                };

                entity._customData = { type: 'wind', speed_kmh: speed, direction_deg: direction };
            }

            this.viewer.dataSources.add(dataSource);
            this.layers.wind = dataSource;
            this.viewer.scene.requestRender();
        } catch (e) {
            console.error("Wind layer load error:", e);
        }
    }

    // Interpolates a 0-100 SHI score into a continuous color: red (0) ->
    // yellow (50) -> green (100), rather than 3 hard buckets where e.g. a
    // score of 51 and 79 were previously visually identical.
    _shiScoreToColor(score) {
        const red = Cesium.Color.fromCssColorString('#ef4444');
        const yellow = Cesium.Color.fromCssColorString('#eab308');
        const green = Cesium.Color.fromCssColorString('#22c55e');
        const t = Math.max(0, Math.min(100, score)) / 100;
        const result = new Cesium.Color();
        if (t < 0.5) {
            Cesium.Color.lerp(red, yellow, t / 0.5, result);
        } else {
            Cesium.Color.lerp(yellow, green, (t - 0.5) / 0.5, result);
        }
        return result;
    }

    // Removes the Global SHI country-color heatmap from the globe. Called
    // both here (to clear the previous render before drawing a new one)
    // and from ui.js's switchTab() whenever the global-shi tab isn't the
    // active one — that second call site is what was missing before:
    // this layer was turned on by loadGlobalShi() but had no
    // corresponding teardown when navigating to a different tab, so the
    // country colors stayed visible everywhere until the panel happened
    // to reload. Every other globe layer already had this teardown
    // wired in (see resetActiveLayers() and switchTab()'s snapshotViewer
    // handling) — this was the one gap.
    clearGlobalShiHeatmap() {
        if (this.layers.globalShi) {
            this.viewer.dataSources.remove(this.layers.globalShi);
            this.layers.globalShi = null;
        }
    }

    async renderGlobalShiHeatmap(countries) {
        this.clearGlobalShiHeatmap();

        const boundaries = await api.getCountryBoundaries();
        if (!boundaries || !boundaries.features) return;

        // Real SHI data keyed by ISO alpha-2 code
        const shiByCode = {};
        countries.forEach(c => { shiByCode[c.country_code] = c; });

        const dataSource = await Cesium.GeoJsonDataSource.load(boundaries, {
            stroke: Cesium.Color.fromCssColorString('#0b0e14'),
            strokeWidth: 1,
            fill: Cesium.Color.WHITE.withAlpha(0.05) // default: no-data countries stay near-invisible
        });

        const entities = dataSource.entities.values;
        for (const entity of entities) {
            const code = entity.properties?.['ISO3166-1-Alpha-2']?.getValue();
            const shiInfo = code ? shiByCode[code] : null;

            if (!shiInfo) {
                // No real data for this country — leave it unshaded, never guess.
                if (entity.polygon) entity.polygon.material = Cesium.Color.WHITE.withAlpha(0.03);
                continue;
            }

            const color = this._shiScoreToColor(shiInfo.shi);
            const componentCount = shiInfo.component_count || (shiInfo.components_used || []).length;

            // Coverage/confidence cue: a score backed by only 1 of 4 real
            // sources reads as visually "thinner" (lower fill opacity)
            // than one backed by all 4 — a 1-component and 4-component
            // country no longer look identically confident just because
            // their scores happen to land in the same range.
            const coverageAlpha = 0.3 + (componentCount / 4) * 0.4; // 0.4 (1/4) .. 0.7 (4/4)

            if (entity.polygon) {
                entity.polygon.material = color.withAlpha(coverageAlpha);
                entity.polygon.outline = true;
                entity.polygon.outlineColor = Cesium.Color.WHITE.withAlpha(componentCount >= 4 ? 0.5 : 0.2);
            }

            entity._customData = {
                type: 'shi_country',
                name: shiInfo.country_name,
                details: {
                    "SHI Score": `${shiInfo.shi}/100`,
                    "Risk Level": shiInfo.risk,
                    "Real Data Coverage": `${componentCount} of 4 sources`,
                    "Real Components Used": (shiInfo.components_used || []).join(', '),
                    ...(shiInfo.components?.air_quality ? {"Air Quality": `${shiInfo.components.air_quality.value}/100 (weight ${Math.round(shiInfo.components.air_quality.weight * 100)}%)`} : {}),
                    ...(shiInfo.components?.emissions ? {"Climate/Emissions": `${shiInfo.components.emissions.value}/100 (weight ${Math.round(shiInfo.components.emissions.weight * 100)}%)`} : {}),
                    ...(shiInfo.components?.health ? {"Health Outcomes": `${shiInfo.components.health.value}/100 (weight ${Math.round(shiInfo.components.health.weight * 100)}%)`} : {}),
                    ...(shiInfo.components?.vegetation ? {"Vegetation": `${shiInfo.components.vegetation.value}/100 (weight ${Math.round(shiInfo.components.vegetation.weight * 100)}%)`} : {}),
                    "Real Stations Sampled": shiInfo.station_count
                }
            };
        }

        this.viewer.dataSources.add(dataSource);
        this.layers.globalShi = dataSource;
        this.viewer.scene.requestRender();
    }

    resetView() {
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(
                CONFIG.DEFAULT_COORDINATES.lon,
                CONFIG.DEFAULT_COORDINATES.lat,
                CONFIG.DEFAULT_COORDINATES.height
            ),
            orientation: {
                heading: 0,
                pitch: Cesium.Math.toRadians(-90),
                roll: 0
            },
            duration: 2.0
        });
    }
}
