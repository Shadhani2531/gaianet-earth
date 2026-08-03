class GlobeManager {
    constructor() {
        // Historical timeline range: MODIS Terra coverage begins Feb 2000,
        // so anything earlier would show today's imagery mislabeled as
        // history rather than real historical imagery. Capped at the
        // present year since there's no future imagery to show either.
        this.TIMELINE_START_YEAR = 2000;
        this.TIMELINE_END_YEAR = new Date().getFullYear();

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
            temperature: null,
            co2: null,
            pollution: null,
            weather: null,
            ndvi: null,
            ndviImagery: null, // Track imagery layer separately
            wildfires: [],
            sensors: [],
            reports: []
        };

        this.initCamera();
        this.initInteraction();
        this.listenForScenarios();
        this.loadUserReports(); // Load existing reports on startup
        
        // Atmospheric Synchronization Engine (ASE)
        this.weather = new WeatherManager(this.viewer);
        
        // Auto-rotation state
        this.isAutoRotating = false;
        this.lastSliderValue = 100; // Baseline for rotation
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
            'Other': Cesium.Color.YELLOW
        };

        const color = colorMap[data.incident_type] || Cesium.Color.WHITE;
        
        const entity = this.viewer.entities.add({
            position: Cesium.Cartesian3.fromDegrees(data.lon, data.lat),
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

        // --- RIGHT CLICK FOR CITIZEN SCIENCE ---
        handler.setInputAction((movement) => {
            const cartesian = this.viewer.camera.pickEllipsoid(movement.position, this.viewer.scene.globe.ellipsoid);
            if (cartesian) {
                const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
                const lat = Cesium.Math.toDegrees(cartographic.latitude);
                const lon = Cesium.Math.toDegrees(cartographic.longitude);
                
                // Dispatch event to UI to open modal
                document.dispatchEvent(new CustomEvent('openReportModal', { 
                    detail: { lat, lon } 
                }));
            }
        }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);

        // Update layers based on UI toggles
        document.getElementById('layer-wildfires').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-wildfires', e.target.checked);
            this.toggleWildfires(e.target.checked);
        });
        document.getElementById('layer-temp').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-temp', e.target.checked);
            this.toggleEnvironmentalLayer(e.target.checked, 'temperature');
        });
        document.getElementById('layer-ndvi').addEventListener('change', (e) => this.toggleEnvironmentalLayer(e.target.checked, 'ndvi'));
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

        // Time Slider Integration.
        // Was looking for id="time-slider" — the actual element is
        // id="timeline-slider". That mismatch meant this threw a
        // TypeError (addEventListener on null) every single time,
        // uncaught, from inside this constructor — which is very likely
        // why the Historical Changes tab never rendered anything.
        const timeSlider = document.getElementById('timeline-slider');
        if (timeSlider) {
            timeSlider.addEventListener('input', (e) => this.updateTime(e.target.value));
        } else {
            console.error('timeline-slider element not found — historical timeline will not respond to dragging.');
        }

        // Level of Detail (LOD) based on camera height
        this.viewer.camera.moveEnd.addEventListener(() => {
            this.applyLOD();
        });
    }

    async toggleSatelliteView(visible) {
        if (!visible) {
            if (this.layers.satellite) {
                this.viewer.imageryLayers.remove(this.layers.satellite_base);
                this.viewer.imageryLayers.remove(this.layers.satellite);
                this.layers.satellite = null;
                this.layers.satellite_base = null;
            }
            return;
        }

        // Idempotent: if satellite is already on, do nothing rather than
        // stacking a second set of imagery layers on top of the first.
        // Without this guard, calling toggleSatelliteView(true) while
        // already visible (e.g. switchTab running twice for the same tab)
        // added duplicate overlapping layers — likely the cause of the
        // "satellite view coming and going" flicker.
        if (this.layers.satellite) {
            return;
        }

        // 1. Seamless Base Layer (Blue Marble) to fill gaps.
        // Switched from the geographic (epsg4326) endpoint to GIBS' Web
        // Mercator (epsg3857) GoogleMapsCompatible endpoint — this matches
        // Cesium's native default tiling scheme exactly (no custom
        // tilingScheme needed), which is the integration path GIBS' own
        // examples recommend. The epsg4326 + GeographicTilingScheme
        // combination from last round only partially matched GIBS' actual
        // tile matrix layout, which is what caused the partial/wedged
        // rendering.
        const baseProvider = new Cesium.WebMapTileServiceImageryProvider({
            url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi',
            layer: 'BlueMarble_NextGeneration',
            style: 'default',
            format: 'image/jpeg',
            tileMatrixSetID: 'GoogleMapsCompatible_Level8',
            maximumLevel: 8,
            credit: 'NASA GIBS (Blue Marble)'
        });

        // 2. High-res Swath Layer (MODIS) for detail
        const imageryProvider = new Cesium.WebMapTileServiceImageryProvider({
            url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi',
            layer: 'MODIS_Terra_CorrectedReflectance_TrueColor',
            style: 'default',
            format: 'image/jpeg',
            tileMatrixSetID: 'GoogleMapsCompatible_Level9',
            maximumLevel: 9,
            credit: 'NASA GIBS (MODIS Terra)'
        });

        this.layers.satellite_base = this.viewer.imageryLayers.addImageryProvider(baseProvider);
        this.layers.satellite = this.viewer.imageryLayers.addImageryProvider(imageryProvider);
        this.viewer.scene.requestRender();
    }

    updateTime(value, type = 'primary') {
        // Range: 2000 (MODIS Terra coverage begins Feb 2000 — anything
        // earlier would just show today's imagery mislabeled as history,
        // not real historical imagery) through the present year (no future
        // imagery exists to show either).
        const startYear = this.TIMELINE_START_YEAR;
        const totalMonths = (this.TIMELINE_END_YEAR - startYear) * 12;
        const currentMonthTotal = Math.floor((value / 100) * totalMonths);
        const year = startYear + Math.floor(currentMonthTotal / 12);
        const month = (currentMonthTotal % 12) + 1;
        const monthStr = month.toString().padStart(2, '0');
        const dateStr = `${year}-${monthStr}-01`;
        
        if (type === 'primary') {
            this.currentDate = dateStr;
            this.rotateToTime(value); // Instant — no debounce, stays smooth while dragging
            if (window.ui) window.ui.updateDateDisplay(value, 'primary');
        } else {
            this.historicalDate = dateStr;
            if (window.ui) window.ui.updateDateDisplay(value, 'historical');
        }

        // Debounce the actual imagery fetch. Dragging the slider fires many
        // 'input' events per second, and each one used to trigger an
        // immediate full GIBS tile refresh — dozens of full reloads while
        // dragging, which is what caused the lag and tile-popping. Waiting
        // until the user pauses for 200ms means the date label and camera
        // rotation stay instantly responsive while dragging, and imagery
        // only loads once, right after they settle on a date.
        clearTimeout(this._imageryRefreshTimeout);
        this._imageryRefreshTimeout = setTimeout(() => {
            this.refreshImageryLayers();
        }, 200);

        console.log(`4D Engine [${type.toUpperCase()}]: ${dateStr}`);
    }

    rotateToTime(sliderValue) {
        // Do not rotate globe during timelapse playback if the user locked it
        if (this.isTimelapsePlaying) return;

        // Calculate the difference from last value
        const delta = sliderValue - this.lastSliderValue;
        if (Math.abs(delta) < 0.1) return; // Ignore micro-jitters
        
        const totalYears = (this.TIMELINE_END_YEAR - this.TIMELINE_START_YEAR);
        const deltaYears = (delta / 100) * totalYears;
        
        // 1 Year = 360 degrees (per user requirement)
        const deltaRotation = Cesium.Math.toRadians(360 * deltaYears);
        
        // Rotate around Z axis (Earth's axis)
        this.viewer.camera.rotate(Cesium.Cartesian3.UNIT_Z, deltaRotation);
        
        this.lastSliderValue = sliderValue;
    }

    async refreshImageryLayers() {
        if (this.layers.ndviImagery) {
            this.refreshNdviImagery(this.currentDate, 
                this.isSplitMode ? Cesium.SplitDirection.RIGHT : Cesium.SplitDirection.NONE, 
                'ndviImagery'
            );
        }
        
        // Also update Satellite layer if active
        if (this.layers.satellite) {
            this.refreshSatelliteImagery(this.currentDate);
        }

        if (this.isSplitMode) {
            this.refreshNdviImagery(this.historicalDate || "2000-02-01", 
                Cesium.SplitDirection.LEFT, 
                'historicalNdvi'
            );
        }
    }

    async refreshNdviImagery(date, splitDir, layerKey) {
        if (this._lastNdviDate === date) return;
        this._lastNdviDate = date;

        const oldLayer = this.layers[layerKey];
        
        const provider = new Cesium.WebMapTileServiceImageryProvider({
            url: 'https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/wmts.cgi',
            layer: 'MODIS_Terra_NDVI_Monthly',
            style: 'default',
            format: 'image/png',
            tileMatrixSetID: '250m',
            maximumLevel: 8,
            tilingScheme: new Cesium.GeographicTilingScheme(),
            parameters: { time: date }
        });
        
        this.layers[layerKey] = this.viewer.imageryLayers.addImageryProvider(provider);
        this.layers[layerKey].alpha = 0.8;
        this.layers[layerKey].splitDirection = splitDir;

        if (oldLayer) {
            if (this._ndviTimeout) clearTimeout(this._ndviTimeout);
            if (this._prevNdviLayer && this.viewer.imageryLayers.contains(this._prevNdviLayer)) {
                this.viewer.imageryLayers.remove(this._prevNdviLayer);
            }
            this._prevNdviLayer = oldLayer;

            this._ndviTimeout = setTimeout(() => {
                if (this.viewer && this.viewer.imageryLayers.contains(oldLayer)) {
                    this.viewer.imageryLayers.remove(oldLayer);
                }
                this._prevNdviLayer = null;
            }, 800);
        }
    }

    async refreshSatelliteImagery(date) {
        if (this._lastSatDate === date) return;
        this._lastSatDate = date;

        const oldLayer = this.layers.satellite;
        
        const provider = new Cesium.WebMapTileServiceImageryProvider({
            url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi',
            layer: 'MODIS_Terra_CorrectedReflectance_TrueColor',
            style: 'default',
            format: 'image/jpeg',
            tileMatrixSetID: 'GoogleMapsCompatible_Level9',
            maximumLevel: 9,
            parameters: { time: date }
        });
        
        this.layers.satellite = this.viewer.imageryLayers.addImageryProvider(provider);

        if (oldLayer) {
            if (this._satTimeout) clearTimeout(this._satTimeout);
            if (this._prevSatLayer && this.viewer.imageryLayers.contains(this._prevSatLayer)) {
                this.viewer.imageryLayers.remove(this._prevSatLayer);
            }
            this._prevSatLayer = oldLayer;

            this._satTimeout = setTimeout(() => {
                if (this.viewer && this.viewer.imageryLayers.contains(oldLayer)) {
                    this.viewer.imageryLayers.remove(oldLayer);
                }
                this._prevSatLayer = null;
            }, 800);
        }
    }

    toggleSplitScreen(enabled) {
        this.isSplitMode = enabled;
        const divider = document.getElementById('split-divider');
        
        if (enabled) {
            divider.classList.remove('hidden');
            this.initSplitDividerInteraction();
            this.refreshImageryLayers();
        } else {
            divider.classList.add('hidden');
            if (this.layers.historicalNdvi) {
                this.viewer.imageryLayers.remove(this.layers.historicalNdvi);
                this.layers.historicalNdvi = null;
            }
            if (this.layers.ndviImagery) this.layers.ndviImagery.splitDirection = Cesium.SplitDirection.NONE;
        }
    }

    initSplitDividerInteraction() {
        const divider = document.getElementById('split-divider');
        let dragging = false;

        const move = (e) => {
            if (!dragging) return;
            const x = e.clientX;
            const width = window.innerWidth;
            const splitPosition = x / width;
            
            divider.style.left = `${x}px`;
            this.viewer.scene.imagerySplitPosition = splitPosition;
        };

        const onDown = () => { dragging = true; };
        const onUp = () => { dragging = false; };

        divider.addEventListener('mousedown', onDown);
        document.addEventListener('mouseup', onUp);
        document.addEventListener('mousemove', move);
    }

    showEntityInfo(entity) {
        const data = entity._customData;
        if (!data) return;
        
        let html = `<h3>${data.type.toUpperCase()} Data</h3>`;
        
        if (data.type === 'wildfire') {
            html += `
                <p><strong>FRP:</strong> ${data.frp.toFixed(1)} MW</p>
                <p><strong>Date:</strong> ${data.acq_date}</p>
                <p><strong>Conf:</strong> ${data.confidence}%</p>
            `;
        } else if (data.type === 'vegetation') {
            html += `<p><strong>NDVI Index:</strong> ${data.value.toFixed(3)}</p>`;
        } else if (data.type === 'climate') {
            html += `<p><strong>Temp Anomaly:</strong> ${data.value.toFixed(2)}°C</p>`;
        }
        
        ui.showSensorPopup(entity.id, {
            name: `${data.type.charAt(0).toUpperCase() + data.type.slice(1)} Insight`,
            details: data,
            color: entity.point ? entity.point.color.getValue().toCssColorString() : '#38bdf8'
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
                });
            }
        });
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
            
            if (ui) ui.updateAnalyticsPanel(climateData, envData, shiData, ndviData);
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
                let color;
                if (frp <= 10) color = Cesium.Color.fromCssColorString('#eab308');   // Low
                else if (frp <= 40) color = Cesium.Color.fromCssColorString('#f97316'); // Moderate
                else if (frp <= 100) color = Cesium.Color.fromCssColorString('#ef4444'); // High
                else if (frp <= 300) color = Cesium.Color.fromCssColorString('#b91c1c'); // Severe
                else color = Cesium.Color.fromCssColorString('#7f1d1d');                 // Extreme

                entity.point = {
                    pixelSize: Math.min(12, 6 + frp/50),
                    color: color.withAlpha(0.8),
                    outlineColor: Cesium.Color.BLACK,
                    outlineWidth: 1,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                    disableDepthTestDistance: Number.POSITIVE_INFINITY 
                };
                
                // Add custom data for tooltips
                entity._customData = {
                    type: 'wildfire',
                    frp: frp,
                    acq_date: entity.properties.acq_date ? entity.properties.acq_date.getValue() : 'N/A',
                    confidence: entity.properties.confidence ? entity.properties.confidence.getValue() : 0,
                    lat: Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(entity.position.getValue()).latitude),
                    lon: Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(entity.position.getValue()).longitude)
                };
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
        const fetchers = {
            ndvi: () => api.getVegetation(),
            temperature: () => api.getClimate(),
            rainfall: () => api.getRainfall(),
            weather: () => api.getWeatherConditions(),
        };
        const labels = {
            ndvi: 'vegetation', temperature: 'temperature',
            rainfall: 'rainfall', weather: 'weather conditions',
        };
        const data = await fetchers[type]();
        const label = labels[type];

        if (!data || !data.features || data.features.length === 0) {
            document.dispatchEvent(new CustomEvent('layerNotice', {
                detail: { message: `Could not load ${label} data — check that the backend server is running.` }
            }));
            return;
        }

        try {
            const dataSource = await Cesium.GeoJsonDataSource.load(data, { clampToGround: true });
            const entities = dataSource.entities.values;
            for (let i = 0; i < entities.length; i++) {
                const entity = entities[i];
                const val = entity.properties.value ? entity.properties.value.getValue() : 0;

                let color;
                if (type === 'ndvi') {
                    // Sparse (brown) -> mid (yellow-green) -> dense (dark green)
                    if (val < 0.2) color = Cesium.Color.fromCssColorString('#a16207');
                    else if (val < 0.5) color = Cesium.Color.fromCssColorString('#84cc16');
                    else color = Cesium.Color.fromCssColorString('#14532d');
                } else if (type === 'temperature') {
                    // Blue -> Yellow -> Red (Anomaly)
                    if (val < 0) color = Cesium.Color.BLUE;
                    else if (val < 1.0) color = Cesium.Color.YELLOW;
                    else color = Cesium.Color.RED;
                } else if (type === 'rainfall') {
                    // Dry -> light rain -> heavy rain (mm in the last hour)
                    if (val <= 0) color = Cesium.Color.fromCssColorString('#78716c'); // Dry
                    else if (val < 2.5) color = Cesium.Color.fromCssColorString('#7dd3fc'); // Light
                    else if (val < 10) color = Cesium.Color.fromCssColorString('#0ea5e9'); // Moderate
                    else color = Cesium.Color.fromCssColorString('#1e3a8a'); // Heavy
                } else {
                    // Weather conditions: cloud cover %, clear -> overcast
                    if (val < 25) color = Cesium.Color.fromCssColorString('#fde047'); // Clear
                    else if (val < 60) color = Cesium.Color.fromCssColorString('#cbd5e1'); // Partly cloudy
                    else color = Cesium.Color.fromCssColorString('#64748b'); // Overcast
                }

                entity.point = {
                    pixelSize: 6,
                    color: color.withAlpha(0.7),
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
                };
                
                entity._customData = {
                    type: label,
                    value: val,
                    lat: Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(entity.position.getValue()).latitude),
                    lon: Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(entity.position.getValue()).longitude)
                };
            }

            this.viewer.dataSources.add(dataSource);
            this.layers[type] = dataSource;
            this.viewer.scene.requestRender();
        } catch (e) {
            console.error(`Error loading layer ${type}:`, e);
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
             
             // Intensify Temperature Layer
             if (this.layers.temperature) {
                 this.layers.temperature.entities.values.forEach(entity => {
                     if (entity.point) {
                         const base = entity._customData.value;
                         const current = base + tempOffset;
                         
                         let color = Cesium.Color.BLUE;
                         if (current > 1.5) color = Cesium.Color.RED;
                         else if (current > 0.5) color = Cesium.Color.ORANGE;
                         else if (current > 0) color = Cesium.Color.YELLOW;
                         
                         entity.point.color = color.withAlpha(0.7);
                         entity.point.pixelSize = 6 + (current * 4);
                     }
                 });
             }

             // Intensify NDVI Layer
             if (this.layers.ndvi) {
                 this.layers.ndvi.entities.values.forEach(entity => {
                     if (entity.point) {
                         const base = entity._customData.value;
                         const factor = 1.0 + (rainOffset / 100);
                         const current = base * factor;

                         let color = Cesium.Color.fromCssColorString('#14532d');
                         if (current < 0.2) color = Cesium.Color.fromCssColorString('#a16207');
                         else if (current < 0.5) color = Cesium.Color.fromCssColorString('#84cc16');
                         
                         entity.point.color = color.withAlpha(0.7);
                     }
                 });
             }
        });
    }

    async toggleSensors(visible) {
        if (!visible) {
            this.layers.sensors.forEach(e => this.viewer.entities.remove(e));
            this.layers.sensors = [];
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
            document.dispatchEvent(new CustomEvent('layerNotice', {
                detail: { message: 'No live air-quality readings available right now — check that OPENAQ_API_KEY is set in backend/.env, or try again shortly.' }
            }));
            return;
        }

        this.viewer.entities.suspendEvents();

        stations.forEach((s) => {
            if (!s.coordinates) return;

            const pmValue = s.pm25;

            // Standard EPA PM2.5 AQI color spectrum (6 tiers) rather than a
            // coarse 3-bucket split — this is the actual "full color
            // gradient/severity scale" the toggle should show.
            let color;
            if (pmValue <= 12) color = Cesium.Color.fromCssColorString('#22c55e');      // Good
            else if (pmValue <= 35.4) color = Cesium.Color.fromCssColorString('#eab308'); // Moderate
            else if (pmValue <= 55.4) color = Cesium.Color.fromCssColorString('#f97316'); // Unhealthy (sensitive)
            else if (pmValue <= 150.4) color = Cesium.Color.fromCssColorString('#ef4444'); // Unhealthy
            else if (pmValue <= 250.4) color = Cesium.Color.fromCssColorString('#a855f7'); // Very Unhealthy
            else color = Cesium.Color.fromCssColorString('#7f1d1d');                       // Hazardous

            const entity = this.viewer.entities.add({
                position: Cesium.Cartesian3.fromDegrees(s.coordinates.longitude, s.coordinates.latitude),
                point: {
                    pixelSize: 6,
                    color: color,
                    outlineColor: Cesium.Color.BLACK,
                    outlineWidth: 1,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
                }
            });

            entity._customData = {
                type: 'air_quality_station',
                name: s.name || "Station",
                lat: s.coordinates.latitude,
                lon: s.coordinates.longitude,
                details: {
                    "Country": s.country || "Unknown",
                    "City": s.city || "Unknown",
                    "PM2.5": pmValue.toFixed(1) + " µg/m³",
                    "Status": "Online"
                }
            };

            this.layers.sensors.push(entity);
        });

        this.viewer.entities.resumeEvents();
        this.viewer.scene.requestRender();
    }

    async renderGlobalShiHeatmap(countries) {
        // Clear any previous heatmap layer
        if (this.layers.globalShi) {
            this.viewer.dataSources.remove(this.layers.globalShi);
            this.layers.globalShi = null;
        }

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

            let color = Cesium.Color.fromCssColorString('#ef4444'); // Poor
            if (shiInfo.shi >= 80) color = Cesium.Color.fromCssColorString('#22c55e'); // Healthy
            else if (shiInfo.shi >= 50) color = Cesium.Color.fromCssColorString('#eab308'); // Moderate

            if (entity.polygon) {
                entity.polygon.material = color.withAlpha(0.55);
                entity.polygon.outline = true;
                entity.polygon.outlineColor = Cesium.Color.WHITE.withAlpha(0.3);
            }

            entity._customData = {
                type: 'shi_country',
                name: shiInfo.country_name,
                details: {
                    "SHI Score": `${shiInfo.shi}/100`,
                    "Risk Level": shiInfo.risk,
                    "Real Components Used": (shiInfo.components_used || []).join(', '),
                    ...(shiInfo.components?.air_quality ? {"Air Quality Component": `${shiInfo.components.air_quality.value}/100`} : {}),
                    ...(shiInfo.components?.climate_stability ? {"Climate Component": `${shiInfo.components.climate_stability.value}/100`} : {}),
                    ...(shiInfo.components?.vegetation ? {"Vegetation Component": `${shiInfo.components.vegetation.value}/100`} : {}),
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
