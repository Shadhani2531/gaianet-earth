class ApiService {
    async get(endpoint, params = {}) {
        try {
            const url = new URL(`${CONFIG.API_BASE_URL}${endpoint}`);
            Object.keys(params).forEach(key => url.searchParams.append(key, params[key]));
            
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`API error: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error("API Request failed:", error);
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
        return this.get('/weather', { lat, lon });
    }

    async getVegetation() {
        return this.get('/vegetation');
    }

    async getWildfires() {
        return this.get('/wildfires');
    }

    async getClimate(lat, lon) {
        return this.get('/climate', { lat, lon });
    }

    async getPrediction(scenario, lat, lon) {
        return this.get('/prediction', { scenario, lat, lon });
    }

    async getStations() {
        return this.get('/stations');
    }

    async getShiIndiaLive() {
        return this.get('/shi-india-live');
    }
}

const api = new ApiService();
