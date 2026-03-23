class UIManager {
    constructor() {
        this.tempChart = null;
        this.precipChart = null;
        this.insightChart = null;
        
        this.initEventListeners();
        this.initCharts();
        this.initSidebarTabs();
        
        // Set default tab
        this.switchTab('earth');
    }

    initEventListeners() {
        // Toggle Scenario Panel
        document.getElementById('scenario-btn').addEventListener('click', () => {
            const panel = document.getElementById('scenario-panel');
            panel.classList.toggle('hidden');
        });

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
                let colorClass = prediction.risk_level === 'Critical' ? 'color: var(--danger);' : 
                                 prediction.risk_level === 'High' ? 'color: var(--warning);' : 'color: var(--success);';
                
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
                
                // Triger event for globe to show heatmap/effects
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

        document.getElementById('apply-global-btn').addEventListener('click', () => {
             const temp = parseFloat(tempSlider.value);
             const rain = parseFloat(rainSlider.value);
             
             // Trigger global reaction on globe
             document.dispatchEvent(new CustomEvent('globalSimulationApplied', { 
                 detail: { tempOffset: temp, rainOffset: rain } 
             }));
        });

        // Close Popup
        document.getElementById('close-popup').addEventListener('click', () => {
            document.getElementById('sensor-popup').classList.remove('active');
        });

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
                
                playInterval = setInterval(() => {
                    let val = parseInt(slider.value);
                    if (val >= 24) {
                        slider.value = 0; // Loop back
                    } else {
                        slider.value = val + 1;
                    }
                    this.updateDateDisplay(slider.value);
                    // Trigger globe update
                    slider.dispatchEvent(new Event('input'));
                }, 1000 / parseInt(speedSelect.value || 1));
            } else {
                clearInterval(playInterval);
            }
        });

        document.getElementById('timeline-slider').addEventListener('input', (e) => {
            this.updateDateDisplay(e.target.value);
        });

        // Minimal Mode Toggle
        const minimalToggle = document.getElementById('minimal-toggle');
        minimalToggle.addEventListener('click', () => {
            document.body.classList.toggle('minimal-mode');
            const icon = minimalToggle.querySelector('i');
            if (document.body.classList.contains('minimal-mode')) {
                icon.className = 'fa-solid fa-compress';
                // Trigger globe auto-rotate if needed
                document.dispatchEvent(new CustomEvent('minimalModeChanged', { detail: { active: true } }));
            } else {
                icon.className = 'fa-solid fa-expand';
                document.dispatchEvent(new CustomEvent('minimalModeChanged', { detail: { active: false } }));
            }
        });
    }

    initSidebarTabs() {
        const tabs = document.querySelectorAll('.tab-item');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const targetTab = tab.getAttribute('data-tab');
                this.switchTab(targetTab);
            });
        });
    }

    switchTab(tabName) {
        // Update body attribute for CSS targeting
        document.body.setAttribute('data-active-tab', tabName);
        
        // Update active class on tab items
        const tabs = document.querySelectorAll('.tab-item');
        tabs.forEach(t => {
            if (t.getAttribute('data-tab') === tabName) {
                t.classList.add('active');
            } else {
                t.classList.remove('active');
            }
        });

        // Specific logic for certain tabs
        if (tabName === 'earth') {
            // Earth is pure globe
        }
        
        console.log(`Switched to tab: ${tabName}`);
    }

    updateDateDisplay(value) {
        const display = document.getElementById('current-date-display');
        const year = 2024 + Math.floor(value / 12);
        const monthIndex = value % 12;
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        display.innerText = `${monthNames[monthIndex]} ${year}`;
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

    updateAnalyticsPanel(climateData, envData, shiData) {
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
        this.updateInsightCard(climateData, envData);
    }

    updateInsightCard(climateData, envData) {
        const card = document.getElementById('insight-card');
        const history = climateData.historical_trends;
        const latest = history[history.length - 1];

        document.getElementById('node-temp').innerText = `${latest.avg_temp_c}°C`;
        document.getElementById('node-precip').innerText = `${latest.total_rainfall_mm}mm`;
        document.getElementById('node-anomaly').innerText = `${climateData.current_anomaly}°C`;
        document.getElementById('node-risk').innerText = envData ? `${envData.risk_index || 45}%` : '45%';

        if (this.insightChart) {
            this.insightChart.data.datasets[0].data = history.map(h => h.avg_temp_c);
            this.insightChart.update();
        }

        card.classList.add('active');
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
