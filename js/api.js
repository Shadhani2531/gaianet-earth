class ApiService {
    // Tracks WHY the last call to `get()` returned null, so callers can
    // show an accurate message instead of always blaming "the backend
    // isn't running". Three real, different causes were previously all
    // collapsed into one generic message:
    //   'network'   - fetch() itself threw (server truly unreachable,
    //                 CORS blocked, DNS/connection refused) -> backend
    //                 really is down or not reachable from this origin.
    //   'http'      - server responded but with a non-2xx status (e.g. a
    //                 500 from an unhandled backend exception).
    //   'empty'     - server responded 200 with valid JSON, but the
    //                 payload itself was empty (e.g. an upstream API like
    //                 Open-Meteo/OpenAQ failed server-side, or an API key
    //                 is missing) -> the backend IS running fine, the
    //                 problem is upstream/config, not the server process.
    lastErrorKind = null;

    async get(endpoint, params = {}) {
        this.lastErrorKind = null;
        try {
            const url = new URL(`${CONFIG.API_BASE_URL}${endpoint}`);
            // Only append params that actually have a value — passing
            // undefined/null through here used to become the literal string
            // "undefined" in the query string (e.g. /climate?lat=undefined),
            // which fails FastAPI's type validation and silently returns
            // nothing to the caller.
            Object.keys(params).forEach(key => {
                const value = params[key];
                if (value !== undefined && value !== null) {
                    url.searchParams.append(key, value);
                }
            });

            let response;
            try {
                response = await fetch(url);
            } catch (networkError) {
                // fetch() only throws for network-level failures: server
                // unreachable, connection refused, CORS block, DNS failure.
                // This is the ONE case that genuinely means "backend isn't
                // running/reachable".
                this.lastErrorKind = 'network';
                throw networkError;
            }

            if (!response.ok) {
                this.lastErrorKind = 'http';
                throw new Error(`API error: ${response.status}`);
            }
            const data = await response.json();
            if (data && Array.isArray(data.features) && data.features.length === 0) {
                this.lastErrorKind = 'empty';
            } else if (Array.isArray(data) && data.length === 0) {
                this.lastErrorKind = 'empty';
            }
            return data;
        } catch (error) {
            console.error(`API request to ${endpoint} failed [${this.lastErrorKind || 'unknown'}]:`, error);
            return null;
        }
    }

    async getEnvironment(lat, lon) {
        return this.get('/environment', { lat, lon });
    }

    async getShi(lat, lon) {
        return this.get('/shi', { lat, lon });
    }

    async getWeather(lat, lon) {
        // Was calling /weather (no such route -> 404) instead of the real
        // /api/weather endpoint used by weather.js's ASE sync.
        return this.get('/api/weather', { lat, lon });
    }

    async getVegetation() {
        return this.get('/vegetation');
    }

    async getNdviValue(lat, lon, date = null) {
        return this.get('/ndvi-value', { lat, lon, date });
    }

    async getWildfires() {
        return this.get('/wildfires');
    }

    async getClimate(lat, lon) {
        return this.get('/climate', { lat, lon });
    }

    async getPrediction(lat, lon, { forestLossPct = 0, emissionsIncreasePct = 0, isTropical = true } = {}) {
        return this.get('/prediction', {
            lat, lon,
            forest_loss_pct: forestLossPct,
            emissions_increase_pct: emissionsIncreasePct,
            is_tropical: isTropical
        });
    }

    // --- Predictive AI (Phase 2): real forecasts + fire danger index ---
    async getWeatherForecast(lat, lon, days = 7) {
        return this.get('/forecast/weather', { lat, lon, days });
    }

    async getAirQualityForecast(lat, lon, days = 5) {
        return this.get('/forecast/air-quality', { lat, lon, days });
    }

    async getWildfireRisk(lat, lon) {
        return this.get('/wildfire-risk', { lat, lon });
    }

    // --- One-Click Impact Report (Phase 3) ---
    async getImpactReport(lat, lon, radiusKm = 50) {
        return this.get('/reports/impact', { lat, lon, radius_km: radiusKm });
    }

    async getStations() {
        return this.get('/stations');
    }

    async getRainfall() {
        return this.get('/rainfall');
    }

    async getWeatherConditions() {
        return this.get('/weather-conditions');
    }

    async getWind() {
        return this.get('/wind');
    }

    async getStationsWithReadings() {
        return this.get('/stations-with-readings');
    }

    async getShiGlobal() {
        return this.get('/shi-global');
    }

    async getCountryBoundaries() {
        return this.get('/country-boundaries');
    }

    async submitReport(reportData) {
        try {
            const response = await fetch(`${CONFIG.API_BASE_URL}/api/reports`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reportData)
            });
            return await response.json();
        } catch (error) {
            console.error("Report submission failed:", error);
            return null;
        }
    }

    async getReports() {
        return this.get('/api/reports');
    }

    // --- Ask Gaia (Phase 3) ---
    async askGaia(message, history = [], context = null) {
        try {
            const response = await fetch(`${CONFIG.API_BASE_URL}/gaia/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message, history, context }),
            });
            if (!response.ok) {
                throw new Error(`API error: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error("Ask Gaia request failed:", error);
            return null;
        }
    }
}

const api = new ApiService();
