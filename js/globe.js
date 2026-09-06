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
            vegetationImagery: null, // deprecated: kept only so any stale saved layer reference is a no-op; the raster itself was removed
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
        // Same hex values as the Reports tab's legend dots and Submit
        // form icons (index.html) — these used to be bright named Cesium
        // colors (ORANGERED/PURPLE/LIMEGREEN/etc.) that didn't match
        // anything else in the app's muted instrument palette. Now drawn
        // from colors that already exist elsewhere in the UI (--danger,
        // --warning-amber, --text-muted, the rainfall gradient's two
        // blues, the NDVI bare-ground brown) so the globe pins, the
        // legend, and the form all agree.
        const colorMap = {
            'Fire': Cesium.Color.fromCssColorString('#ef4444'),
            'Pollution': Cesium.Color.fromCssColorString('#ffb800'),
            'Deforestation': Cesium.Color.fromCssColorString('#a16207'),
            'Water': Cesium.Color.fromCssColorString('#38bdf8'),
            'Flooding': Cesium.Color.fromCssColorString('#0ea5e9'),
            'Other': Cesium.Color.fromCssColorString('#64748b')
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
            // Immediately refresh the Insight card's wildfire node (real
            // nearby-fire count) rather than waiting for the next click —
            // same reasoning as the Temperature/Vegetation toggles below.
            if (AppState.selectedLocation) {
                this.loadLocationAnalytics(AppState.selectedLocation.lat, AppState.selectedLocation.lon);
            }
        });
        document.getElementById('layer-temp').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-temp', e.target.checked);
            this.toggleTemperatureAnomalyRaster(e.target.checked);
            // Immediately refresh the currently-open Insight card (if any)
            // rather than leaving it showing whatever it looked like at
            // the time of the last click — flipping this toggle with no
            // visible effect until the next click was confusing (the
            // "Turn on..." hint could keep showing even after toggling
            // ON, simply because nothing re-rendered yet).
            if (AppState.selectedLocation) {
                this.loadLocationAnalytics(AppState.selectedLocation.lat, AppState.selectedLocation.lon);
            }
        });
        document.getElementById('layer-ndvi').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-ndvi', e.target.checked);
            // No globe raster to toggle anymore (removed — see
            // _ndviClassification's comment). This checkbox now solely
            // controls whether the Insight card's vegetation section
            // (value, legend, and History chart) shows — refreshed
            // immediately below rather than waiting for the next click,
            // same reasoning as the Temperature toggle above.
            if (AppState.selectedLocation) {
                this.loadLocationAnalytics(AppState.selectedLocation.lat, AppState.selectedLocation.lon);
            }
        });
        document.getElementById('layer-rainfall').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-rainfall', e.target.checked);
            // No globe raster to toggle anymore (removed — see
            // toggleEnvironmentalLayer's comment). This checkbox now
            // solely controls whether the Insight card's Rainfall History
            // chart shows, refreshed immediately below rather than
            // waiting for the next click — same pattern as Temperature/
            // Vegetation/Wildfires.
            if (AppState.selectedLocation) {
                this.loadLocationAnalytics(AppState.selectedLocation.lat, AppState.selectedLocation.lon);
            }
        });
        document.getElementById('layer-weather').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-weather', e.target.checked);
            // No globe raster to toggle anymore (the 20°-grid rectangle
            // renderer that used to handle this was removed entirely).
            // This does NOT affect weather.js's atmospheric sync
            // (rain/cloud/clear visuals) — that's a separate, camera-
            // driven system left untouched. This checkbox now solely
            // controls whether the Insight card's Weather Conditions
            // node shows, refreshed immediately rather than waiting for
            // the next click.
            if (AppState.selectedLocation) {
                this.loadLocationAnalytics(AppState.selectedLocation.lat, AppState.selectedLocation.lon);
            }
        });
        document.getElementById('layer-sensors').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-sensors', e.target.checked);
            // No globe markers/clusters anymore (removed — see the note
            // above toggleWindLayer). This checkbox now solely gates the
            // real nearest-OpenAQ-station verification line in the
            // Insight card's AQI node, refreshed immediately rather than
            // waiting for the next click.
            if (AppState.selectedLocation) {
                this.loadLocationAnalytics(AppState.selectedLocation.lat, AppState.selectedLocation.lon);
            }
        });
        document.getElementById('layer-wind').addEventListener('change', (e) => {
            AppState.setLayerActive('layer-wind', e.target.checked);
            // No globe arrows anymore (removed — see the note above
            // where toggleWindLayer used to live). This checkbox now
            // solely gates the Insight card's Wind node, refreshed
            // immediately rather than waiting for the next click.
            if (AppState.selectedLocation) {
                this.loadLocationAnalytics(AppState.selectedLocation.lat, AppState.selectedLocation.lon);
            }
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
        }
        
        // Points are gone from most layers now (billboards/rectangles/
        // cylinders instead — see toggleWildfires, and the remaining
        // rectangle-grid layers like wind). Billboard-based entities
        // (wildfires) don't have a queryable Cesium color property the
        // way point/rectangle/cylinder do — their color lives baked
        // into the glyph
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

            // Vegetation History is now gated entirely behind the
            // Vegetation (NDVI) layer toggle — per explicit request, this
            // toggle no longer paints a globe raster (removed, see
            // _ndviClassification's comment above) and instead solely
            // controls whether this per-location history lookup (and the
            // Insight card's vegetation section) runs at all. Skipping the
            // fetch when it's off avoids the extra ~6 real ORNL DAAC calls
            // for people who haven't opted into vegetation analysis.
            const vegetationLayerOn = document.getElementById('layer-ndvi')?.checked;

            // Temperature History follows the exact same pattern, gated
            // behind the Temperature (Anomaly) toggle — this used to be
            // the always-on 6-month sparkline (insightChart); it's now a
            // real yearly comparison (see updateTempHistoryChart in
            // ui.js), so gating it the same way as vegetation avoids
            // firing 6 extra Open-Meteo archive calls for people who
            // haven't opted into temperature analysis either.
            const temperatureLayerOn = document.getElementById('layer-temp')?.checked;

            // Active Wildfires: wildfireRiskData itself (the rule-based
            // fire danger index) is already fetched unconditionally below
            // — the Prediction tab's stat-risk needs it regardless of
            // this toggle. Only the REAL nearby-fire-count lookup
            // (alertSummaryData, via /alerts/summary) is gated here, same
            // reasoning as vegetation/temperature: no reason to make that
            // extra real FIRMS-distance-filter call for people who
            // haven't opted into wildfire analysis for this location.
            const wildfiresLayerOn = document.getElementById('layer-wildfires')?.checked;

            // Global Air Quality (OpenAQ): repurposed — no more globe
            // markers/clusters (removed, see the note above
            // toggleWindLayer). Now solely gates a real NEAREST-station
            // verification line in the Insight card's AQI node, via a
            // DEDICATED endpoint (/aqi-verification, get_nearest_station_
            // verification in alerts.py) — deliberately separate from
            // alertSummaryData above, which picks the worst reading
            // within range rather than the genuinely nearest station.
            // That distinction matters enough (they can disagree by a
            // lot in cities with many stations) that this needed its own
            // real lookup, not a relabeled reuse of the alert data.
            const openAqLayerOn = document.getElementById('layer-sensors')?.checked;

            // Rainfall History follows the same pattern — real annual
            // precipitation totals (see get_rainfall_history in
            // climate.py), only fetched when the Rainfall (Precipitation)
            // toggle is on. This replaces the removed 20°-grid rectangle
            // globe layer (see toggleEnvironmentalLayer's comment).
            const rainfallLayerOn = document.getElementById('layer-rainfall')?.checked;

            // Weather Conditions AND Wind: both reuse api.getWeather() —
            // the exact same /api/weather (OpenWeatherMap) endpoint
            // weather.js already calls for the atmospheric sync, just
            // fetched again here tied to the EXACT clicked coordinates
            // rather than wherever the camera happens to be centered.
            // weather.js's own fetch is camera-driven (fires on
            // camera.moveEnd using the globe's center point), which
            // usually matches the clicked location right after the
            // fly-to animation but isn't guaranteed to if the user pans
            // afterward — a dedicated fetch keeps these cards honestly
            // tied to the location they're actually displaying. Fetched
            // once, shared by both, if EITHER toggle is on — each node
            // is independently gated in ui.js by its own toggle though,
            // so having one doesn't force the other to show.
            const weatherLayerOn = document.getElementById('layer-weather')?.checked;
            const windLayerOn = document.getElementById('layer-wind')?.checked;

            // Predictive AI (Phase 2): fetched alongside the existing calls
            // above rather than blocking on them — these three hit
            // different upstream services (Open-Meteo, MODIS) than the
            // existing calls, so there's no shared rate limit to worry
            // about by running them concurrently.
            const [forecastData, aqiForecastData, wildfireRiskData, ndviHistoryData, tempHistoryData, alertSummaryData, rainfallHistoryData, weatherConditionsData, aqiVerificationData] = await Promise.all([
                api.getWeatherForecast(lat, lon, 7),
                api.getAirQualityForecast(lat, lon, 5),
                api.getWildfireRisk(lat, lon),
                // Vegetation History chart — location-scoped only (never
                // touches the removed global grid); only fetched when the
                // Vegetation (NDVI) toggle is on.
                vegetationLayerOn ? api.getNdviHistory(lat, lon) : Promise.resolve(null),
                // Temperature History chart — only fetched when the
                // Temperature (Anomaly) toggle is on.
                temperatureLayerOn ? api.getTemperatureHistory(lat, lon) : Promise.resolve(null),
                // Real nearby fire count (NASA FIRMS) — only fetched when
                // the Active Wildfires toggle is on.
                wildfiresLayerOn ? api.getAlertSummary(lat, lon, 50) : Promise.resolve(null),
                // Rainfall History (annual totals) — only fetched when
                // the Rainfall (Precipitation) toggle is on.
                rainfallLayerOn ? api.getRainfallHistory(lat, lon) : Promise.resolve(null),
                // Weather Conditions and/or Wind — fetched once if either
                // toggle is on.
                (weatherLayerOn || windLayerOn) ? api.getWeather(lat, lon) : Promise.resolve(null),
                // Nearest-station AQI verification — only fetched when
                // the Global Air Quality toggle is on.
                openAqLayerOn ? api.getAqiVerification(lat, lon, 25) : Promise.resolve(null),
            ]);

            if (ui) {
                ui.updateAnalyticsPanel(climateData, envData, shiData, ndviData);
                ui.updateForecastPanels(forecastData, aqiForecastData, wildfireRiskData);
                ui.updateNdviHistoryChart(ndviHistoryData);
                ui.updateTempHistoryChart(tempHistoryData);
                ui.updateWildfireInsightNode(wildfireRiskData, alertSummaryData);
                ui.updateRainfallHistoryChart(rainfallHistoryData);
                ui.updateWeatherInsightNode(weatherConditionsData);
                ui.updateWindInsightNode(weatherConditionsData);
                ui.updateAqiVerificationNode(aqiVerificationData);
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

    // Note: _createWindArrowCanvas (the wind-arrow glyph, used only by
    // the now-removed global arrow layer — see the note above
    // toggleWindLayer's old location) was removed alongside it.

    // Note: toggleEnvironmentalLayer (the 20°-grid rectangle renderer)
    // used to live here. It handled rainfall (removed — see
    // getRainfallHistory's comment) and, later, weather conditions
    // (removed too, same reasoning: the blocky rectangle grid never
    // looked right on the globe). Weather Conditions is now shown
    // per-location in the Insight card instead (exact real condition,
    // cloud cover %, LIVE/MOCK badge), gated by the same "Weather
    // Conditions" toggle. This is UNRELATED to weather.js's atmospheric
    // sync (camera-driven rain/cloud/clear visual effects on the globe
    // itself) — that system is untouched and keeps working exactly as
    // before; it was never part of this function.

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

    // Real per-location classification, used for the Insight panel's text
    // label. (Previously also shared with the global raster's coloring via
    // _ndviToColor — that raster and its color-mapping helper were removed
    // per explicit request: the 10°-grid blocky tiling never looked right
    // on the globe, and the real per-location value + Vegetation History
    // chart in the Insight card now cover this feature instead. Nothing
    // else referenced _ndviToColor, so it was safe to remove outright.)
    _ndviClassification(value) {
        if (value < 0) return 'Water/Snow/Non-vegetated';
        if (value < 0.2) return 'Sparse';
        if (value < 0.4) return 'Low';
        if (value < 0.6) return 'Moderate';
        return 'Dense';
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
        });
    }

    // Note: toggleSensors (the OpenAQ station marker/cluster renderer)
    // used to live here. Removed per explicit request — the "Global Air
    // Quality (OpenAQ)" toggle is now repurposed to gate a real nearest-
    // station verification line in the Insight card instead (see
    // updateAqiVerificationNode in ui.js), reusing the SAME
    // alertSummaryData already fetched for Wildfires rather than a
    // dedicated station-list fetch. No globe markers/clusters render for
    // this toggle anymore, on purpose.

    // Note: toggleWindLayer (the global arrow-glyph renderer) used to
    // live here. Removed per explicit request — even after fixing its
    // alignedAxis direction bug, individual arrows scattered across a
    // ~20°-step global grid were fundamentally too sparse/small to read
    // as a coherent wind pattern at whole-globe zoom, the same wall every
    // other coarse global grid layer hit tonight. Wind is now shown
    // per-location in the Insight card instead (real speed + a correctly
    // rotated 2D compass arrow — a flat UI icon has no camera-orientation
    // ambiguity the way a 3D globe marker did, so a plain CSS rotation is
    // completely correct there), gated by the same "Wind (direction &
    // speed)" toggle. See updateWindInsightNode in ui.js.

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
