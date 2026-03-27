/**
 * Causal Simulation Logic
 * Handles the "Digital Lab" interdependent variable forecasting.
 * Logic: Temperature -> NDVI/AQI impact.
 */
class SimulationEngine {
    constructor() {
        this.baseConfig = {
            ndvi_sensitivity: 0.15, // 1 degree = -15% NDVI
            aqi_sensitivity: 0.2,   // 1 degree = +20% AQI degradation
            recovery_rate: 0.05     // Baseline ecosystem recovery per month
        };
    }

    /**
     * Calculates the impact of climate changes on environmental health.
     */
    forecastImpact(tempOffset, precipitationOffset) {
        // Causal Math:
        // 1. High Temp + Low Rain -> Drought -> NDVI drops significantly
        // 2. High Temp -> Fire Risk Spikes -> SHI Drops
        
        let ndviImpact = -(tempOffset * this.baseConfig.ndvi_sensitivity);
        let fireRisk = 0;

        if (precipitationOffset < 0) {
            // Drought Cascade:
            const droughtFactor = Math.abs(precipitationOffset / 100);
            ndviImpact -= (droughtFactor * 0.4); // Drastic drop if 0% rain
            fireRisk = Math.min(100, (tempOffset * 10) + (droughtFactor * 50));
        } else {
            ndviImpact += (precipitationOffset / 100) * 0.1; // Recovery
            fireRisk = Math.max(0, (tempOffset * 5) - (precipitationOffset / 10));
        }

        let aqiImpact = (tempOffset * this.baseConfig.aqi_sensitivity);
        if (fireRisk > 70) aqiImpact += 0.3; // Fire smog impact
        
        // Sustainability Health Index (SHI)
        // Baseline 84, drops with negative impacts
        let shiChange = (ndviImpact * 50) - (aqiImpact * 10) - (fireRisk / 5);
        
        return {
            ndviImpact: parseFloat(ndviImpact.toFixed(2)),
            aqiImpact: parseFloat(aqiImpact.toFixed(2)),
            fireRisk: Math.round(fireRisk),
            shiScore: Math.max(0, Math.min(100, 84 + shiChange))
        };
    }
}

const simulation = new SimulationEngine();
