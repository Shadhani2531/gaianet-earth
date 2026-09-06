class UIManager {
    constructor() {
        this.tempChart = null;
        this.precipChart = null;
        this.tempHistoryChart = null;
        this.ndviHistoryChart = null;
        this.rainfallHistoryChart = null;
        this.aqiForecastChart = null;

        this.initEventListeners();
        this.initCharts();
        this.initSidebarTabs();
        this.initTimelineEvents();
        this.initSecondaryEvents();
        this.initSearch();
        this.initPanelCollapse();
        this.initShiSectionToggles();

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
            { panelId: 'global-shi-panel', btnId: 'close-global-shi', collapseIcon: 'fa-chevron-right', expandIcon: 'fa-chevron-left' },
            { panelId: 'reports-panel', btnId: 'close-reports-panel', collapseIcon: 'fa-chevron-right', expandIcon: 'fa-chevron-left' },
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

    // Collapsible sections inside the Global SHI panel (Legend &
    // Methodology, Rankings) — the globe itself is never touched by
    // this, same as the Insight tab's panel doesn't affect the globe.
    initShiSectionToggles() {
        const sections = ['shi-legend', 'shi-ranking'];
        sections.forEach(id => {
            const toggle = document.getElementById(`${id}-toggle`);
            const section = document.getElementById(`${id}-section`);
            if (!toggle || !section) return;

            toggle.addEventListener('click', () => {
                const isCollapsed = section.classList.toggle('collapsed');
                toggle.setAttribute('aria-expanded', String(!isCollapsed));
            });
        });
    }

    // Global Ground-Truth panel's two sub-tabs: Info (legend + live feed)
    // and Submit Report (the form, moved in from the old floating
    // #report-modal). Unlike the SHI panel's independently-collapsible
    // sections, these are mutually exclusive — true tabs, only one body
    // visible at a time — since showing the feed and the submission form
    // together in a narrow sidebar doesn't read well.
    initReportsSubtabs() {
        document.querySelectorAll('.reports-subtab-btn').forEach(btn => {
            btn.addEventListener('click', () => this.switchReportsSubtab(btn.dataset.subtab));
        });
    }

    switchReportsSubtab(subtab) {
        document.querySelectorAll('.reports-subtab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.subtab === subtab);
        });
        document.querySelectorAll('.reports-subtab-body').forEach(body => {
            body.classList.toggle('hidden', body.dataset.subtabBody !== subtab);
        });

        // Populate the coordinate readout at the moment the form becomes
        // visible — same "use whatever's currently selected" behavior
        // the old openReportModal event provided, just triggered by a
        // sub-tab switch instead of a modal open.
        if (subtab === 'submit') {
            const loc = AppState.selectedLocation ?? CONFIG.DEFAULT_COORDINATES;
            const coordsEl = document.getElementById('report-coords');
            if (coordsEl) coordsEl.innerText = `${loc.lat.toFixed(4)}, ${loc.lon.toFixed(4)}`;
        }
    }

    // Single registry of "things that must never leak between tabs."
    // switchTab() runs every entry here unconditionally on every call,
    // then its switch-case re-enables exactly what the target tab needs
    // (e.g. case 'global-shi' calls loadGlobalShi(), which re-renders the
    // heatmap this teardown just cleared). Add new tab-specific globe
    // layers or transient UI state here, not as a one-off conditional in
    // switchTab — that's what let the Global SHI heatmap go untorn-down
    // for as long as it did.
    static TAB_SCOPED_TEARDOWN = {
        temporalSnapshot: () => {
            document.getElementById('story-readout')?.classList.add('hidden');
            document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
            window.snapshotViewer?.hide();
        },
        globalShiHeatmap: () => {
            window.globeManager?.clearGlobalShiHeatmap();
        },
        reportMarkers: () => {
            window.globeManager?.setReportsVisible(false);
        },
    };

    // Single source for what each layer's legend entry looks like.
    // Satellite View is intentionally absent — it's real imagery, not a
    // severity scale, so it never gets a legend entry.
    static LAYER_LEGEND_CONFIG = {
        'layer-temp': { label: 'Temperature Anomaly (vs. seasonal baseline)', type: 'gradient', stops: ['#08306b', '#6bafd6', '#e6e6e6', '#fd8d3c', '#a50f15'], words: ['-4°C', '-2°C', '0°C', '+2°C', '+4°C'], subLabel: 'Colder ←—— Average ——→ Warmer' },
        'layer-ndvi': { label: 'Vegetation (NDVI, NASA MODIS)', type: 'gradient', stops: ['#a16207', '#bebe28', '#84cc16', '#228b22', '#0a4114'], words: ['0.0', '0.2', '0.4', '0.6', '1.0'], subLabel: 'Bare/Sparse ←—— Low —— Moderate ——→ Dense' },
        'layer-wildfires': { label: 'Active wildfires', type: 'dots', stops: ['#f5b942', '#f2792e', '#e6432c', '#b31f1f', '#6e0f0f'], words: ['Low', 'Extreme (pulsing)'] },
        // 'layer-sensors' (Global Air Quality / OpenAQ) intentionally has
        // no entry here anymore — it no longer renders anything on the
        // globe (repurposed for Insight card verification only, see
        // updateAqiVerificationNode), so there's no color scale to
        // explain in this legend.
        'layer-rainfall': { label: 'Rainfall (last hour)', type: 'gradient', stops: ['#78716c', '#7dd3fc', '#0ea5e9', '#1e3a8a'], words: ['Dry', 'Heavy'] },
        'layer-weather': { label: 'Cloud cover', type: 'gradient', stops: ['#fde047', '#cbd5e1', '#64748b'], words: ['Clear', 'Overcast'] },
        'layer-wind': { label: 'Wind speed — arrow points downwind', type: 'gradient', stops: ['#7dd3fc', '#38bdf8', '#e8c547', '#e6432c'], words: ['Calm', 'Severe'] },
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
                    <div class="legend-values">${cfg.words.map(w => `<span>${w}</span>`).join('')}</div>
                    ${cfg.subLabel ? `<div class="legend-sublabel">${cfg.subLabel}</div>` : ''}
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
        // Atmospheric Sync Engine (js/weather.js) dispatches this every time
        // it re-syncs rain/snow/cloud visuals to the globe center. The
        // payload's `status` is "success" (real OpenWeatherMap) or "mock"
        // (deterministic placeholder used when OPENWEATHERMAP_API_KEY isn't
        // set) — surface that honestly instead of showing weather-driven
        // visuals with no indication they might not be real.
        document.addEventListener('weatherSynced', (e) => this.updateAseStatusBadge(e.detail));

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

        // Map heatmap: every country with real data from any source —
        // full coverage, single-component territories included, since a
        // colored polygon in the right place isn't misleading the way a
        // #1 ranking slot would be.
        if (window.globeManager) {
            window.globeManager.renderGlobalShiHeatmap(result.countries);
        }

        // Ranked list: restricted server-side to countries with >= 2 real
        // components (see shi_composite.py's MIN_COMPONENTS_FOR_RANKING) —
        // a single-component score isn't diluted by any other dimension
        // and can otherwise flood the top of the list with real but
        // statistically thin values (e.g. several tiny territories all
        // landing at a perfect 100 on one metric alone).
        const rankable = result.ranking_countries || [];
        this._renderShiRankingList(rankable);
    }

    // Renders the ranking list rows.
    _renderShiRankingList(countries) {
        const rankingEl = document.getElementById('global-shi-ranking');
        const componentIcons = {
            air_quality: '<i class="fa-solid fa-wind" title="Air quality (OpenAQ)"></i>',
            emissions: '<i class="fa-solid fa-smog" title="Climate/Emissions (World Bank CO2 per capita)"></i>',
            health: '<i class="fa-solid fa-heart-pulse" title="Health outcomes (WHO life expectancy)"></i>',
            vegetation: '<i class="fa-solid fa-seedling" title="Vegetation (NASA MODIS NDVI)"></i>'
        };

        if (!countries.length) {
            rankingEl.innerHTML = '<p class="text-secondary small">No countries currently have data from 2 or more real sources.</p>';
            return;
        }

        rankingEl.innerHTML = countries.map((c) => {
            const riskClass = c.shi >= 80 ? 'healthy' : (c.shi >= 50 ? 'moderate' : 'poor');
            const usedIcons = (c.components_used || []).map(k => componentIcons[k] || '').join(' ');
            const count = c.component_count || (c.components_used || []).length;
            return `
                <div class="shi-rank-row" data-code="${c.country_code}">
                    <span class="shi-rank-position">#${c.ranking_rank ?? ''}</span>
                    <span class="shi-rank-name">${c.country_name}</span>
                    <span class="shi-rank-components">${usedIcons}</span>
                    <span class="shi-rank-coverage" title="${count} of 4 real data sources">${count}/4</span>
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

        // Global SHI panel's collapse behavior is registered in
        // initPanelCollapse() below, alongside left-panel/right-panel —
        // same proven mechanism, not custom logic.

        // Timeline playback
        const playBtn = document.getElementById('play-btn');
        let isPlaying = false;
        let timelapseInterval;

        playBtn.addEventListener('click', () => {
            isPlaying = !isPlaying;
            playBtn.innerHTML = isPlaying ? '<i class="fa-solid fa-pause"></i>' : '<i class="fa-solid fa-play"></i>';

            const slider = document.getElementById('timeline-slider');

            if (isPlaying) {
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

                    // Trigger the input event so initTimelineEvents' listener
                    // picks it up and updates the snapshot viewer
                    slider.dispatchEvent(new Event('input'));
                }, 1000); // Trigger every 1 second to give the snapshot image time to load
            } else {
                // Stop timelapse
                clearInterval(timelapseInterval);
            }
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

        // --- CITIZEN SCIENCE REPORTING (now sidebar sub-tabs, no modal) ---
        const reportForm = document.getElementById('report-form');
        const severitySlider = document.getElementById('report-severity');

        this.initReportsSubtabs();

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
                const selectedType = reportForm.querySelector('input[name="incident-type"]:checked')?.value || 'Other';

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
                    reportForm.reset();
                    document.getElementById('severity-val').innerText = '3';
                    document.dispatchEvent(new CustomEvent('reportSubmitted', { detail: result }));
                    this.refreshReportsFeed();
                    this.showNeuralScan("Ground-Truth Data Synchronized Successfully");
                    this.switchReportsSubtab('info'); // back to the feed to see the new report
                } else {
                    alert("Sync failed. Check connection.");
                }
                btn.innerHTML = originalText;
                btn.disabled = false;
            });
        }

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

                // On/off toggle for Global Health Index: clicking its
                // already-active nav icon closes the panel exactly the
                // way the panel's own X button does — hide only, no
                // switchTab('earth'), so the globe doesn't start
                // auto-rotating just because this panel closed. Clicking
                // the icon again re-opens it via the normal flow below.
                if (targetTab === 'global-shi' && tab.classList.contains('active')) {
                    document.getElementById('global-shi-panel')?.classList.add('hidden');
                    tab.classList.remove('active');
                    return;
                }

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
            'layer-rainfall', 'layer-weather', 'layer-wind'
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

        // 0. Reset: tear down every tab-specific visual overlay, every
        // single time, regardless of which tab is being entered — then
        // the switch-case below turns back on exactly what the target
        // tab needs. This is deliberately unconditional rather than "if
        // leaving tab X, clean up X's stuff": that pattern is exactly how
        // the Global SHI heatmap (and, earlier, report pins) ended up
        // with no teardown at all and kept showing long after navigating
        // away. Any new tab-specific globe layer or transient UI state
        // should be added to TAB_SCOPED_TEARDOWN below, not as a one-off
        // conditional here — that's the single enforcement point for
        // "nothing leaks between tabs," with no exceptions at this point.
        this.resetActiveLayers();
        Object.values(UIManager.TAB_SCOPED_TEARDOWN).forEach(teardown => teardown());

        // Tab-Specific Visibility Mapping (Refined HUD)
        // Note: the floating search bar (.floating-controller) is
        // intentionally NOT in this map — it should stay visible and
        // usable on every tab, so it's never added to the hide/show sweep.
        const uiElements = {
            'left': document.querySelector('.left-panel'),
            'right': document.querySelector('.right-panel'),
            'bottom': document.querySelector('.bottom-panel'),
            'presets': document.getElementById('timelapse-presets'),
            'snapshotViewer': document.getElementById('snapshot-viewer'),
            'insight': document.getElementById('insight-card'),
            'reports': document.getElementById('reports-panel'),
            'globalShi': document.getElementById('global-shi-panel'),
            'prediction': document.getElementById('prediction-panel'),
            'intelligence': document.querySelector('.layer-group'), 
            'shi_gauge': document.querySelector('.shi-gauge-container'),
            // NOTE: previously also included 'charts':
            // document.querySelectorAll('.chart-container') here, which
            // added 'hidden' to EVERY chart-container on the page on every
            // tab switch — but no tab case (not even 'insight', not even
            // 'prediction'/'forecast', which actually needs its charts)
            // ever removed it again. That silently broke every chart in
            // the app (mini trend sparkline, tempChart, precipChart,
            // ndviHistoryChart) behind a class no code ever undid. Removed
            // entirely: chart visibility already correctly follows its
            // parent panel's own show/hide (insight-card, right-panel):
            // there's no case where a chart should be hidden while its
            // parent panel is shown, so this extra independent toggle was
            // pure redundant risk with no upside.
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
                if(uiElements.snapshotViewer) uiElements.snapshotViewer.classList.remove('hidden');

                // Show the flat-image snapshot at whatever location is
                // currently selected (or the default) and the timeline
                // slider's current position — mirrors the old "render
                // immediately on tab entry" fix, but through the snapshot
                // viewer instead of a Cesium imagery layer.
                if (window.snapshotViewer) {
                    const loc = AppState.selectedLocation ?? CONFIG.DEFAULT_COORDINATES;
                    const primarySlider = document.getElementById('timeline-slider');
                    window.snapshotViewer.show(loc.lat, loc.lon);
                    if (primarySlider) {
                        window.snapshotViewer.updateDate(primarySlider.value, 'primary');
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
                window.globeManager?.setReportsVisible(true);
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
        if (!window.snapshotViewer) return;
        const startYear = window.snapshotViewer.TIMELINE_START_YEAR;
        const totalYears = window.snapshotViewer.TIMELINE_END_YEAR - startYear;
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
            this.updateDateDisplay(e.target.value, 'primary');
            window.snapshotViewer?.updateDate(e.target.value, 'primary');
            this.updateTimelineNdviReadout();
        });

        comparisonSlider.addEventListener('input', (e) => {
            this.updateDateDisplay(e.target.value, 'historical');
            window.snapshotViewer?.updateDate(e.target.value, 'historical');
        });

        splitBtn.addEventListener('click', () => {
            const isEnabled = comparisonNode.classList.toggle('hidden');
            const splitActive = !isEnabled; // If hidden is toggled off, split is active

            splitBtn.classList.toggle('active', splitActive);
            window.snapshotViewer?.setSplitMode(splitActive);
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

                AppState.setSelectedLocation(lat, lon);

                // Fly the globe camera to the location for visual context
                // behind/around the snapshot panel. This is plain camera
                // movement, not an imagery-layer swap — it was never the
                // thing causing the instability, so it's safe to keep.
                if (window.globeManager?.viewer) {
                    window.globeManager._programmaticFlight = true;
                    window.globeManager.viewer.camera.flyTo({
                        destination: Cesium.Cartesian3.fromDegrees(lon, lat, height),
                        duration: 2.0,
                        complete: () => { window.globeManager._programmaticFlight = false; }
                    });
                }

                window.snapshotViewer?.show(lat, lon);

                const beforeDate = chip.dataset.beforeDate;
                const afterDate = chip.dataset.afterDate;
                if (beforeDate && afterDate) {
                    const beforeValue = this.dateToSliderValue(beforeDate);
                    const afterValue = this.dateToSliderValue(afterDate);

                    primarySlider.value = afterValue;
                    this.updateDateDisplay(afterValue, 'primary');
                    window.snapshotViewer?.updateDate(afterValue, 'primary');

                    comparisonSlider.value = beforeValue;
                    this.updateDateDisplay(beforeValue, 'historical');
                    window.snapshotViewer?.updateDate(beforeValue, 'historical');

                    if (comparisonNode.classList.contains('hidden')) {
                        comparisonNode.classList.remove('hidden');
                        splitBtn.classList.add('active');
                        window.snapshotViewer?.setSplitMode(true);
                    }

                    this.showStoryReadout(chip, beforeDate, afterDate, lat, lon);
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
    // produces it via SnapshotViewer.updateDate()'s inverse formula — keeps
    // the date<->slider-position mapping in one place rather than
    // duplicating the month-math here.
    dateToSliderValue(dateStr) {
        if (!window.snapshotViewer) return 0;
        const [y, m] = dateStr.split('-').map(Number);
        const startYear = window.snapshotViewer.TIMELINE_START_YEAR;
        const totalMonths = (window.snapshotViewer.TIMELINE_END_YEAR - startYear) * 12;
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
        if (!window.snapshotViewer) return;
        const lat = AppState.selectedLocation?.lat ?? CONFIG.DEFAULT_COORDINATES.lat;
        const lon = AppState.selectedLocation?.lon ?? CONFIG.DEFAULT_COORDINATES.lon;
        const date = window.snapshotViewer.primaryDate;

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

        // Temperature History chart — real yearly comparison (was
        // previously the always-on 6-month sparkline). Unlike NDVI's
        // fixed 0-1 range, temperature can be negative and its real
        // range varies hugely by location (a Delhi summer and an
        // Antarctic reading aren't on any shared fixed scale), so this
        // deliberately leaves y min/max unset and lets Chart.js auto-scale
        // per location rather than picking one number that would be
        // wrong most of the time. spanGaps: false for the same honesty
        // reason as ndviHistoryChart below: a missing year (see
        // get_temperature_history's data_source: "unavailable") must
        // show as a visible gap, never bridged/interpolated.
        const ctxTempHistory = document.getElementById('tempHistoryChart').getContext('2d');
        this.tempHistoryChart = new Chart(ctxTempHistory, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Temperature',
                    data: [],
                    borderColor: '#f97316',
                    backgroundColor: 'rgba(249, 115, 22, 0.1)',
                    tension: 0.3,
                    spanGaps: false,
                    pointRadius: 4,
                    pointBackgroundColor: '#f97316',
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => ctx.parsed.y === null
                                ? 'No real data for this year'
                                : `${ctx.parsed.y.toFixed(1)}°C`
                        }
                    }
                },
                scales: {
                    y: {
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: '#94a3b8', font: { size: 10 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8', font: { size: 10 } }
                    }
                }
            }
        });

        // Vegetation History chart — a real labeled trend (year -> NDVI),
        // not a sparkline, so unlike the old always-on sparkline this one
        // shows its axes. spanGaps: false is deliberate: a null value for
        // a year means "no real MODIS composite found within tolerance"
        // (see get_ndvi_history's data_source: "unavailable"), and this
        // must render as a visible gap in the line, never bridged/interpolated
        // — bridging it would visually fabricate a value that was never
        // measured.
        const ctxNdviHistory = document.getElementById('ndviHistoryChart').getContext('2d');
        this.ndviHistoryChart = new Chart(ctxNdviHistory, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'NDVI',
                    data: [],
                    borderColor: '#22c55e',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    tension: 0.3,
                    spanGaps: false,
                    pointRadius: 4,
                    pointBackgroundColor: '#22c55e',
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => ctx.parsed.y === null
                                ? 'No real data for this year'
                                : `NDVI ${ctx.parsed.y.toFixed(3)}`
                        }
                    }
                },
                scales: {
                    y: {
                        min: 0,
                        max: 1,
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: '#94a3b8', font: { size: 10 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8', font: { size: 10 } }
                    }
                }
            }
        });

        // Rainfall History chart — a BAR chart, deliberately different
        // from the line charts above: this is a discrete annual total
        // per year (not a continuous trend the way temperature/NDVI are
        // sampled), so bars are the more conventional, immediately
        // legible shape for "amount per year." A missing year (data_
        // source: "unavailable" from get_rainfall_history, e.g. below the
        // completeness threshold) simply has no bar — Chart.js already
        // renders a null value as an absent bar, no spanGaps equivalent
        // needed for bar charts.
        const ctxRainfallHistory = document.getElementById('rainfallHistoryChart').getContext('2d');
        this.rainfallHistoryChart = new Chart(ctxRainfallHistory, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Annual rainfall',
                    data: [],
                    backgroundColor: 'rgba(56, 189, 248, 0.7)',
                    borderColor: '#38bdf8',
                    borderWidth: 1,
                    borderRadius: 3,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => ctx.parsed.y === null
                                ? 'No real data for this year'
                                : `${ctx.parsed.y.toLocaleString()} mm`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: '#94a3b8', font: { size: 10 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8', font: { size: 10 } }
                    }
                }
            }
        });

        // AQI forecast — bar chart so each day's peak reads as a distinct
        // event, and colored per-bar against the same AQI thresholds used
        // by the sensor dots on the globe and the extension's alert
        // threshold, so "what counts as bad" looks the same everywhere.
        const ctxAqiForecast = document.getElementById('aqiForecastChart').getContext('2d');
        this.aqiForecastChart = new Chart(ctxAqiForecast, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Forecast AQI (daily peak)',
                    data: [],
                    backgroundColor: [],
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `AQI ${ctx.parsed.y ?? 'n/a'}`
                        }
                    }
                },
                scales: {
                    y: { display: false, beginAtZero: true },
                    x: { grid: { display: false } }
                }
            }
        });
    }

    // Small "LIVE" / "EST" pill next to a stat value, driven by the
    // `data_source` field the backend already returns on nearly every
    // response (live_waqi, real_openmeteo, real_modis, fallback,
    // estimated_fallback, ...). This information existed end-to-end in
    // the API before this change but stopped at the network response —
    // nothing in the UI ever showed the person whether a number was a
    // live reading or a labeled fallback estimate. See
    // _setStatBadge() for how this gets attached next to a stat element.
    _dataSourceBadge(source) {
        if (!source) return null;
        const live = new Set(['live_waqi', 'real_openmeteo', 'real_modis', 'live']);
        const isLive = live.has(source);
        return {
            label: isLive ? 'LIVE' : 'EST',
            cls: isLive ? 'live' : 'estimated',
            title: `Data source: ${source.replace(/_/g, ' ')}`,
        };
    }

    // Attaches (or updates) a small badge immediately after the element
    // with id `valueElId`. Creates the badge element once, then just
    // updates its text/class/title on subsequent calls — so this is
    // safe to call every time a panel refreshes without leaking
    // duplicate badge elements into the DOM.
    _setStatBadge(valueElId, source) {
        const valueEl = document.getElementById(valueElId);
        if (!valueEl) return;
        const info = this._dataSourceBadge(source);

        let badge = valueEl.parentElement.querySelector(`.data-source-badge[data-for="${valueElId}"]`);
        if (!info) {
            if (badge) badge.remove();
            return;
        }
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'data-source-badge';
            badge.dataset.for = valueElId;
            valueEl.insertAdjacentElement('afterend', badge);
        }
        badge.className = `data-source-badge ${info.cls}`;
        badge.textContent = info.label;
        badge.title = info.title;
    }

    // Shows/updates the small "LIVE"/"MOCK" pill in the corner of the
    // globe reflecting whether the current rain/snow/cloud atmospheric
    // sync came from real OpenWeatherMap data or the labeled deterministic
    // fallback (see backend/services/weather.py's `status` field). Called
    // from the 'weatherSynced' listener in initEventListeners().
    updateAseStatusBadge(weather) {
        const badge = document.getElementById('ase-status-badge');
        if (!badge || !weather || !weather.status) return;

        const isLive = weather.status === 'success';
        badge.classList.remove('hidden');
        badge.className = `ase-status-badge ${isLive ? 'live' : 'mock'}`;
        badge.textContent = isLive ? 'ASE: LIVE' : 'ASE: MOCK';
        badge.title = isLive
            ? 'Rain/snow/cloud visuals are synced to live OpenWeatherMap data at this location.'
            : 'OPENWEATHERMAP_API_KEY is not set, so rain/snow/cloud visuals use a deterministic placeholder, not real weather.';
    }

    // AQI color scale shared with the sensor dots on the globe and the
    // browser extension's AQI_ALERT_THRESHOLD (200) — kept in one place
    // here so the forecast bars, if that scale ever changes, are easy to
    // update alongside it rather than silently drifting out of sync.
    _aqiColor(aqi) {
        if (aqi === null || aqi === undefined) return 'rgba(148,163,184,0.5)'; // unknown - grey
        if (aqi <= 50) return '#22c55e';   // Good
        if (aqi <= 100) return '#eab308';  // Moderate
        if (aqi <= 150) return '#f97316';  // Unhealthy (sensitive)
        if (aqi <= 200) return '#ef4444';  // Unhealthy
        if (aqi <= 300) return '#a855f7';  // Very unhealthy
        return '#7f1d1d';                  // Hazardous
    }

    updateForecastPanels(forecastData, aqiForecastData, wildfireRiskData) {
        this._updateWeatherForecastStrip(forecastData);
        this._updateAqiForecastChart(aqiForecastData);
        this._updateWildfireRiskStat(wildfireRiskData);
    }

    _updateWeatherForecastStrip(forecastData) {
        const strip = document.getElementById('forecast-strip');
        if (!strip) return;

        if (!forecastData || !forecastData.days || forecastData.days.length === 0) {
            strip.innerHTML = `<p class="text-secondary small">Forecast unavailable right now — the backend couldn't reach Open-Meteo. Try again shortly.</p>`;
            return;
        }

        strip.innerHTML = forecastData.days.map(day => {
            const date = new Date(day.date + 'T00:00:00');
            const label = date.toLocaleDateString('default', { weekday: 'short' });
            const precip = day.precipitation_mm ?? 0;
            return `
                <div class="forecast-day" title="${day.date}">
                    <span class="forecast-day-label">${label}</span>
                    <i class="fa-solid ${this._precipIcon(precip)} forecast-day-icon"></i>
                    <span class="forecast-day-temp">${day.temp_max_c ?? '--'}° / ${day.temp_min_c ?? '--'}°</span>
                    <span class="forecast-day-precip">${precip}mm</span>
                </div>
            `;
        }).join('');
    }

    // Shared mm->icon mapping so the same rainfall amount always reads the
    // same way in both the 7-day forecast strip and the insight card's
    // rainfall node, rather than two independently-tuned thresholds.
    _precipIcon(precipMm) {
        if (precipMm === null || precipMm === undefined) return 'fa-sun';
        if (precipMm >= 10) return 'fa-cloud-showers-heavy';
        if (precipMm >= 1) return 'fa-cloud-rain';
        return 'fa-sun';
    }

    // Temperature band -> {icon, colorVar}, matching the same cold/mild/hot
    // language used in _aqiColor() below (fixed thresholds over a real
    // reading, not a new data source).
    _tempBand(tempC) {
        if (tempC === null || tempC === undefined) return { icon: 'fa-temperature-half', color: 'var(--accent-color)' };
        if (tempC < 10) return { icon: 'fa-temperature-low', color: 'var(--accent-color)' };
        if (tempC <= 25) return { icon: 'fa-temperature-half', color: 'var(--success)' };
        if (tempC <= 32) return { icon: 'fa-temperature-three-quarters', color: 'var(--warning-amber)' };
        return { icon: 'fa-temperature-high', color: 'var(--danger)' };
    }

    // AQI numeric value -> category label, using the exact same thresholds
    // as _aqiColor() so the color and the label never drift apart.
    _aqiCategory(aqi) {
        if (aqi === null || aqi === undefined) return '';
        if (aqi <= 50) return 'Good';
        if (aqi <= 100) return 'Moderate';
        if (aqi <= 150) return 'Unhealthy for sensitive groups';
        if (aqi <= 200) return 'Unhealthy';
        if (aqi <= 300) return 'Very unhealthy';
        return 'Hazardous';
    }

    // NDVI value -> {icon, color}, collapsing globeManager's 5-tier
    // _ndviClassification() text into a 3-tier color/icon read (the same
    // health-color bands the right panel's stat-ndvi already uses, though
    // that one referenced a non-existent 'var(--warning)' CSS variable —
    // fixed here to the actual var(--warning-amber) token).
    _ndviBand(ndvi) {
        if (ndvi === null || ndvi === undefined) return { icon: 'fa-seedling', color: 'var(--text-secondary)' };
        if (ndvi <= 0.2) return { icon: 'fa-mountain', color: 'var(--danger)' };
        if (ndvi <= 0.6) return { icon: 'fa-seedling', color: 'var(--warning-amber)' };
        return { icon: 'fa-tree', color: 'var(--success)' };
    }

    _updateAqiForecastChart(aqiForecastData) {
        const note = document.getElementById('aqi-forecast-note');
        if (!this.aqiForecastChart) return;

        if (!aqiForecastData || !aqiForecastData.days || aqiForecastData.days.length === 0) {
            this.aqiForecastChart.data.labels = [];
            this.aqiForecastChart.data.datasets[0].data = [];
            this.aqiForecastChart.data.datasets[0].backgroundColor = [];
            this.aqiForecastChart.update();
            if (note) note.textContent = 'Forecast unavailable right now — try again shortly.';
            return;
        }

        const labels = aqiForecastData.days.map(d => {
            const date = new Date(d.date + 'T00:00:00');
            return date.toLocaleDateString('default', { weekday: 'short' });
        });
        const values = aqiForecastData.days.map(d => d.aqi_max);
        const colors = values.map(v => this._aqiColor(v));

        this.aqiForecastChart.data.labels = labels;
        this.aqiForecastChart.data.datasets[0].data = values;
        this.aqiForecastChart.data.datasets[0].backgroundColor = colors;
        this.aqiForecastChart.update();

        if (note) {
            const worst = values.filter(v => v !== null && v !== undefined);
            note.textContent = worst.length
                ? `Peak forecast AQI this period: ${Math.max(...worst)}.`
                : '';
        }
    }

    // Shared by both the right-panel stat (below) and the Insight card's
    // wildfire node, so the two never drift into disagreeing colors.
    _wildfireRiskColor(category) {
        const colorByCategory = {
            'Low': 'var(--success)',
            'Moderate': 'var(--warning-amber)',
            'High': '#f97316',
            'Extreme': 'var(--danger)',
        };
        return colorByCategory[category] || '';
    }

    // Formats the real inputs behind the rule-based index into one
    // readable string — shared for the same reason as the color map above.
    _wildfireInputsText(inputs) {
        inputs = inputs || {};
        const parts = [];
        if (inputs.temp_c !== null && inputs.temp_c !== undefined) parts.push(`${inputs.temp_c}°C`);
        if (inputs.humidity_pct !== null && inputs.humidity_pct !== undefined) parts.push(`${inputs.humidity_pct}% humidity`);
        if (inputs.wind_kmh !== null && inputs.wind_kmh !== undefined) parts.push(`${inputs.wind_kmh}km/h wind`);
        if (inputs.ndvi !== null && inputs.ndvi !== undefined) parts.push(`NDVI ${inputs.ndvi}`);
        return parts;
    }

    // Shared "FORMULA" badge — distinct from _setStatBadge's LIVE/EST
    // vocabulary, since a rule-based derived value is neither a raw
    // measurement nor a degraded fallback; labeling it EST would be
    // misleading in the other direction. Used by both the right-panel
    // stat and the Insight card's wildfire node.
    _setFormulaBadge(valueElId, title) {
        const valueEl = document.getElementById(valueElId);
        if (!valueEl) return;
        let badge = valueEl.parentElement.querySelector(`.data-source-badge[data-for="${valueElId}"]`);
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'data-source-badge formula';
            badge.dataset.for = valueElId;
            badge.textContent = 'FORMULA';
            valueEl.insertAdjacentElement('afterend', badge);
        }
        badge.title = title;
    }

    _updateWildfireRiskStat(wildfireRiskData) {
        const valueEl = document.getElementById('stat-risk');
        const detailEl = document.getElementById('stat-risk-detail');
        if (!valueEl) return;

        if (!wildfireRiskData || wildfireRiskData.score === null || wildfireRiskData.score === undefined) {
            valueEl.textContent = '--';
            valueEl.style.color = '';
            if (detailEl) detailEl.textContent = '';
            return;
        }

        valueEl.textContent = `${wildfireRiskData.score} (${wildfireRiskData.category})`;
        this._setFormulaBadge('stat-risk', 'Rule-based fire danger index from real inputs — not a trained ML model.');
        valueEl.style.color = this._wildfireRiskColor(wildfireRiskData.category);

        if (detailEl) {
            const parts = this._wildfireInputsText(wildfireRiskData.inputs);
            detailEl.textContent = parts.length
                ? `Rule-based index from: ${parts.join(', ')}`
                : '';
        }
    }

    updateAnalyticsPanel(climateData, envData, shiData, ndviData) {
        console.log("Updating Analytics Panel:", { climateData, envData });
        if (!climateData || !climateData.historical_trends) {
            console.error("No climate data or historical trends available.");
            return;
        }

        // Update Summary
        const location = climateData.location;
        const _anomalySign = climateData.current_anomaly > 0 ? '+' : '';
        let summaryHtml = `
            <p><i class="fa-solid fa-location-dot"></i> Lat: ${location.lat.toFixed(2)}°, Lon: ${location.lon.toFixed(2)}°</p>
            <p><strong>Anomaly:</strong> <span style="color:${climateData.current_anomaly > 0 ? 'var(--danger)' : 'var(--accent-color)'}">${_anomalySign}${climateData.current_anomaly.toFixed(2)}°C</span></p>
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

            // AQI is the field that actually varies live/fallback per
            // request (see mock_data.py); CO2 is always the real NOAA
            // monthly figure once fetched successfully, so it always
            // reads LIVE here rather than tracking AQI's source.
            this._setStatBadge('stat-aqi', envData.data_source);
            // CO2 always comes from a real NOAA GML reading (see
            // mock_data.get_real_global_co2_ppm) — it's either today's
            // fetch or the last successfully cached real value, never a
            // fabricated fallback, so this always reads LIVE.
            this._setStatBadge('stat-co2', 'live');
        }

        if (ndviData) {
            document.getElementById('stat-ndvi').innerText = ndviData.ndvi !== undefined ? ndviData.ndvi.toFixed(3) : '--';
            // Optional: change color based on health
            const ndviElem = document.getElementById('stat-ndvi');
            if (ndviData.ndvi > 0.6) ndviElem.style.color = 'var(--success)';
            else if (ndviData.ndvi > 0.2) ndviElem.style.color = 'var(--warning)';
            else ndviElem.style.color = 'var(--danger)';

            this._setStatBadge('stat-ndvi', ndviData.data_source);

            const ndviSubEl = document.getElementById('stat-ndvi-sub');
            if (ndviSubEl && ndviData.ndvi !== undefined) {
                const classification = window.globeManager?._ndviClassification(ndviData.ndvi) ?? '';
                ndviSubEl.textContent = `${classification} — NASA MODIS`;
            }
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
        const tempHistoryActive = document.getElementById('layer-temp')?.checked;
        const wildfiresActive = document.getElementById('layer-wildfires')?.checked;
        const rainfallHistoryActive = document.getElementById('layer-rainfall')?.checked;
        const weatherActive = document.getElementById('layer-weather')?.checked;
        const windActive = document.getElementById('layer-wind')?.checked;
        const openAqActive = document.getElementById('layer-sensors')?.checked;

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

            // Temperature band: colors the value + swaps the icon, purely a
            // visual read of the same real number already shown.
            const tempBand = this._tempBand(latest.avg_temp_c);
            const tempValueEl = document.getElementById('node-temp');
            const tempIconEl = document.getElementById('node-temp-icon');
            if (tempValueEl) tempValueEl.style.color = tempBand.color;
            if (tempIconEl) {
                tempIconEl.className = `fa-solid ${tempBand.icon} data-node-icon`;
                tempIconEl.style.color = tempBand.color;
            }

            // Rainfall icon: same mm->icon mapping as the 7-day forecast
            // strip, so a given rainfall amount always reads the same way.
            const precipIconEl = document.getElementById('node-precip-icon');
            if (precipIconEl) {
                precipIconEl.className = `fa-solid ${this._precipIcon(latest.total_rainfall_mm)} data-node-icon`;
            }

            // Anomaly is a delta from a seasonal baseline, not an absolute
            // temperature — showing it as a bare number ("7.67°C") reads
            // like a temperature reading, not a departure from normal.
            // An explicit sign makes clear which direction it's off by.
            const anomaly = climateData.current_anomaly;
            const anomalySign = anomaly > 0 ? '+' : (anomaly < 0 ? '' : '±'); // toFixed already includes '-' for negatives
            document.getElementById('node-anomaly').innerText = `${anomalySign}${anomaly.toFixed(2)}°C`;

            const subEl = document.getElementById('node-anomaly-sub');
            if (subEl) {
                subEl.textContent = anomaly > 0.05 ? 'Warmer than historical average'
                    : anomaly < -0.05 ? 'Colder than historical average'
                    : 'Near historical average';
            }

            // Zero-centered diverging bar: magnitude scaled against a fixed
            // +-3C range and clamped at the ends so one outlier can't blow
            // out the visual scale. Fill grows left (cooler) or right
            // (warmer) from the center tick.
            const anomalyFillEl = document.getElementById('anomaly-fill');
            if (anomalyFillEl) {
                const ANOMALY_RANGE = 3; // +-3C maps to the full half-width
                const pct = Math.min(Math.abs(anomaly) / ANOMALY_RANGE, 1) * 50; // max 50% of track from center
                anomalyFillEl.style.background = anomaly >= 0 ? 'var(--danger)' : 'var(--accent-color)';
                if (anomaly >= 0) {
                    anomalyFillEl.style.left = '50%';
                    anomalyFillEl.style.right = 'auto';
                    anomalyFillEl.style.width = `${pct}%`;
                } else {
                    anomalyFillEl.style.right = '50%';
                    anomalyFillEl.style.left = 'auto';
                    anomalyFillEl.style.width = `${pct}%`;
                }
            }

            // climateData.data_source is "real_openmeteo" or
            // "estimated_fallback" — applies to temp/rainfall/anomaly,
            // all three of which come from the same Open-Meteo call.
            this._setStatBadge('node-temp', climateData.data_source);
            this._setStatBadge('node-precip', climateData.data_source);
            this._setStatBadge('node-anomaly', climateData.data_source);

            if (envData) {
                document.getElementById('node-aqi').innerText = envData.air_quality_index ?? '--';
                document.getElementById('node-co2').innerText = envData.co2_ppm ? `${envData.co2_ppm}` : '--';
                this._setStatBadge('node-aqi', envData.data_source);
                this._setStatBadge('node-co2', 'live'); // real NOAA GML reading, see stat-co2 above

                // AQI color + category, reusing the same _aqiColor() scale
                // already driving the forecast chart bars and globe dots.
                const aqiValueEl = document.getElementById('node-aqi');
                const aqiSubEl = document.getElementById('node-aqi-sub');
                if (aqiValueEl) aqiValueEl.style.color = this._aqiColor(envData.air_quality_index);
                if (aqiSubEl) aqiSubEl.textContent = this._aqiCategory(envData.air_quality_index);

                // CO2 context bar: fixed 280ppm (pre-industrial) -> 450ppm
                // rail with a marker at the real reading.
                const co2MarkerEl = document.getElementById('co2-context-marker');
                const co2SubEl = document.getElementById('node-co2-sub');
                if (envData.co2_ppm) {
                    const CO2_BASELINE = 280, CO2_MAX = 450;
                    const co2Pct = Math.min(Math.max((envData.co2_ppm - CO2_BASELINE) / (CO2_MAX - CO2_BASELINE), 0), 1) * 100;
                    if (co2MarkerEl) co2MarkerEl.style.left = `${co2Pct}%`;
                    if (co2SubEl) {
                        const pctAbove = Math.round(((envData.co2_ppm - CO2_BASELINE) / CO2_BASELINE) * 100);
                        co2SubEl.textContent = `+${pctAbove}% vs pre-industrial (${CO2_BASELINE}ppm)`;
                    }
                } else if (co2SubEl) {
                    co2SubEl.textContent = '';
                }
            }

            if (shiData) {
                document.getElementById('insight-shi-value').innerText = shiData.shi;
                document.getElementById('insight-shi-risk').innerText = shiData.risk;

                const badge = document.getElementById('insight-shi-badge');
                badge.classList.remove('risk-healthy', 'risk-moderate', 'risk-poor');
                if (shiData.shi >= 80) badge.classList.add('risk-healthy');
                else if (shiData.shi >= 50) badge.classList.add('risk-moderate');
                else badge.classList.add('risk-poor');

                // Ring gauge: circumference of r=26 is 2*pi*26 ~= 163.4;
                // dashoffset 0 = full ring, 163.4 = empty ring.
                const ringFillEl = document.getElementById('insight-shi-ring-fill');
                if (ringFillEl) {
                    const CIRCUMFERENCE = 163.4;
                    const shiPct = Math.min(Math.max(shiData.shi, 0), 100) / 100;
                    ringFillEl.style.strokeDashoffset = `${CIRCUMFERENCE * (1 - shiPct)}`;
                }
            }

            // Temperature History section visibility — gated by the
            // Temperature (Anomaly) toggle, same pattern as vegetation
            // below. The actual chart data comes from updateTempHistoryChart(),
            // called separately from globe.js right alongside this
            // function (mirrors how ndviHistoryData/updateNdviHistoryChart
            // already work) — this block only controls show/hide.
            const tempHistorySection = document.getElementById('temp-history-section');
            if (tempHistorySection) tempHistorySection.classList.toggle('hidden', !tempHistoryActive);

            // 3. Vegetation section visibility — per explicit request,
            // this whole section (data-node + legend + History chart) is
            // now solely gated by the Vegetation (NDVI) toggle, not shown
            // unconditionally. The old always-on behavior for the
            // data-node is intentionally gone.
            const ndviDataNode = document.getElementById('ndvi-data-node');
            const ndviHistorySection = document.getElementById('ndvi-history-section');

            if (legendBox) legendBox.classList.toggle('hidden', !ndviActive);
            if (ndviDataNode) ndviDataNode.classList.toggle('hidden', !ndviActive);
            if (ndviHistorySection) ndviHistorySection.classList.toggle('hidden', !ndviActive);

            // Active Wildfires data-node — same gating pattern, real data
            // populated separately by updateWildfireInsightNode() (called
            // alongside this function from globe.js), this block only
            // controls show/hide.
            const wildfireDataNode = document.getElementById('wildfire-data-node');
            if (wildfireDataNode) wildfireDataNode.classList.toggle('hidden', !wildfiresActive);

            // Rainfall History section — same gating pattern, real data
            // populated separately by updateRainfallHistoryChart() (called
            // alongside this function from globe.js), this block only
            // controls show/hide.
            const rainfallHistorySection = document.getElementById('rainfall-history-section');
            if (rainfallHistorySection) rainfallHistorySection.classList.toggle('hidden', !rainfallHistoryActive);

            // Weather Conditions data-node — same gating pattern, real
            // data populated separately by updateWeatherInsightNode()
            // (called alongside this function from globe.js), this block
            // only controls show/hide.
            const weatherDataNode = document.getElementById('weather-data-node');
            if (weatherDataNode) weatherDataNode.classList.toggle('hidden', !weatherActive);

            // Wind data-node — same gating pattern, real data populated
            // separately by updateWindInsightNode() (called alongside
            // this function from globe.js), this block only controls
            // show/hide.
            const windDataNode = document.getElementById('wind-data-node');
            if (windDataNode) windDataNode.classList.toggle('hidden', !windActive);

            // AQI OpenAQ verification sub-line — same gating pattern,
            // real data populated separately by updateAqiVerificationNode()
            // (called alongside this function from globe.js), this block
            // only controls show/hide. Note the AQI value/category above
            // it (WAQI-sourced) is NEVER gated by this toggle — it always
            // shows, same as before; only this extra verification line is.
            const aqiOpenAqSub = document.getElementById('node-aqi-openaq-sub');
            if (aqiOpenAqSub) aqiOpenAqSub.classList.toggle('hidden', !openAqActive);

            if (ndviActive) {
                // NDVI legend marker: positions a pointer along the static
                // gradient bar at the real NDVI value for this location.
                // Typical real-world NDVI runs ~0 (bare ground) to ~0.9
                // (dense rainforest); values are clamped so an edge-case
                // reading can't push the marker off the bar.
                const ndviMarkerEl = document.getElementById('ndvi-legend-marker');
                if (ndviMarkerEl && ndviData && ndviData.ndvi !== undefined) {
                    const NDVI_MIN = 0, NDVI_MAX = 0.9;
                    const ndviPct = Math.min(Math.max((ndviData.ndvi - NDVI_MIN) / (NDVI_MAX - NDVI_MIN), 0), 1) * 100;
                    ndviMarkerEl.style.left = `${ndviPct}%`;
                }

                if (ndviData && ndviData.ndvi !== undefined) {
                    const ndviBand = this._ndviBand(ndviData.ndvi);
                    const ndviValueEl = document.getElementById('node-ndvi');
                    const ndviIconEl = document.getElementById('node-ndvi-icon');
                    const ndviSubEl2 = document.getElementById('node-ndvi-sub');
                    const ndviNodeMarkerEl = document.getElementById('node-ndvi-marker');

                    if (ndviValueEl) {
                        ndviValueEl.innerText = ndviData.ndvi.toFixed(2);
                        ndviValueEl.style.color = ndviBand.color;
                    }
                    if (ndviIconEl) {
                        ndviIconEl.className = `fa-solid ${ndviBand.icon} data-node-icon`;
                        ndviIconEl.style.color = ndviBand.color;
                    }
                    if (ndviSubEl2) {
                        const classification = window.globeManager?._ndviClassification(ndviData.ndvi) ?? '';
                        ndviSubEl2.textContent = `${classification} — NASA MODIS`;
                    }
                    if (ndviNodeMarkerEl) {
                        const NDVI_MIN = 0, NDVI_MAX = 0.9;
                        const pct = Math.min(Math.max((ndviData.ndvi - NDVI_MIN) / (NDVI_MAX - NDVI_MIN), 0), 1) * 100;
                        ndviNodeMarkerEl.style.left = `${pct}%`;
                    }
                    this._setStatBadge('node-ndvi', ndviData.data_source);
                }
            }
        }, 1200);
    }

    // Vegetation History: renders the year -> NDVI chart + trend summary
    // from get_ndvi_history(). Deliberately separate from updateInsightCard
    // above (called right alongside it from globe.js) rather than folded
    // in, so the existing NDVI current-value logic there stays untouched.
    updateNdviHistoryChart(historyData) {
        const summaryEl = document.getElementById('ndvi-history-summary');
        const emptyEl = document.getElementById('ndvi-history-empty');
        const sectionEl = document.getElementById('ndvi-history-section');
        if (!this.ndviHistoryChart || !sectionEl) return;

        const years = historyData && Array.isArray(historyData.years) ? historyData.years : [];
        const validYears = years.filter(y => y.data_source === 'real_modis' && y.ndvi !== null && y.ndvi !== undefined);

        if (years.length === 0 || validYears.length === 0) {
            // Honest empty state — never draw a chart implying data exists
            // when every year came back unavailable. Surface the REAL
            // reason where we have one (historyData.error, from a total
            // /dates failure) rather than a fixed generic message that
            // hides whether this is a systemic failure or every individual
            // year genuinely being cloud-masked.
            this.ndviHistoryChart.data.labels = [];
            this.ndviHistoryChart.data.datasets[0].data = [];
            this.ndviHistoryChart.update();
            if (summaryEl) { summaryEl.textContent = ''; summaryEl.classList.add('hidden'); }
            if (emptyEl) {
                emptyEl.textContent = (historyData && historyData.error)
                    ? historyData.error
                    : years.length > 0
                        ? 'No real MODIS composite found for any reference year at this location (all cloud-masked or no coverage).'
                        : 'Historical MODIS data unavailable for this location.';
                emptyEl.classList.remove('hidden');
            }
            return;
        }

        if (emptyEl) emptyEl.classList.add('hidden');
        if (summaryEl) summaryEl.classList.remove('hidden');

        // Missing years become explicit null data points (never
        // interpolated/fabricated) — spanGaps: false on the chart (see
        // its init above) renders these as a visible break in the line.
        this.ndviHistoryChart.data.labels = years.map(y => String(y.year));
        this.ndviHistoryChart.data.datasets[0].data = years.map(y =>
            (y.data_source === 'real_modis' && y.ndvi !== null && y.ndvi !== undefined) ? y.ndvi : null
        );
        this.ndviHistoryChart.update();

        if (summaryEl) {
            if (validYears.length < 2) {
                summaryEl.textContent = 'Not enough real historical data at this location to determine a trend.';
            } else {
                const earliest = validYears[0];
                const latest = validYears[validYears.length - 1];
                const pctChange = earliest.ndvi !== 0
                    ? ((latest.ndvi - earliest.ndvi) / Math.abs(earliest.ndvi)) * 100
                    : 0;

                // Deliberately NOT "Improving/Declining" — that framing
                // implies a directional vegetation-cover trend, but this
                // number compares two seasonal MEANS (each averaged from
                // real Jul-Aug composites — see get_ndvi_history), which
                // can shift for reasons other than permanent cover change
                // (monsoon timing, crop cycle, irrigation). Reporting the
                // plain % change with its basis stated avoids that
                // overclaim while still surfacing the real number.
                const sign = pctChange > 0 ? '+' : '';
                summaryEl.textContent =
                    `NDVI change: ${sign}${pctChange.toFixed(1)}% (Jul-Aug seasonal mean, ${earliest.year} to ${latest.year})`;
            }
        }
    }

    // Temperature History: renders the year -> °C chart + trend summary
    // from get_temperature_history(). Mirrors updateNdviHistoryChart above,
    // with one deliberate difference: the trend here uses an ABSOLUTE °C
    // threshold (+/-0.5°C), not percent change. Percent change breaks down
    // for a value that can cross or sit near zero — e.g. -0.2°C to +0.2°C
    // is a tiny, unremarkable shift but computes as a nonsensical -200%;
    // a real anomaly at a cold location could produce similarly misleading
    // percentages. An absolute °C difference is the honest, stable way to
    // describe a temperature change, unlike NDVI (always positive, 0-1)
    // where percent change is meaningful.
    updateTempHistoryChart(historyData) {
        const summaryEl = document.getElementById('temp-history-summary');
        const emptyEl = document.getElementById('temp-history-empty');
        const sectionEl = document.getElementById('temp-history-section');
        if (!this.tempHistoryChart || !sectionEl) return;

        const years = historyData && Array.isArray(historyData.years) ? historyData.years : [];
        const validYears = years.filter(y => y.data_source === 'real_openmeteo' && y.avg_temp_c !== null && y.avg_temp_c !== undefined);

        if (years.length === 0 || validYears.length === 0) {
            this.tempHistoryChart.data.labels = [];
            this.tempHistoryChart.data.datasets[0].data = [];
            this.tempHistoryChart.update();
            if (summaryEl) { summaryEl.textContent = ''; summaryEl.classList.add('hidden'); }
            if (emptyEl) {
                emptyEl.textContent = (historyData && historyData.error)
                    ? historyData.error
                    : 'Historical temperature data unavailable for this location.';
                emptyEl.classList.remove('hidden');
            }
            return;
        }

        if (emptyEl) emptyEl.classList.add('hidden');
        if (summaryEl) summaryEl.classList.remove('hidden');

        // Missing years become explicit null data points (never
        // interpolated/fabricated) — spanGaps: false on the chart
        // renders these as a visible break in the line.
        this.tempHistoryChart.data.labels = years.map(y => String(y.year));
        this.tempHistoryChart.data.datasets[0].data = years.map(y =>
            (y.data_source === 'real_openmeteo' && y.avg_temp_c !== null && y.avg_temp_c !== undefined) ? y.avg_temp_c : null
        );
        this.tempHistoryChart.update();

        if (summaryEl) {
            if (validYears.length < 2) {
                summaryEl.textContent = 'Not enough real historical data at this location to determine a trend.';
            } else {
                const earliest = validYears[0];
                const latest = validYears[validYears.length - 1];
                const degChange = latest.avg_temp_c - earliest.avg_temp_c;

                const trendLabel = degChange > 0.5 ? 'Warming' : degChange < -0.5 ? 'Cooling' : 'Stable';
                const sign = degChange > 0 ? '+' : '';
                summaryEl.textContent =
                    `Overall trend: ${trendLabel} (${sign}${degChange.toFixed(1)}°C from ${earliest.year} to ${latest.year})`;
            }
        }
    }

    // Rainfall History: renders the year -> annual-total-mm bar chart
    // from get_rainfall_history(). Wording is deliberately neutral (no
    // "Improving/Declining/Wetter/Drier" framing) — same reasoning as
    // NDVI's "NDVI change" wording: more or less rainfall isn't
    // inherently good or bad the way it depends entirely on the region
    // (drought-prone vs. flood-prone), so a plain % change with its
    // basis stated avoids implying a value judgment the number can't
    // actually support on its own.
    updateRainfallHistoryChart(historyData) {
        const summaryEl = document.getElementById('rainfall-history-summary');
        const emptyEl = document.getElementById('rainfall-history-empty');
        const sectionEl = document.getElementById('rainfall-history-section');
        if (!this.rainfallHistoryChart || !sectionEl) return;

        const years = historyData && Array.isArray(historyData.years) ? historyData.years : [];
        const validYears = years.filter(y => y.data_source === 'real_openmeteo' && y.annual_mm !== null && y.annual_mm !== undefined);

        if (years.length === 0 || validYears.length === 0) {
            this.rainfallHistoryChart.data.labels = [];
            this.rainfallHistoryChart.data.datasets[0].data = [];
            this.rainfallHistoryChart.update();
            if (summaryEl) { summaryEl.textContent = ''; summaryEl.classList.add('hidden'); }
            if (emptyEl) {
                emptyEl.textContent = (historyData && historyData.error)
                    ? historyData.error
                    : 'Historical rainfall data unavailable for this location.';
                emptyEl.classList.remove('hidden');
            }
            return;
        }

        if (emptyEl) emptyEl.classList.add('hidden');
        if (summaryEl) summaryEl.classList.remove('hidden');

        this.rainfallHistoryChart.data.labels = years.map(y => String(y.year));
        this.rainfallHistoryChart.data.datasets[0].data = years.map(y =>
            (y.data_source === 'real_openmeteo' && y.annual_mm !== null && y.annual_mm !== undefined) ? y.annual_mm : null
        );
        this.rainfallHistoryChart.update();

        if (summaryEl) {
            if (validYears.length < 2) {
                summaryEl.textContent = 'Not enough real historical data at this location to determine a trend.';
            } else {
                const earliest = validYears[0];
                const latest = validYears[validYears.length - 1];
                const pctChange = earliest.annual_mm !== 0
                    ? ((latest.annual_mm - earliest.annual_mm) / Math.abs(earliest.annual_mm)) * 100
                    : 0;
                const sign = pctChange > 0 ? '+' : '';
                summaryEl.textContent =
                    `Rainfall change: ${sign}${pctChange.toFixed(1)}% (annual total, ${earliest.year} to ${latest.year})`;
            }
        }
    }

    // Active Wildfires: surfaces data that was already being fetched on
    // every click (wildfireRiskData, via the same rule-based formula the
    // Prediction tab's stat-risk already shows) plus a new real nearby-
    // fire count (alertSummaryData, via the existing /alerts/summary
    // endpoint — already used by the browser extension, just not the
    // Insight card). Called separately from globe.js, same pattern as
    // updateNdviHistoryChart/updateTempHistoryChart above.
    updateWildfireInsightNode(wildfireRiskData, alertSummaryData) {
        const valueEl = document.getElementById('node-wildfire');
        const iconEl = document.getElementById('node-wildfire-icon');
        const inputsSubEl = document.getElementById('node-wildfire-inputs-sub');
        const nearbySubEl = document.getElementById('node-wildfire-nearby-sub');
        if (!valueEl) return;

        if (!wildfireRiskData || wildfireRiskData.score === null || wildfireRiskData.score === undefined) {
            valueEl.textContent = '--';
            valueEl.style.color = '';
            if (iconEl) iconEl.style.color = '';
            if (inputsSubEl) inputsSubEl.textContent = 'Fire danger index unavailable for this location.';
            if (nearbySubEl) nearbySubEl.textContent = '';
            return;
        }

        const color = this._wildfireRiskColor(wildfireRiskData.category);
        valueEl.textContent = `${wildfireRiskData.score} (${wildfireRiskData.category})`;
        valueEl.style.color = color;
        if (iconEl) iconEl.style.color = color;
        this._setFormulaBadge('node-wildfire', 'Rule-based fire danger index from real inputs — not a trained ML model.');

        if (inputsSubEl) {
            const parts = this._wildfireInputsText(wildfireRiskData.inputs);
            inputsSubEl.textContent = parts.length ? `Rule-based index from: ${parts.join(', ')}` : '';
        }

        // Real nearby fire count from NASA FIRMS (via /alerts/summary) —
        // only populated when the Active Wildfires toggle was on at
        // fetch time (see globe.js); an honest "no fires detected" reads
        // the same as elsewhere in this app (e.g. the globe layer's own
        // all-clear notice) rather than looking like missing data.
        if (nearbySubEl) {
            if (!alertSummaryData || alertSummaryData.data_source?.fires === 'unavailable') {
                nearbySubEl.textContent = '';
            } else if (alertSummaryData.fire_count > 0) {
                const nearest = alertSummaryData.nearest_fire_distance_km;
                nearbySubEl.textContent = `${alertSummaryData.fire_count} active fire(s) within ${alertSummaryData.radius_km}km` +
                    (nearest !== null && nearest !== undefined ? ` — nearest ${nearest.toFixed(1)}km (NASA FIRMS)` : ' (NASA FIRMS)');
            } else {
                nearbySubEl.textContent = `No active fires detected within ${alertSummaryData.radius_km}km (NASA FIRMS)`;
            }
        }
    }

    // Weather Conditions: real current condition for the exact clicked
    // location, via the same /api/weather (OpenWeatherMap) endpoint
    // weather.js's atmospheric sync already relies on — see
    // loadLocationAnalytics's comment in globe.js for why this is a
    // separate fetch rather than reusing that camera-driven one.
    _weatherIcon(main) {
        const iconByMain = {
            'Clear': 'fa-sun',
            'Clouds': 'fa-cloud',
            'Rain': 'fa-cloud-rain',
            'Drizzle': 'fa-cloud-rain',
            'Thunderstorm': 'fa-bolt',
            'Snow': 'fa-snowflake',
            'Mist': 'fa-smog',
            'Fog': 'fa-smog',
            'Haze': 'fa-smog',
        };
        return iconByMain[main] || 'fa-cloud';
    }

    updateWeatherInsightNode(weatherData) {
        const valueEl = document.getElementById('node-weather');
        const iconEl = document.getElementById('node-weather-icon');
        const subEl = document.getElementById('node-weather-sub');
        if (!valueEl) return;

        if (!weatherData || !weatherData.description) {
            valueEl.textContent = '--';
            if (subEl) subEl.textContent = '';
            return;
        }

        // Capitalize each word ("scattered clouds" -> "Scattered Clouds")
        const description = weatherData.description.replace(/\b\w/g, c => c.toUpperCase());
        valueEl.textContent = description;
        if (iconEl) iconEl.className = `fa-solid ${this._weatherIcon(weatherData.main)} data-node-icon`;

        // status: "success" = real OpenWeatherMap reading; "mock" = the
        // deterministic fallback used when no API key is configured (see
        // weather.py's _get_mock_weather) — reuses the existing LIVE/EST
        // badge vocabulary rather than inventing a third label.
        this._setStatBadge('node-weather', weatherData.status === 'success' ? 'live' : 'mock');

        if (subEl) {
            const parts = [];
            if (weatherData.clouds !== null && weatherData.clouds !== undefined) parts.push(`${weatherData.clouds}% cloud cover`);
            if (weatherData.wind_speed !== null && weatherData.wind_speed !== undefined) parts.push(`${weatherData.wind_speed}km/h wind`);
            subEl.textContent = parts.join(', ');
        }
    }

    // 16-point compass rose lookup — used by updateWindInsightNode below
    // for a plain-language direction ("NE") alongside the rotated icon.
    _compassDirection(deg) {
        const dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                      'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
        const index = Math.round(((deg % 360) + 360) % 360 / 22.5) % 16;
        return dirs[index];
    }

    // Wind: real speed + direction for the exact clicked location,
    // replacing the removed global arrow-glyph layer entirely (see the
    // note above where toggleWindLayer used to live in globe.js).
    // Reuses the SAME weatherData already fetched for Weather Conditions
    // (both come from /api/weather) — no extra API call, each node just
    // independently gated by its own toggle.
    updateWindInsightNode(weatherData) {
        const valueEl = document.getElementById('node-wind');
        const iconEl = document.getElementById('node-wind-icon');
        const subEl = document.getElementById('node-wind-sub');
        if (!valueEl) return;

        if (!weatherData || weatherData.wind_speed === null || weatherData.wind_speed === undefined) {
            valueEl.textContent = '--';
            if (subEl) subEl.textContent = '';
            return;
        }

        valueEl.textContent = `${weatherData.wind_speed} km/h`;
        this._setStatBadge('node-wind', weatherData.status === 'success' ? 'live' : 'mock');

        const hasDirection = weatherData.wind_deg !== null && weatherData.wind_deg !== undefined;
        if (iconEl) {
            if (hasDirection) {
                // This icon is a flat 2D element in this side panel, NOT
                // a marker on the rotating 3D globe — there's no camera-
                // orientation ambiguity here the way there was for the
                // removed globe arrows, so a plain CSS rotation is
                // completely correct on its own, no alignedAxis/ENU-frame
                // math needed. Rotated to point where the wind is
                // blowing TOWARD (direction + 180), same convention the
                // removed globe arrows used, for consistency of meaning.
                const towardBearing = (weatherData.wind_deg + 180) % 360;
                iconEl.style.transform = `rotate(${towardBearing}deg)`;
            } else {
                iconEl.style.transform = '';
            }
        }

        if (subEl) {
            subEl.textContent = hasDirection
                ? `From the ${this._compassDirection(weatherData.wind_deg)} (${Math.round(weatherData.wind_deg)}°)`
                : '';
        }
    }

    // AQI OpenAQ verification: a real GENUINELY NEAREST station reading
    // shown alongside the existing WAQI-sourced AQI value/category above
    // it (which this never touches or replaces). Uses aqiVerificationData
    // from the dedicated /aqi-verification endpoint (get_nearest_station_
    // verification in alerts.py) — deliberately separate from
    // alertSummaryData/get_alert_summary, which picks the worst reading
    // within range for the alert system instead of the closest station.
    // Called separately from globe.js, same pattern as the other Insight
    // card node updaters.
    updateAqiVerificationNode(aqiVerificationData) {
        const subEl = document.getElementById('node-aqi-openaq-sub');
        if (!subEl) return;

        // data_source is one of: "live" (a validated, fresh reading from
        // the nearest USABLE station — see get_nearest_station_verification,
        // which now tries progressively farther candidates rather than
        // giving up on the single geographically-nearest one),
        // "missing_api_key", "no_station_in_radius" (zero candidates
        // existed at all), or "unavailable" with reason="no_valid_
        // station_in_radius" (candidates existed but none had a usable
        // reading) or reason="stale" (kept for older cached responses).
        const source = aqiVerificationData?.data_source;

        if (!aqiVerificationData || source === 'missing_api_key') {
            subEl.textContent = 'OpenAQ verification unavailable — OPENAQ_API_KEY not set in backend/.env.';
        } else if (source === 'no_station_in_radius') {
            subEl.textContent = `No OpenAQ station within ${aqiVerificationData.radius_km}km to verify against.`;
        } else if (source === 'live' && aqiVerificationData.nearest_aqi !== null && aqiVerificationData.nearest_aqi !== undefined) {
            const distance = aqiVerificationData.nearest_distance_km;
            const name = aqiVerificationData.nearest_station_name;
            const label = name ? `Nearest usable station (${name})` : 'Nearest usable station';
            subEl.textContent = `${label}${distance !== null && distance !== undefined ? ` (${distance}km away)` : ''}: PM2.5-derived AQI ${aqiVerificationData.nearest_aqi} (OpenAQ)`;
        } else if (aqiVerificationData.reason === 'no_valid_station_in_radius') {
            subEl.textContent = `No OpenAQ station within ${aqiVerificationData.radius_km}km currently has a usable PM2.5 reading.`;
        } else if (aqiVerificationData.reason === 'stale') {
            subEl.textContent = 'Nearest OpenAQ station\'s latest reading is too old to verify against right now.';
        } else {
            subEl.textContent = 'OpenAQ verification unavailable for this location right now.';
        }
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
