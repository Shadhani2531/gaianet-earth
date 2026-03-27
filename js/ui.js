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
        
        // Set default tab
        this.switchTab('earth');
    }

    initSearch() {
        const searchInput = document.querySelector('.search-input');
        if (!searchInput) return;

        searchInput.addEventListener('keypress', async (e) => {
            if (e.key === 'Enter') {
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
            }
        });
    }

    initEventListeners() {
        // Toggle Scenario Panel
        document.getElementById('scenario-btn').addEventListener('click', () => {
            const panel = document.getElementById('scenario-panel');
            panel.classList.toggle('hidden');
        });

        // NDVI Legend Toggle logic
        const ndviCheckbox = document.getElementById('layer-ndvi');
        if (ndviCheckbox) {
            ndviCheckbox.addEventListener('change', (e) => {
                const legend = document.getElementById('ndvi-legend-box');
                if (legend) {
                    if (e.target.checked && document.body.getAttribute('data-active-tab') === 'insight') {
                        legend.classList.remove('hidden');
                    } else {
                        legend.classList.add('hidden');
                    }
                }
            });
        }

        // Run Scenario
        document.getElementById('run-scenario-btn').addEventListener('click', async () => {
            const scenario = document.getElementById('scenario-select').value;
            if (!scenario) {
                alert("Please select a scenario.");
                return;
            }
            
            const resultsDiv = document.getElementById('simulation-results');
            resultsDiv.innerHTML = '<p style="color:var(--text-secondary);"><i class="fa-solid fa-spinner fa-spin"></i> Running simulation models...</p>';
            
            // Get center coordinates from globe (mocked for now)
            const lat = CONFIG.DEFAULT_COORDINATES.lat; 
            const lon = CONFIG.DEFAULT_COORDINATES.lon;

            const prediction = await api.getPrediction(scenario, lat, lon);
            
            if (prediction) {
                resultsDiv.innerHTML = `
                    <div style="background: rgba(0,0,0,0.3); padding: 10px; border-radius: 6px; font-size: 0.9rem;">
                        <p><strong>Predicted Probabilities:</strong></p>
                        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:5px; margin: 10px 0;">
                            <div>🔥 Fire: ${prediction.probabilities.wildfire}%</div>
                            <div>🌵 Drought: ${prediction.probabilities.drought}%</div>
                            <div>🌊 Flood: ${prediction.probabilities.flood}%</div>
                        </div>
                        <p><strong>Impact:</strong> +${prediction.predicted_temp_change_c}°C</p>
                        <p><strong>Sea Level:</strong> +${prediction.sea_level_rise_cm}cm</p>
                    </div>
                `;
                
                document.dispatchEvent(new CustomEvent('scenarioRan', { detail: prediction }));
            } else {
                resultsDiv.innerHTML = '<p style="color:var(--danger);">Simulation failed to execute.</p>';
            }
        });

        // --- GLOBAL SIMULATION (SCREEN 5) ---
        const tempSlider = document.getElementById('global-temp-slider');
        const rainSlider = document.getElementById('global-rain-slider');
        
        tempSlider.addEventListener('input', (e) => {
            document.getElementById('temp-offset-val').innerText = e.target.value;
        });
        
        rainSlider.addEventListener('input', (e) => {
            document.getElementById('rain-offset-val').innerText = e.target.value;
        });

        // Apply Global Simulation
        document.getElementById('apply-global-btn').addEventListener('click', () => {
             const temp = parseFloat(tempSlider.value);
             const rain = parseFloat(rainSlider.value);
             
             // 1. Calculate Causal Impact
             const impact = simulation.forecastImpact(temp, rain);
             
             // 2. Update HUD Metrics
             this.updateSHIGauge(impact.shiScore);
             document.getElementById('stat-ndvi').innerText = (0.7 + impact.ndviImpact).toFixed(2);
             document.getElementById('stat-aqi').innerText = Math.round(50 * (1 + impact.aqiImpact));
             
             // 3. Cascade Effect: Update Risk Index across tabs
             const riskVal = `${impact.fireRisk}%`;
             const riskColor = impact.fireRisk > 70 ? 'var(--danger)' : (impact.fireRisk > 40 ? 'var(--warning-amber)' : 'var(--success)');
             
             const riskElem = document.getElementById('node-risk');
             if (riskElem) {
                 riskElem.innerText = riskVal;
                 riskElem.style.color = riskColor;
             }

             const statRiskElem = document.getElementById('stat-risk');
             if (statRiskElem) {
                 statRiskElem.innerText = riskVal;
                 statRiskElem.style.color = riskColor;
             }

             // 4. Trigger global reaction on globe
             document.dispatchEvent(new CustomEvent('globalSimulationApplied', { 
                 detail: { tempOffset: temp, rainOffset: rain, impact: impact } 
             }));

             this.showNeuralScan(`Simulation Applied: Risk Index at ${impact.fireRisk}%`);
        });

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

        container.innerHTML = reports.reverse().map(r => `
            <div class="report-card animate-in">
                <div class="report-header">
                    <span class="report-type">${r.incident_type.toUpperCase()}</span>
                    <span class="report-severity">LVL ${r.severity}</span>
                </div>
                <div class="report-desc">${r.description}</div>
                <div class="report-meta">
                    <span><i class="fa-solid fa-location-dot"></i> ${r.lat.toFixed(2)}, ${r.lon.toFixed(2)}</span>
                    <span>JUST NOW</span>
                </div>
            </div>
        `).join('');
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

    initSecondaryEvents() {
        // Close Insight Card
        document.getElementById('close-insight').addEventListener('click', () => {
            document.getElementById('insight-card').classList.remove('active');
        });

        // Timeline playback
        const playBtn = document.getElementById('play-btn');
        let isPlaying = false;
        let playInterval;

        playBtn.addEventListener('click', () => {
            isPlaying = !isPlaying;
            playBtn.innerHTML = isPlaying ? '<i class="fa-solid fa-pause"></i>' : '<i class="fa-solid fa-play"></i>';
            
            if (isPlaying) {
                const slider = document.getElementById('timeline-slider');
                const speedSelect = document.getElementById('speed-select');
                const speed = speedSelect ? parseInt(speedSelect.value) : 1;
                
                playInterval = setInterval(() => {
                    let val = parseInt(slider.value);
                    if (val >= 100) slider.value = 0;
                    else slider.value = val + 1;
                    
                    this.updateDateDisplay(slider.value, 'primary');
                    slider.dispatchEvent(new Event('input'));
                }, 1000 / speed);
            } else {
                clearInterval(playInterval);
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
                    description: document.getElementById('report-description').value
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

    switchTab(tabName) {
        // Update body attribute for CSS targeting
        document.body.setAttribute('data-active-tab', tabName);
        
        // Tab-Specific Visibility Mapping (Refined HUD)
        const uiElements = {
            'search': document.querySelector('.floating-controller'),
            'left': document.querySelector('.left-panel'),
            'right': document.querySelector('.right-panel'),
            'bottom': document.querySelector('.bottom-panel'),
            'insight': document.getElementById('insight-card'),
            'reports': document.getElementById('reports-panel'),
            'scenario': document.getElementById('scenario-panel'),
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
                if(uiElements.search) uiElements.search.classList.remove('hidden');
                if(uiElements.left) {
                    uiElements.left.classList.remove('hidden');
                    if(uiElements.intelligence) uiElements.intelligence.classList.remove('hidden');
                }
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
                break;

            case 'prediction':
            case 'forecast':
                if(uiElements.search) uiElements.search.classList.remove('hidden');
                if(uiElements.right) uiElements.right.classList.remove('hidden');
                if(uiElements.shi_gauge) uiElements.shi_gauge.classList.remove('hidden');
                if(uiElements.left) {
                    uiElements.left.classList.remove('hidden');
                    if(uiElements.intelligence) uiElements.intelligence.classList.remove('hidden');
                }
                break;

            case 'lab':
            case 'simulator':
                if(uiElements.search) uiElements.search.classList.remove('hidden');
                if(uiElements.left) {
                    uiElements.left.classList.remove('hidden');
                    if(uiElements.scenario) uiElements.scenario.classList.remove('hidden');
                }
                if(uiElements.right) {
                    uiElements.right.classList.remove('hidden');
                    if(uiElements.charts) uiElements.charts.forEach(c => c.classList.remove('hidden'));
                }
                break;
                
            case 'reports':
                if(uiElements.reports) uiElements.reports.classList.remove('hidden');
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
        const startYear = 1984;
        const totalYears = 46;
        const year = startYear + Math.floor((value / 100) * totalYears);
        const monthIndex = Math.floor(((value / 100) * (totalYears * 12)) % 12);
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        
        if (type === 'primary') {
            document.getElementById('current-date-display').innerText = `${monthNames[monthIndex]} ${year}`;
        }
    }

    initTimelineEvents() {
        const primarySlider = document.getElementById('timeline-slider');
        const comparisonSlider = document.getElementById('comparison-slider');
        const splitBtn = document.getElementById('split-screen-btn');
        const comparisonNode = document.getElementById('comparison-slider-node');

        primarySlider.addEventListener('input', (e) => {
            if (window.globeManager) window.globeManager.updateTime(e.target.value, 'primary');
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
        this.updateInsightCard(climateData, envData, ndviData);
    }

    updateInsightCard(climateData, envData, ndviData) {
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
            
            if (ndviData) {
                const riskVal = ndviData.wildfire_risk || "Low";
                const riskPercent = ndviData.wildfire_risk_index || 45;
                document.getElementById('node-risk').innerText = `${riskPercent}% (${riskVal})`;
                
                const riskElem = document.getElementById('node-risk');
                if (riskVal === 'Low') riskElem.style.color = 'var(--success)';
                else if (riskVal === 'Moderate') riskElem.style.color = 'var(--warning-amber)';
                else riskElem.style.color = 'var(--danger)';
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
