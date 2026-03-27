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

        // Disable default browser context menu on the globe
        document.getElementById('cesiumContainer').addEventListener('contextmenu', (e) => e.preventDefault());

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
            shi: [],
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

        // Listen for new reports submitted
        document.addEventListener('reportSubmitted', (e) => {
            this.addReportEntity(e.detail);
        });
    }

    async searchLocation(query) {
        try {
            // Use Cesium Ion Geocoder as primary
            const geocoder = new Cesium.IonGeocoderService();
            const results = await geocoder.geocode(query);
            
            if (results && results.length > 0) {
                const destination = results[0].destination;
                const name = results[0].displayName;
                
                this.flyToDestination(destination, name);
                return true;
            }
            return false;
        } catch (error) {
            console.error("Geocoding failed:", error);
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
        const rotate = () => {
            if (!this.isAutoRotating) return;
            
            const now = Date.now();
            const delta = (now - this.lastTime) / 1000;
            this.lastTime = now;
            
            this.viewer.camera.rotate(Cesium.Cartesian3.UNIT_Z, 0.05 * delta);
            requestAnimationFrame(rotate);
        };
        this.lastTime = Date.now();
        requestAnimationFrame(rotate);
    }

    initCamera() {
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(
                CONFIG.DEFAULT_COORDINATES.lon,
                CONFIG.DEFAULT_COORDINATES.lat,
                CONFIG.DEFAULT_COORDINATES.height
            ),
            duration: 3.0 // Cinematic fly-in
        });
    }

    initInteraction() {
        const handler = new Cesium.ScreenSpaceEventHandler(this.viewer.scene.canvas);
        
        handler.setInputAction((movement) => {
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
        document.getElementById('layer-wildfires').addEventListener('change', (e) => this.toggleWildfires(e.target.checked));
        document.getElementById('layer-temp').addEventListener('change', (e) => this.toggleEnvironmentalLayer(e.target.checked, 'temperature'));
        document.getElementById('layer-ndvi').addEventListener('change', (e) => this.toggleEnvironmentalLayer(e.target.checked, 'ndvi'));
        document.getElementById('layer-satellite').addEventListener('change', (e) => this.toggleSatelliteView(e.target.checked));
        document.getElementById('layer-sensors').addEventListener('change', (e) => this.toggleSensors(e.target.checked));
        document.getElementById('layer-shi').addEventListener('change', (e) => this.toggleShi(e.target.checked));

        // Time Slider Integration
        const timeSlider = document.getElementById('time-slider');
        timeSlider.addEventListener('input', (e) => this.updateTime(e.target.value));

        // Level of Detail (LOD) based on camera height
        this.viewer.camera.moveEnd.addEventListener(() => {
            this.applyLOD();
        });

        this.renderLegends();
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

        // 1. Seamless Base Layer (Blue Marble) to fill gaps
        const baseProvider = new Cesium.WebMapTileServiceImageryProvider({
            url: 'https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/wmts.cgi',
            layer: 'BlueMarble_NextGeneration',
            style: 'default',
            format: 'image/jpeg',
            tileMatrixSetID: '500m',
            maximumLevel: 8,
            credit: 'NASA GIBS (Blue Marble)'
        });

        // 2. High-res Swath Layer (MODIS) for detail
        const imageryProvider = new Cesium.WebMapTileServiceImageryProvider({
            url: 'https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/wmts.cgi',
            layer: 'MODIS_Terra_CorrectedReflectance_TrueColor',
            style: 'default',
            format: 'image/jpeg',
            tileMatrixSetID: '250m',
            maximumLevel: 9,
            credit: 'NASA GIBS (MODIS Terra)'
        });

        this.layers.satellite_base = this.viewer.imageryLayers.addImageryProvider(baseProvider);
        this.layers.satellite = this.viewer.imageryLayers.addImageryProvider(imageryProvider);
        this.viewer.scene.requestRender();
    }

    updateTime(value, type = 'primary') {
        // Expanded Range: 1984 through 2030 (approx 550 months)
        const startYear = 1984;
        const totalMonths = (2030 - 1984) * 12;
        const currentMonthTotal = Math.floor((value / 100) * totalMonths);
        const year = startYear + Math.floor(currentMonthTotal / 12);
        const month = (currentMonthTotal % 12) + 1;
        const monthStr = month.toString().padStart(2, '0');
        const dateStr = `${year}-${monthStr}-01`;
        
        if (type === 'primary') {
            this.currentDate = dateStr;
            this.rotateToTime(value);
            if (window.ui) window.ui.updateDateDisplay(value, 'primary');
        } else {
            this.historicalDate = dateStr;
            if (window.ui) window.ui.updateDateDisplay(value, 'historical');
        }

        this.refreshImageryLayers();
        console.log(`4D Engine [${type.toUpperCase()}]: ${dateStr}`);
    }

    rotateToTime(sliderValue) {
        // Calculate the difference from last value
        const delta = sliderValue - this.lastSliderValue;
        if (Math.abs(delta) < 0.1) return; // Ignore micro-jitters
        
        const totalYears = (2030 - 1984);
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
        
        if (this.isSplitMode) {
            this.refreshNdviImagery(this.historicalDate || "1984-01-01", 
                Cesium.SplitDirection.LEFT, 
                'historicalNdvi'
            );
        }
    }

    async refreshNdviImagery(date, splitDir, layerKey) {
        if (this.layers[layerKey]) {
            this.viewer.imageryLayers.remove(this.layers[layerKey]);
        }
        
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

    renderLegends() {
        const container = document.getElementById('layer-legend');
        if (!container) return;
        
        container.innerHTML = `
            <div class="legend-item">
                <span class="legend-label">Vegetation (NDVI)</span>
                <div class="gradient-bar" style="background: linear-gradient(to right, #a16207, #84cc16, #14532d)"></div>
                <div class="legend-values"><span>Arid</span><span>Dense</span></div>
            </div>
            <div class="legend-item">
                <span class="legend-label">Temperature Anomaly</span>
                <div class="gradient-bar" style="background: linear-gradient(to right, #0000ff, #ffff00, #ff0000)"></div>
                <div class="legend-values"><span>Cold</span><span>Extreme</span></div>
            </div>
        `;
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
            // Screen 2: Top-Down Camera View (No Tilt as per User Request)
            this.viewer.camera.flyTo({
                destination: Cesium.Cartesian3.fromDegrees(lon, lat, 2000000), 
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
        if(!data) return;

        try {
            const dataSource = await Cesium.GeoJsonDataSource.load(data, {
                clampToGround: true
            });

            const entities = dataSource.entities.values;
            for (let i = 0; i < entities.length; i++) {
                const entity = entities[i];
                const frp = entity.properties.frp ? entity.properties.frp.getValue() : 10;
                
                // Normalizing color Yellow -> Orange -> Red
                let color = Cesium.Color.YELLOW;
                if (frp > 100) color = Cesium.Color.RED;
                else if (frp > 40) color = Cesium.Color.ORANGE;

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
        if (type === 'ndvi') {
            return this.toggleNdviSatellite(visible);
        }

        if (!visible) {
            if (this.layers[type]) {
                this.viewer.dataSources.remove(this.layers[type]);
                this.layers[type] = null;
            }
            return;
        }

        const data = await api.getClimate();
        if(!data) return;

        try {
            const dataSource = await Cesium.GeoJsonDataSource.load(data, { clampToGround: true });
            const entities = dataSource.entities.values;
            for (let i = 0; i < entities.length; i++) {
                const entity = entities[i];
                const val = entity.properties.value ? entity.properties.value.getValue() : 0;
                
                // Blue -> Yellow -> Red (Anomaly)
                let color;
                if (val < 0) color = Cesium.Color.BLUE;
                else if (val < 1.0) color = Cesium.Color.YELLOW;
                else color = Cesium.Color.RED;

                entity.point = {
                    pixelSize: 6,
                    color: color.withAlpha(0.7),
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
                };
                
                entity._customData = {
                    type: 'climate',
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

    async toggleNdviSatellite(visible) {
        if (!visible) {
            if (this.layers.ndviImagery) {
                this.viewer.imageryLayers.remove(this.layers.ndviImagery);
                this.layers.ndviImagery = null;
            }
            return;
        }

        if (!this.currentDate) this.currentDate = '2024-01-01';
        this.refreshNdviImagery();
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

        // Fetch OpenAQ real global stations
        const stations = await api.getStations();
        if (!stations || !stations.length) return;

        this.viewer.entities.suspendEvents();

        stations.forEach((s) => {
            if (!s.coordinates) return;

            let pmValue = 0;
            if (s.parameters) {
                s.parameters.forEach(p => {
                    if ((p.parameter === 'pm25' || p.parameter === 'pm10') && p.lastValue) {
                        pmValue = Math.max(pmValue, p.lastValue);
                    }
                });
            }

            let color = Cesium.Color.fromCssColorString('#22c55e'); // Green
            if (pmValue >= 50 && pmValue <= 100) color = Cesium.Color.fromCssColorString('#eab308'); // Yellow
            else if (pmValue > 100) color = Cesium.Color.fromCssColorString('#ef4444'); // Red

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
                name: s.name || s.location || "Station",
                lat: s.coordinates.latitude,
                lon: s.coordinates.longitude,
                details: {
                    "Country": s.country || "Unknown",
                    "City": s.city || "Unknown",
                    "PM Level": pmValue.toFixed(2) + " µg/m³",
                    "Status": "Online"
                }
            };

            this.layers.sensors.push(entity);
        });

        this.viewer.entities.resumeEvents();
        this.viewer.scene.requestRender();
    }

    async toggleShi(visible) {
        if (!visible) {
            if (this.layers.shi) {
                this.layers.shi.forEach(e => this.viewer.entities.remove(e));
            }
            this.layers.shi = [];
            return;
        }

        const stations = await api.getShiIndiaLive();
        if (!stations || !stations.length) return;

        this.viewer.entities.suspendEvents();
        
        for (const data of stations) {
            let color = Cesium.Color.fromCssColorString('#ef4444'); // Red
            if (data.shi >= 80) color = Cesium.Color.fromCssColorString('#22c55e'); // Green
            else if (data.shi >= 50) color = Cesium.Color.fromCssColorString('#eab308'); // Yellow

            let radius = 150000;
            if (data.shi >= 80) radius = 100000;
            else if (data.shi < 50) radius = 200000;

            const entity = this.viewer.entities.add({
                position: Cesium.Cartesian3.fromDegrees(data.lon, data.lat),
                ellipse: {
                    semiMinorAxis: radius,
                    semiMajorAxis: radius,
                    material: color.withAlpha(0.6),
                    outline: true,
                    outlineColor: Cesium.Color.WHITE,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
                }
            });
            
            entity._customData = {
                type: 'shi_region',
                name: data.city || "India Station",
                lat: data.lat,
                lon: data.lon,
                details: {
                    "Live PM2.5": data.aqi.toFixed(1) + " µg/m³",
                    "SHI Score": Math.round(data.shi) + "/100",
                    "Risk Level": data.shi >= 80 ? 'Healthy' : (data.shi >= 50 ? 'Moderate' : 'Poor')
                }
            };
            this.layers.shi.push(entity);
        }
        
        this.viewer.entities.resumeEvents();
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
