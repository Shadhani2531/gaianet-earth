class UIManager {
    constructor() {
        this.tempChart = null;
        this.precipChart = null;
        this.insightChart = null;

        this.initEventListeners();
        this.initCharts();
        this.initSidebarTabs();
        this.initTimelineEvents();
        this.initSecondaryEvents();
        this.initSearch();
        this.initPanelCollapse();

        // Keep the Tab 4 What-If panel's location/biome display in sync
        // with whatever point is currently selected on the globe, however
        // it was selected (click, search, or a Tab 3 preset chip). Reads
        // from AppState.selectedLocation — the single source of truth —
        // instead of a separately-tracked local copy synced by hand.
        // Also re-renders the legend whenever active layers change, so it
        // always reflects exactly what's currently on the globe.
        AppState.subscribe((state) => {
            if (state.selectedLocation) {
                this.updateSelectedLocationDisplay(state.selectedLocation.lat, state.selectedLocation.lon);
            }
            this.renderDynamicLegend(state.activeLayers);
        });

        // Set default tab
        this.switchTab('earth');
    }

    initPanelCollapse() {
        // Collapse state intentionally persists across tab switches — it's
        // a user layout preference, not per-tab state, so switchTab() never
        // touches these classes.
        const panels = [
            { panelId: 'left-panel', btnId: 'left-panel-collapse', collapseIcon: 'fa-chevron-left', expandIcon: 'fa-chevron-right' },
            { panelId: 'right-panel', btnId: 'right-panel-collapse', collapseIcon: 'fa-chevron-right', expandIcon: 'fa-chevron-left' },
        ];

        panels.forEach(({ panelId, btnId, collapseIcon, expandIcon }) => {
            const panel = document.getElementById(panelId);
            const btn = document.getElementById(btnId);
            if (!panel || !btn) return;

            btn.addEventListener('click', () => {
                const isCollapsed = panel.classList.toggle('collapsed');
                const icon = btn.querySelector('i');
                if (icon) {
                    icon.classList.remove(collapseIcon, expandIcon);
                    icon.classList.add(isCollapsed ? expandIcon : collapseIcon);
                }
                btn.setAttribute('aria-label', isCollapsed ? 'Expand panel' : 'Collapse panel');
                btn.title = isCollapsed ? 'Expand panel' : 'Collapse panel';
            });
        });
    }

    // Single source for what each layer's legend entry looks like.
    // Satellite View is intentionally absent — it's real imagery, not a
    // severity scale, so it never gets a legend entry.
    static LAYER_LEGEND_CONFIG = {
        'layer-temp': { label: 'Temperature (Anomaly)', type: 'gradient', stops: ['#3b82f6', '#eab308', '#ef4444'], words: ['Cold', 'Extreme'] },
        'layer-ndvi': { label: 'Vegetation (NDVI)', type: 'gradient', stops: ['#a16207', '#84cc16', '#14532d'], words: ['Sparse', 'Dense'] },
        'layer-wildfires': { label: 'Active wildfires', type: 'dots', stops: ['#eab308', '#f97316', '#ef4444', '#b91c1c', '#7f1d1d'], words: ['Low', 'Extreme'] },
        'layer-sensors': { label: 'Air quality (PM2.5)', type: 'dots', stops: ['#22c55e', '#eab308', '#f97316', '#ef4444', '#a855f7', '#7f1d1d'], words: ['Good', 'Hazardous'] },
        'layer-rainfall': { label: 'Rainfall (last hour)', type: 'gradient', stops: ['#78716c', '#7dd3fc', '#0ea5e9', '#1e3a8a'], words: ['Dry', 'Heavy'] },
        'layer-weather': { label: 'Cloud cover', type: 'gradient', stops: ['#fde047', '#cbd5e1', '#64748b'], words: ['Clear', 'Overcast'] },
    };

    // Renders only the legend entries for layers currently switched on —
    // replaces the old static legend that always showed NDVI + Temperature
    // regardless of what was actually active on the globe. Hides the whole
    // section entirely when nothing relevant is on, rather than showing an
    // empty box.
    renderDynamicLegend(activeLayers) {
        const container = document.getElementById('layer-legend');
        if (!container) return;

        const activeIds = Object.keys(UIManager.LAYER_LEGEND_CONFIG).filter(id => activeLayers.has(id));

        if (activeIds.length === 0) {
            container.classList.add('hidden');
            container.innerHTML = '';
            return;
        }

        container.classList.remove('hidden');
        container.innerHTML = activeIds.map(id => {
            const cfg = UIManager.LAYER_LEGEND_CONFIG[id];
            const visual = cfg.type === 'gradient'
                ? `<div class="gradient-bar" style="background: linear-gradient(to right, ${cfg.stops.join(', ')})"></div>`
                : `<div class="legend-dots">${cfg.stops.map(c => `<span class="legend-dot" style="background:${c}"></span>`).join('')}</div>`;

            return `
                <div class="legend-item">
                    <span class="legend-label">${cfg.label}</span>
                    ${visual}
                    <div class="legend-values"><span>${cfg.words[0]}</span><span>${cfg.words[1]}</span></div>
                </div>
            `;
        }).join('');
    }

    updateSelectedLocationDisplay(lat, lon) {
        // Tropical zone: roughly the Tropics of Cancer/Capricorn, ±23.5°.
        // (AppState.selectedLocation.isTropical already computes this the
        // same way — recomputed here too since callers may pass raw lat/lon.)
        const isTropical = Math.abs(lat) <= 23.5;

        const locEl = document.getElementById('prediction-location');
        const locText = document.getElementById('prediction-location-text');
        if (locText) {
            locText.innerText = `${lat.toFixed(2)}°, ${lon.toFixed(2)}°`;
        }
        if (locEl) locEl.classList.add('selected');

        const biomeText = document.getElementById('prediction-biome-text');
        if (biomeText) {
            biomeText.innerText = isTropical
                ? 'Biome: Tropical'
                : 'Biome: Non-tropical';
        }
    }

    initSearch() {
        const searchInput = document.querySelector('.search-input');
        const searchTrigger = document.getElementById('search-trigger');
        if (!searchInput) return;

        const runSearch = async () => {
            const query = searchInput.value;
            if (!query) return;

            console.log(`Searching for: ${query}`);
            this.showNeuralScan(`SEARCHING: ${query}`);

            if (window.globeManager) {
                const result = await window.globeManager.searchLocation(query);
                if (!result) {
                    this.showNeuralScan("Location Not Found");
                }
            }
        };

        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') runSearch();
        });

        // The magnifying glass was purely decorative before — clicking it
        // now triggers the same search as pressing Enter.
        if (searchTrigger) {
            searchTrigger.addEventListener('click', runSearch);
        }
    }

    initEventListeners() {
        // "LAB" quick-access button jumps to the What-If Simulator tab
        const scenarioBtn = document.getElementById('scenario-btn');
        if (scenarioBtn) {
            scenarioBtn.addEventListener('click', () => {
                document.querySelector('[data-tab="prediction"]')?.click();
            });
        }

        // NDVI Legend Toggle logic
        const ndviCheckbox = document.getElementById('layer-ndvi');
        if (ndviCheckbox) {
            ndviCheckbox.addEventListener('change', (e) => {
                AppState.setLayerActive('layer-ndvi', e.target.checked);

                const legend = document.getElementById('ndvi-legend-box');
                if (legend) {
                    if (e.target.checked && AppState.activeTab === 'insight') {
                        legend.classList.remove('hidden');
                    } else {
                        legend.classList.add('hidden');
                    }
                }
            });
        }

        // --- Tab 4: What-If Simulator ---
        const deforestSlider = document.getElementById('deforestation-slider');
        const emissionsSlider = document.getElementById('emissions-slider');
        const deforestVal = document.getElementById('deforestation-val');
        const emissionsVal = document.getElementById('emissions-val');

        if (deforestSlider) {
            deforestSlider.addEventListener('input', (e) => {
                deforestVal.innerText = `${e.target.value}%`;
            });
        }
        if (emissionsSlider) {
            emissionsSlider.addEventListener('input', (e) => {
                emissionsVal.innerText = `${e.target.value}%`;
            });
        }

        const runPredictionBtn = document.getElementById('run-prediction-btn');
        if (runPredictionBtn) {
            runPredictionBtn.addEventListener('click', () => this.runPrediction());
        }

        this.startReportsSync();
    }

    // --- RECENT REPORTS FEED ---
    async startReportsSync() {
        this.refreshReportsFeed();
        setInterval(() => this.refreshReportsFeed(), 30000); // Sync every 30s
    }

    async refreshReportsFeed() {
        const reports = await api.getReports();
        if (!reports) return;

        const container = document.getElementById('reports-feed');
        if (!container) return;

        container.innerHTML = reports.reverse().map(r => {
            const ageHours = (Date.now() - new Date(r.timestamp + (r.timestamp.endsWith('Z') ? '' : 'Z')).getTime()) / 3600000;
            const agingClass = ageHours > 72 ? 'report-aged' : '';
            return `
            <div class="report-card animate-in ${agingClass}">
                <div class="report-header">
                    <span class="report-type">${r.incident_type.toUpperCase()}</span>
                    <span class="report-severity">LVL ${r.severity}</span>
                </div>
                ${r.satellite_confirmed ? `
                    <div class="satellite-badge">
                        <i class="fa-solid fa-satellite"></i> Confirmed by NASA FIRMS satellite
                    </div>
                ` : ''}
                <div class="report-desc">${r.description}</div>
                <div class="report-meta">
                    <span><i class="fa-solid fa-location-dot"></i> ${r.lat.toFixed(2)}, ${r.lon.toFixed(2)}</span>
                    <span><i class="fa-solid fa-user"></i> ${r.reporter_name || 'Anonymous'}</span>
                </div>
                <div class="report-meta">
                    <span>${this.formatRelativeTime(r.timestamp)}</span>
                </div>
            </div>
        `;
        }).join('');
    }

    formatRelativeTime(timestamp) {
        const then = new Date(timestamp + (timestamp.endsWith('Z') ? '' : 'Z'));
        const diffMs = Date.now() - then.getTime();
        const diffMin = Math.floor(diffMs / 60000);
        if (diffMin < 1) return 'Just now';
        if (diffMin < 60) return `${diffMin}m ago`;
        const diffHr = Math.floor(diffMin / 60);
        if (diffHr < 24) return `${diffHr}h ago`;
        const diffDay = Math.floor(diffHr / 24);
        return `${diffDay}d ago`;
    }

    async loadGlobalShi() {
        const statusEl = document.getElementById('global-shi-status');
        const rankingEl = document.getElementById('global-shi-ranking');

        const result = await api.getShiGlobal();

        if (!result || result.status === 'missing_api_key') {
            statusEl.classList.remove('hidden');
            statusEl.classList.add('warning');
            statusEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> ${result?.message || 'Could not load global data.'}`;
            rankingEl.innerHTML = '';
            return;
        }

        if (result.status === 'no_data' || !result.countries.length) {
            statusEl.classList.remove('hidden');
            statusEl.classList.add('warning');
            statusEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> ${result.message || 'No real station data available right now.'}`;
            rankingEl.innerHTML = '';
            return;
        }

        statusEl.classList.add('hidden');

        // Render the country heatmap on the globe
        if (window.globeManager) {
            window.globeManager.renderGlobalShiHeatmap(result.countries);
        }

        // Render the ranking list, with each real component that fed the score
        rankingEl.innerHTML = result.countries.map((c, i) => {
            const riskClass = c.shi >= 80 ? 'healthy' : (c.shi >= 50 ? 'moderate' : 'poor');
            const componentIcons = {
                air_quality: '<i class="fa-solid fa-wind" title="Air quality (OpenAQ)"></i>',
                climate_stability: '<i class="fa-solid fa-temperature-half" title="Climate stability (Open-Meteo)"></i>',
                vegetation: '<i class="fa-solid fa-seedling" title="Vegetation (NASA MODIS)"></i>'
            };
            const usedIcons = (c.components_used || []).map(k => componentIcons[k] || '').join(' ');
            return `
                <div class="shi-rank-row" data-code="${c.country_code}">
                    <span class="shi-rank-position">#${i + 1}</span>
                    <span class="shi-rank-name">${c.country_name}</span>
                    <span class="shi-rank-components">${usedIcons}</span>
                    <span class="shi-rank-score ${riskClass}">${c.shi}</span>
                </div>
            `;
        }).join('');
    }

    updateSHIGauge(score) {
        const gauge = document.querySelector('.shi-gauge');
        const value = document.getElementById('shi-value');
        if (value) value.innerText = Math.round(score);
        
        if (gauge) {
            gauge.classList.toggle('shi-gauge-warning', score < 60);
            gauge.classList.toggle('shi-gauge-critical', score < 40);
        }
    }

    async runPrediction() {
        const btn = document.getElementById('run-prediction-btn');
        const resultsDiv = document.getElementById('prediction-results');

        const selected = AppState.selectedLocation;
        if (!selected) {
            this.showNeuralScan("Click a location on the globe first");
            return;
        }

        const lat = selected.lat;
        const lon = selected.lon;
        const isTropical = selected.isTropical;

        const forestLossPct = parseFloat(document.getElementById('deforestation-slider').value);
        const emissionsIncreasePct = parseFloat(document.getElementById('emissions-slider').value);

        if (forestLossPct === 0 && emissionsIncreasePct === 0) {
            this.showNeuralScan("Adjust a slider to run a scenario");
            return;
        }

        const originalBtnHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Projecting…';
        btn.disabled = true;

        const result = await api.getPrediction(lat, lon, { forestLossPct, emissionsIncreasePct, isTropical });

        btn.innerHTML = originalBtnHtml;
        btn.disabled = false;

        if (!result) {
            this.showNeuralScan("Prediction request failed");
            return;
        }

        resultsDiv.classList.remove('hidden');

        // Before/after SHI comparison
        const before = result.shi_before;
        const after = result.shi_after;
        document.getElementById('shi-before-val').innerText = before.shi;
        document.getElementById('shi-before-risk').innerText = before.risk;
        document.getElementById('shi-after-val').innerText = after.shi;
        document.getElementById('shi-after-risk').innerText = after.risk;

        const afterSide = document.getElementById('shi-after-val').closest('.shi-compare-side');
        afterSide.classList.remove('worse', 'better');
        if (after.shi < before.shi) afterSide.classList.add('worse');
        else if (after.shi > before.shi) afterSide.classList.add('better');

        // Also reflect the projected SHI on the main right-panel gauge,
        // so the "what if" outcome is visible at a glance app-wide.
        this.updateSHIGauge(after.shi);

        // Narrative
        document.getElementById('prediction-narrative').innerText = result.narrative;

        // Per-metric change rows with confidence badges + citations
        const changesDiv = document.getElementById('prediction-changes');
        changesDiv.innerHTML = result.changes.map(c => {
            const deltaClass = c.delta > 0 ? 'positive' : (c.delta < 0 ? 'negative' : '');
            const deltaSign = c.delta > 0 ? '+' : '';
            const metricLabel = c.metric.replace(/_/g, ' ');
            return `
                <div class="change-row">
                    <div class="change-row-top">
                        <span class="change-row-metric">${metricLabel}</span>
                        <span class="change-row-delta ${deltaClass}">${deltaSign}${c.delta} ${c.unit}</span>
                    </div>
                    <div class="change-row-basis">
                        <span class="confidence-badge ${c.confidence}">${c.confidence}</span>${c.basis}
                    </div>
                </div>
            `;
        }).join('');

        // Honest data-source note
        const sourceLabel = result.current_data_source === 'live_waqi'
            ? 'Live WAQI + Open-Meteo data for this location.'
            : 'Live data unavailable right now — using a labeled fallback estimate for current conditions.';
        document.getElementById('prediction-data-note').innerText = sourceLabel;
    }

    initSecondaryEvents() {
        // Close Insight Card
        document.getElementById('close-insight').addEventListener('click', () => {
            document.getElementById('insight-card').classList.remove('active');
        });

        // Timeline playback
        const playBtn = document.getElementById('play-btn');
        let isPlaying = false;
        let timelapseInterval;

        playBtn.addEventListener('click', () => {
            isPlaying = !isPlaying;
            playBtn.innerHTML = isPlaying ? '<i class="fa-solid fa-pause"></i>' : '<i class="fa-solid fa-play"></i>';
            
            const slider = document.getElementById('timeline-slider');
            
            if (window.globeManager) {
                window.globeManager.isTimelapsePlaying = isPlaying;
            }

            if (isPlaying) {
                // PAUSE auto-rotation during timelapse (so user can focus on environmental changes)
                if (window.globeManager) {
                    window.globeManager.isAutoRotating = false;
                }

                const speedSelect = document.getElementById('speed-select');
                
                // Start timelapse loop
                timelapseInterval = setInterval(() => {
                    const speed = speedSelect ? parseInt(speedSelect.value) : 1;
                    let currentValue = parseFloat(slider.value);
                    
                    // Increment by a step based on speed
                    currentValue += (0.5 * speed);
                    
                    // Loop back to start (2000) if we reach the end (present year)
                    if (currentValue >= 100) {
                        currentValue = 0; 
                    }
                    
                    slider.value = currentValue;
                    
                    // Trigger the input event so globe.js knows the slider moved
                    slider.dispatchEvent(new Event('input'));
                }, 1000); // Trigger every 1 second to allow tiles to load
            } else {
                // Stop timelapse
                clearInterval(timelapseInterval);
            }
        });

        document.getElementById('timeline-slider').addEventListener('input', (e) => {
            this.updateDateDisplay(e.target.value, 'primary');
        });

        // Minimal Mode Toggle
        const minimalToggle = document.getElementById('minimal-toggle');
        if (minimalToggle) {
            minimalToggle.addEventListener('click', () => {
                document.body.classList.toggle('minimal-mode');
                const icon = minimalToggle.querySelector('i');
                if (document.body.classList.contains('minimal-mode')) {
                    icon.className = 'fa-solid fa-compress';
                } else {
                    icon.className = 'fa-solid fa-expand';
                }
            });
        }

        // Reset Globe View
        const resetBtn = document.getElementById('reset-globe-btn');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                if (window.globeManager) window.globeManager.resetView();
            });
        }

        // --- CITIZEN SCIENCE REPORTING ---
        const reportModal = document.getElementById('report-modal');
        const reportForm = document.getElementById('report-form');
        const severitySlider = document.getElementById('report-severity');

        if (reportModal) {
            document.getElementById('close-report-modal').addEventListener('click', () => {
                reportModal.classList.add('hidden');
            });
        }

        if (severitySlider) {
            severitySlider.addEventListener('input', (e) => {
                document.getElementById('severity-val').innerText = e.target.value;
            });
        }

        if (reportForm) {
            reportForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const btn = reportForm.querySelector('button[type="submit"]');
                const originalText = btn.innerHTML;
                btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> SYNCING...';
                btn.disabled = true;

                const coordsText = document.getElementById('report-coords').innerText;
                const [lat, lon] = coordsText.split(',').map(c => parseFloat(c));
                const selectedType = reportForm.querySelector('input[name="incident-type"]:checked')?.value || 'pollution';

                const reportData = {
                    lat: lat,
                    lon: lon,
                    incident_type: selectedType,
                    severity: parseInt(severitySlider.value),
                    description: document.getElementById('report-description').value,
                    reporter_name: document.getElementById('reporter-name').value.trim() || 'Anonymous',
                    reporter_email: document.getElementById('reporter-email').value.trim() || null
                };

                const result = await api.submitReport(reportData);
                if (result) {
                    reportModal.classList.add('hidden');
                    reportForm.reset();
                    document.getElementById('severity-val').innerText = '3';
                    document.dispatchEvent(new CustomEvent('reportSubmitted', { detail: result }));
                    this.refreshReportsFeed();
                    this.showNeuralScan("Ground-Truth Data Synchronized Successfully");
                } else {
                    alert("Sync failed. Check connection.");
                }
                btn.innerHTML = originalText;
                btn.disabled = false;
            });
        }

        document.addEventListener('openReportModal', (e) => {
            const { lat, lon } = e.detail;
            document.getElementById('report-coords').innerText = `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
            reportModal.classList.remove('hidden');
        });

        // Any layer can report a degraded/no-data state (e.g. missing API
        // key) via this event instead of silently doing nothing.
        document.addEventListener('layerNotice', (e) => {
            this.showToast(e.detail.message);
        });
    }

    showToast(message, durationMs = 6000) {
        const toast = document.getElementById('gn-toast');
        const messageEl = document.getElementById('gn-toast-message');
        if (!toast || !messageEl) return;

        messageEl.innerText = message;
        toast.classList.add('gn-toast-visible');

        clearTimeout(this._toastTimeout);
        this._toastTimeout = setTimeout(() => {
            toast.classList.remove('gn-toast-visible');
        }, durationMs);
    }

    initSidebarTabs() {
        const tabs = document.querySelectorAll('.tab-item');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const targetTab = tab.getAttribute('data-tab');
                // Deactivate all first
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                this.switchTab(targetTab);
            });
        });
    }

    resetActiveLayers() {
        const layerToggleIds = [
            'layer-temp', 'layer-ndvi', 'layer-wildfires', 'layer-sensors',
            'layer-rainfall', 'layer-weather'
        ];
        layerToggleIds.forEach(id => {
            const toggle = document.getElementById(id);
            if (toggle && toggle.checked) {
                toggle.checked = false;
                toggle.dispatchEvent(new Event('change'));
            }
        });
    }

    switchTab(tabName) {
        // AppState is now the single source of truth for "what tab is
        // active" — it also updates the body attribute CSS relies on
        // internally, so nothing else should write that attribute directly.
        AppState.setActiveTab(tabName);

        // 0. Reset: turn OFF every active environmental layer on the globe.
        // Layers are a per-tab investigation tool, not a persistent state —
        // leaving a tab should close whatever it was showing on the globe,
        // the same way you'd expect a real instrument panel to power down.
        // Dispatching a real 'change' event (not just flipping .checked)
        // re-uses each layer's existing toggle handler in globe.js/ui.js,
        // so this stays in sync automatically if a new layer is added later.
        this.resetActiveLayers();

        // Satellite imagery is no longer a general Insight-tab toggle (its
        // imagery-tile reliability made it a poor fit as a user-facing
        // switch) — it's exclusively Tab 3's own built-in historical view
        // now. Driven directly here rather than through a checkbox, since
        // there isn't one anymore: on when entering Tab 3, off everywhere
        // else, every time.
        if (window.globeManager) {
            const isTemporalTab = (tabName === 'temporal' || tabName === 'timeline');
            window.globeManager.toggleSatelliteView(isTemporalTab);

            if (!isTemporalTab) {
                document.getElementById('story-readout')?.classList.add('hidden');
                document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
            }
        }

        // Tab-Specific Visibility Mapping (Refined HUD)
        // Note: the floating search bar (.floating-controller) is
        // intentionally NOT in this map — it should stay visible and
        // usable on every tab, so it's never added to the hide/show sweep.
        const uiElements = {
            'left': document.querySelector('.left-panel'),
            'right': document.querySelector('.right-panel'),
            'bottom': document.querySelector('.bottom-panel'),
            'presets': document.getElementById('timelapse-presets'),
            'insight': document.getElementById('insight-card'),
            'reports': document.getElementById('reports-panel'),
            'globalShi': document.getElementById('global-shi-panel'),
            'prediction': document.getElementById('prediction-panel'),
            'intelligence': document.querySelector('.layer-group'), 
            'shi_gauge': document.querySelector('.shi-gauge-container'),
            'charts': document.querySelectorAll('.chart-container'),
            'ndvi_legend': document.getElementById('ndvi-legend-box')
        };

        // 1. Reset: Hide all main functional blocks
        Object.values(uiElements).forEach(el => { 
            if(el instanceof NodeList) el.forEach(item => item.classList.add('hidden'));
            else if(el) el.classList.add('hidden'); 
        });

        // 2. Tab-Specific Visibility Logic
        switch(tabName) {
            case 'earth':
                // Pure cinematic entry view: no layers, no data panels —
                // just the globe, auto-rotating, free to explore. (Search
                // stays available here too, like on every other tab.)
                break;

            case 'insight':
                if(uiElements.insight) uiElements.insight.classList.remove('hidden');
                if(uiElements.left) {
                    uiElements.left.classList.remove('hidden');
                    if(uiElements.intelligence) uiElements.intelligence.classList.remove('hidden');
                }
                break;

            case 'temporal':
            case 'timeline':
                if(uiElements.bottom) uiElements.bottom.classList.remove('hidden');
                if(uiElements.presets) uiElements.presets.classList.remove('hidden');

                // Satellite is turned on above (unconditionally, for every
                // entry into this tab); NDVI is already off from
                // resetActiveLayers() at the top of this function — neither
                // needs handling here anymore.
                if (window.globeManager) {
                    // Render the timeline's current position immediately —
                    // previously nothing rendered until the user happened to
                    // drag the slider, which combined with the satellite bug
                    // made this tab look completely empty on first entry.
                    const primarySlider = document.getElementById('timeline-slider');
                    if (primarySlider) {
                        window.globeManager.updateTime(primarySlider.value, 'primary');
                    }
                }
                break;

            case 'prediction':
            case 'forecast':
                if(uiElements.left) {
                    uiElements.left.classList.remove('hidden');
                    if(uiElements.prediction) uiElements.prediction.classList.remove('hidden');
                }
                if(uiElements.right) uiElements.right.classList.remove('hidden');
                if(uiElements.shi_gauge) uiElements.shi_gauge.classList.remove('hidden');
                break;

            case 'reports':
                if(uiElements.reports) uiElements.reports.classList.remove('hidden');
                break;

            case 'global-shi':
                if(uiElements.globalShi) uiElements.globalShi.classList.remove('hidden');
                this.loadGlobalShi();
                break;
        }

        console.log(`Command Center HUD Refactored for: ${tabName}`);
    }

    // Neural Scan HUD Effects
    showNeuralScan(locationName) {
        const overlay = document.getElementById('neural-overlay');
        const locLabel = document.getElementById('scan-location');
        if (overlay && locLabel) {
            locLabel.innerText = locationName.toUpperCase();
            overlay.classList.remove('hidden');
            setTimeout(() => this.hideNeuralScan(), 4000); // Auto-hide after transition
        }
    }

    hideNeuralScan() {
        const overlay = document.getElementById('neural-overlay');
        if (overlay) overlay.classList.add('hidden');
    }

    updateDateDisplay(value, type = 'primary') {
        if (!window.globeManager) return;
        const startYear = window.globeManager.TIMELINE_START_YEAR;
        const totalYears = window.globeManager.TIMELINE_END_YEAR - startYear;
        const year = startYear + Math.floor((value / 100) * totalYears);
        const monthIndex = Math.floor(((value / 100) * (totalYears * 12)) % 12);
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        
        if (type === 'primary') {
            document.getElementById('current-date-display').innerText = `${monthNames[monthIndex]} ${year}`;
            const primaryLabel = document.querySelector('#timeline-slider')?.closest('.slider-node')?.querySelector('.slider-label');
            if (primaryLabel) primaryLabel.innerText = `PRIMARY [${year}]`;
        } else {
            const historicalLabel = document.querySelector('#comparison-slider')?.closest('.slider-node')?.querySelector('.slider-label');
            if (historicalLabel) historicalLabel.innerText = `HISTORICAL [${year}]`;
        }
    }

    initTimelineEvents() {
        const primarySlider = document.getElementById('timeline-slider');
        const comparisonSlider = document.getElementById('comparison-slider');
        const splitBtn = document.getElementById('split-screen-btn');
        const comparisonNode = document.getElementById('comparison-slider-node');

        primarySlider.addEventListener('input', (e) => {
            if (window.globeManager) window.globeManager.updateTime(e.target.value, 'primary');
            this.updateTimelineNdviReadout();
        });

        comparisonSlider.addEventListener('input', (e) => {
            if (window.globeManager) window.globeManager.updateTime(e.target.value, 'historical');
        });

        splitBtn.addEventListener('click', () => {
            const isEnabled = comparisonNode.classList.toggle('hidden');
            const splitActive = !isEnabled; // If hidden is toggled off, split is active
            
            splitBtn.classList.toggle('active', splitActive);
            if (window.globeManager) {
                window.globeManager.toggleSplitScreen(splitActive);
            }
        });

        // Curated location presets — guaranteed-good starting points for
        // the timelapse, since a blank globe + slider gives no cue where
        // to look for a dramatic real change. Each one is a guided tour:
        // fly in, set both sliders to the story's real date range, turn on
        // split-screen automatically, and show a hard number backing up
        // the visual — measured live for Amazon (NDVI is a meaningful
        // vegetation metric), cited from real published research for the
        // other three (NDVI doesn't meaningfully measure water volume,
        // urban area, or ice mass, so a live NDVI number there would be
        // precise-looking nonsense).
        document.querySelectorAll('.preset-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const lat = parseFloat(chip.dataset.lat);
                const lon = parseFloat(chip.dataset.lon);
                const height = parseFloat(chip.dataset.height) || 1000000;
                const name = chip.dataset.name;

                document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
                chip.classList.add('active');

                if (window.globeManager) {
                    window.globeManager._programmaticFlight = true;
                    window.globeManager.viewer.camera.flyTo({
                        destination: Cesium.Cartesian3.fromDegrees(lon, lat, height),
                        duration: 2.0,
                        complete: () => { window.globeManager._programmaticFlight = false; }
                    });
                    AppState.setSelectedLocation(lat, lon);

                    const beforeDate = chip.dataset.beforeDate;
                    const afterDate = chip.dataset.afterDate;
                    if (beforeDate && afterDate) {
                        const beforeValue = this.dateToSliderValue(beforeDate);
                        const afterValue = this.dateToSliderValue(afterDate);

                        primarySlider.value = afterValue;
                        window.globeManager.updateTime(afterValue, 'primary');

                        comparisonSlider.value = beforeValue;
                        window.globeManager.updateTime(beforeValue, 'historical');

                        if (comparisonNode.classList.contains('hidden')) {
                            comparisonNode.classList.remove('hidden');
                            splitBtn.classList.add('active');
                            window.globeManager.toggleSplitScreen(true);
                        }

                        this.showStoryReadout(chip, beforeDate, afterDate, lat, lon);
                    }
                }
                this.showNeuralScan(name);
            });
        });

        document.getElementById('story-readout-close')?.addEventListener('click', () => {
            document.getElementById('story-readout').classList.add('hidden');
            document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
        });
    }

    // Converts a "YYYY-MM-01" date string into the 0-100 slider value that
    // produces it via GlobeManager.updateTime()'s inverse formula — keeps
    // the date<->slider-position mapping in one place rather than
    // duplicating the month-math here.
    dateToSliderValue(dateStr) {
        if (!window.globeManager) return 0;
        const [y, m] = dateStr.split('-').map(Number);
        const startYear = window.globeManager.TIMELINE_START_YEAR;
        const totalMonths = (window.globeManager.TIMELINE_END_YEAR - startYear) * 12;
        const monthTotal = (y - startYear) * 12 + (m - 1);
        return Math.max(0, Math.min(100, (monthTotal / totalMonths) * 100));
    }

    async showStoryReadout(chip, beforeDate, afterDate, lat, lon) {
        const panel = document.getElementById('story-readout');
        const title = document.getElementById('story-readout-title');
        const numberEl = document.getElementById('story-readout-number');
        const badge = document.getElementById('story-readout-badge');
        const source = document.getElementById('story-readout-source');
        if (!panel) return;

        title.innerText = chip.dataset.name;
        panel.classList.remove('hidden');
        numberEl.innerText = 'Loading…';
        badge.innerText = '';
        badge.className = 'confidence-badge';
        source.innerText = '';

        if (chip.dataset.statType === 'live-ndvi') {
            const [before, after] = await Promise.all([
                api.getNdviValue(lat, lon, beforeDate),
                api.getNdviValue(lat, lon, afterDate),
            ]);
            if (before && after && typeof before.ndvi === 'number' && typeof after.ndvi === 'number' && before.ndvi > 0) {
                const pctChange = ((after.ndvi - before.ndvi) / before.ndvi) * 100;
                const direction = pctChange < 0 ? 'decline' : 'increase';
                numberEl.innerText = `${Math.abs(pctChange).toFixed(0)}% vegetation ${direction}`;
                badge.innerText = 'measured';
                badge.classList.add('measured');
                source.innerText = `NASA MODIS NDVI, ${beforeDate.slice(0, 7)} vs ${afterDate.slice(0, 7)}`;
            } else {
                numberEl.innerText = 'Live comparison unavailable right now';
                badge.innerText = 'unavailable';
                source.innerText = 'Try again shortly';
            }
        } else {
            numberEl.innerText = chip.dataset.citedText;
            badge.innerText = 'cited';
            badge.classList.add('cited');
            source.innerText = chip.dataset.citedSource;
        }
    }

    // Fetch the real NDVI value for whatever location is currently in
    // view, at the slider's current date, so the timelapse is backed by
    // an actual number alongside the imagery — not just a visual.
    async updateTimelineNdviReadout() {
        if (!window.globeManager) return;
        const lat = AppState.selectedLocation?.lat ?? CONFIG.DEFAULT_COORDINATES.lat;
        const lon = AppState.selectedLocation?.lon ?? CONFIG.DEFAULT_COORDINATES.lon;
        const date = window.globeManager.currentDate;

        const ndviData = await api.getNdviValue(lat, lon, date);
        const readout = document.getElementById('timeline-ndvi-value');
        if (readout && ndviData && ndviData.ndvi !== undefined) {
            readout.innerText = ndviData.ndvi.toFixed(2);
        }
    }

    initCharts() {
        Chart.defaults.color = '#94a3b8';
        Chart.defaults.font.family = 'Inter';

        const ctxTemp = document.getElementById('tempChart').getContext('2d');
        this.tempChart = new Chart(ctxTemp, {
            type: 'line',
            data: {
                labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                datasets: [{
                    label: 'Avg Temp (°C)',
                    data: [0, 0, 0, 0, 0, 0],
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Temperature Trends', color: '#e2e8f0' }
                },
                scales: {
                    y: { grid: { color: 'rgba(255,255,255,0.05)' } },
                    x: { grid: { display: false } }
                }
            }
        });

        const ctxPrecip = document.getElementById('precipChart').getContext('2d');
        this.precipChart = new Chart(ctxPrecip, {
            type: 'bar',
            data: {
                labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                datasets: [{
                    label: 'Rainfall (mm)',
                    data: [0, 0, 0, 0, 0, 0],
                    backgroundColor: '#38bdf8',
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Rainfall Patterns', color: '#e2e8f0' }
                },
                scales: {
                    y: { grid: { color: 'rgba(255,255,255,0.05)' } },
                    x: { grid: { display: false } }
                }
            }
        });

        const ctxInsight = document.getElementById('insightChart').getContext('2d');
        this.insightChart = new Chart(ctxInsight, {
            type: 'line',
            data: {
                labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
                datasets: [{
                    label: 'Trend',
                    data: [0, 0, 0, 0, 0, 0],
                    borderColor: '#38bdf8',
                    tension: 0.4,
                    pointRadius: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { display: false },
                    x: { display: false }
                }
            }
        });
    }

    updateAnalyticsPanel(climateData, envData, shiData, ndviData) {
        console.log("Updating Analytics Panel:", { climateData, envData });
        if (!climateData || !climateData.historical_trends) {
            console.error("No climate data or historical trends available.");
            return;
        }

        // Update Summary
        const location = climateData.location;
        let summaryHtml = `
            <p><i class="fa-solid fa-location-dot"></i> Lat: ${location.lat.toFixed(2)}°, Lon: ${location.lon.toFixed(2)}°</p>
            <p><strong>Anomaly:</strong> <span style="color:${climateData.current_anomaly > 0 ? 'var(--danger)' : 'var(--accent-color)'}">${climateData.current_anomaly}°C</span></p>
        `;
        
        if (shiData) {
            summaryHtml += `
                <div style="margin-top: 10px; padding: 10px; border-radius: 6px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);">
                    <strong>Local SHI:</strong> ${shiData.shi}/100 (${shiData.grade})
                    <p style="font-size: 0.8rem; color: var(--text-secondary); margin: 0;">Status: ${shiData.risk}</p>
                </div>
            `;
        }
        
        document.getElementById('location-summary').innerHTML = summaryHtml;

        // Update Stats with Live Environmental Data
        if (envData) {
            document.getElementById('stat-aqi').innerText = envData.air_quality_index || '--';
            document.getElementById('stat-co2').innerText = envData.co2_ppm || '--';
            
            document.querySelector('#stat-aqi').previousElementSibling.innerText = "Air Quality (AQI)";
            document.querySelector('#stat-co2').previousElementSibling.innerText = "CO₂ (ppm)";
        }

        if (ndviData) {
            document.getElementById('stat-ndvi').innerText = ndviData.ndvi !== undefined ? ndviData.ndvi.toFixed(3) : '--';
            // Optional: change color based on health
            const ndviElem = document.getElementById('stat-ndvi');
            if (ndviData.ndvi > 0.6) ndviElem.style.color = 'var(--success)';
            else if (ndviData.ndvi > 0.2) ndviElem.style.color = 'var(--warning)';
            else ndviElem.style.color = 'var(--danger)';
        }

        // Update Charts
        const history = climateData.historical_trends;
        const labels = history.map(h => {
             const parts = h.month.split('-');
             const d = new Date(parts[0], parts[1]-1 || 0);
             return d.toLocaleString('default', { month: 'short' });
        });
        
        const temps = history.map(h => h.avg_temp_c);
        const rain = history.map(h => h.total_rainfall_mm);

        console.log("New Chart Data:", { labels, temps, rain });

        if (this.tempChart) {
            this.tempChart.data.labels = labels;
            this.tempChart.data.datasets[0].data = temps;
            this.tempChart.update();
        }

        if (this.precipChart) {
            this.precipChart.data.labels = labels;
            this.precipChart.data.datasets[0].data = rain;
            this.precipChart.update();
        }

        // --- IMMERSIVE INSIGHT CARD (SCREEN 2) ---
        this.updateInsightCard(climateData, envData, ndviData, shiData);
    }

    updateInsightCard(climateData, envData, ndviData, shiData) {
        const card = document.getElementById('insight-card');
        const scanOverlay = document.getElementById('insight-scan-overlay');
        const legendBox = document.getElementById('ndvi-legend-box');
        const ndviActive = document.getElementById('layer-ndvi')?.checked;

        // 1. Show scanning animation
        if (scanOverlay) scanOverlay.classList.remove('hidden');
        card.classList.add('active');

        // 2. Delayed data reveal (Neural Sync)
        setTimeout(() => {
            if (scanOverlay) scanOverlay.classList.add('hidden');

            const history = climateData.historical_trends;
            const latest = history[history.length - 1];

            document.getElementById('node-temp').innerText = `${latest.avg_temp_c}°C`;
            document.getElementById('node-precip').innerText = `${latest.total_rainfall_mm}mm`;
            document.getElementById('node-anomaly').innerText = `${climateData.current_anomaly}°C`;

            if (envData) {
                document.getElementById('node-aqi').innerText = envData.air_quality_index ?? '--';
                document.getElementById('node-co2').innerText = envData.co2_ppm ? `${envData.co2_ppm}` : '--';
            }

            if (shiData) {
                document.getElementById('insight-shi-value').innerText = shiData.shi;
                document.getElementById('insight-shi-risk').innerText = shiData.risk;

                const badge = document.getElementById('insight-shi-badge');
                badge.classList.remove('risk-healthy', 'risk-moderate', 'risk-poor');
                if (shiData.shi >= 80) badge.classList.add('risk-healthy');
                else if (shiData.shi >= 50) badge.classList.add('risk-moderate');
                else badge.classList.add('risk-poor');
            }

            if (this.insightChart) {
                this.insightChart.data.datasets[0].data = history.map(h => h.avg_temp_c);
                this.insightChart.update();
            }

            // 3. Dynamic Legend visibility
            if (legendBox) {
                if (ndviActive) legendBox.classList.remove('hidden');
                else legendBox.classList.add('hidden');
            }
        }, 1200);
    }

    showSensorPopup(id, data, x, y) {
        const popup = document.getElementById('sensor-popup');
        const title = document.getElementById('popup-title');
        const content = document.getElementById('popup-content');
        
        let color = data.color || '#38bdf8';
        title.innerHTML = `<i class="fa-solid fa-satellite-dish" style="color:${color}"></i> ${data.name}`;
        
        let html = '';
        for (const [key, value] of Object.entries(data.details)) {
             if (typeof value === 'object') continue; // Avoid stringifying complex objects
             html += `
                <div class="popup-detail">
                    <span class="label">${key.toUpperCase()}</span>
                    <span class="val">${value}</span>
                </div>
             `;
        }
        content.innerHTML = html;
        
        popup.classList.add('active');
        // Simple positioning fix or keep top-right as per CSS
    }
}

const ui = new UIManager();
