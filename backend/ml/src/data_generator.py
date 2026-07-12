"""
GaiaNet Earth - AQI Prediction ML Pipeline
File: backend/ml/src/data_generator.py
Purpose: Generates physically realistic synthetic environmental data for development and training.
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def calculate_subindex(value, bp_vals, bp_aqis):
    """
    Linearly interpolates AQI subindex based on pollutant concentrations and EPA breakpoints.
    """
    for i in range(len(bp_vals)):
        low_val, high_val = bp_vals[i]
        low_aqi, high_aqi = bp_aqis[i]
        if low_val <= value <= high_val:
            return round(((high_aqi - low_aqi) / (high_val - low_val)) * (value - low_val) + low_aqi)
    # If it exceeds maximum breakpoint, return upper limit or extrapolate
    return bp_aqis[-1][1]

def calculate_epa_aqi(pm25, pm10, no2, so2, co):
    """
    Calculates the aggregate Air Quality Index (AQI) based on US EPA breakpoints.
    AQI is defined as the maximum sub-index of the active pollutants.
    """
    # Breakpoints: (Low Concentration, High Concentration), (Low AQI, High AQI)
    
    # PM2.5 (ug/m3)
    pm25_bp_vals = [(0.0, 12.0), (12.1, 35.4), (35.5, 55.4), (55.5, 150.4), (150.5, 250.4), (250.5, 500.4)]
    pm25_bp_aqi = [(0, 50), (51, 100), (101, 150), (151, 200), (201, 300), (301, 500)]
    sub_pm25 = calculate_subindex(pm25, pm25_bp_vals, pm25_bp_aqi)

    # PM10 (ug/m3)
    pm10_bp_vals = [(0, 54), (55, 154), (155, 254), (255, 354), (355, 424), (425, 604)]
    pm10_bp_aqi = [(0, 50), (51, 100), (101, 150), (151, 200), (201, 300), (301, 500)]
    sub_pm10 = calculate_subindex(pm10, pm10_bp_vals, pm10_bp_aqi)

    # NO2 (ppb)
    no2_bp_vals = [(0, 53), (54, 100), (101, 360), (361, 649), (650, 1249), (1250, 2049)]
    no2_bp_aqi = [(0, 50), (51, 100), (101, 150), (151, 200), (201, 300), (301, 500)]
    sub_no2 = calculate_subindex(no2, no2_bp_vals, no2_bp_aqi)

    # SO2 (ppb)
    so2_bp_vals = [(0, 35), (36, 75), (76, 185), (186, 304), (305, 604), (605, 1004)]
    so2_bp_aqi = [(0, 50), (51, 100), (101, 150), (151, 200), (201, 300), (301, 500)]
    sub_so2 = calculate_subindex(so2, so2_bp_vals, so2_bp_aqi)

    # CO (ppm)
    co_bp_vals = [(0.0, 4.4), (4.5, 9.4), (9.5, 12.4), (12.5, 15.4), (15.5, 30.4), (30.5, 50.4)]
    co_bp_aqi = [(0, 50), (51, 100), (101, 150), (151, 200), (201, 300), (301, 500)]
    sub_co = calculate_subindex(co, co_bp_vals, co_bp_aqi)

    # Aggregate AQI is the maximum of all sub-indices
    return max(sub_pm25, sub_pm10, sub_no2, sub_so2, sub_co)

def generate_synthetic_data(output_path="backend/ml/data/raw/synthetic_air_quality.csv", num_days=60, seed=42):
    """
    Generates realistic, physically constrained synthetic environmental data.
    - Temperature: Diurnal cycles (coldest at 5 AM, warmest at 3 PM)
    - Humidity: Inversely related to Temperature
    - Pollutants (PM2.5, PM10, NO2, SO2, CO): Spikes during traffic rush hour (8-10 AM, 5-8 PM) 
      and night-time atmospheric inversion.
    - AQI: Realistically computed with standard EPA equations and some minor noise.
    """
    np.random.seed(seed)
    print(f"Generating synthetic environmental dataset for {num_days} days...")

    start_date = datetime(2026, 1, 1, 0, 0, 0)
    total_hours = num_days * 24
    
    timestamps = [start_date + timedelta(hours=i) for i in range(total_hours)]
    
    data = []
    for i, ts in enumerate(timestamps):
        hour = ts.hour
        day_of_week = ts.weekday()
        is_weekend = 1 if day_of_week >= 5 else 0
        
        # 1. Temperature (°C): Base cycle + seasonal warming trend + weather noise
        # Diurnal cycle peaks at 15:00 (3 PM), lowest at 05:00 (5 AM)
        diurnal_temp = 8 * np.sin((hour - 9) * 2 * np.pi / 24)
        base_temp = 25.0 + (i / total_hours) * 5.0 # gradual seasonal increase
        weather_noise = np.random.normal(0, 1.5)
        temperature = round(base_temp + diurnal_temp + weather_noise, 1)
        temperature = max(10.0, min(temperature, 45.0))  # physical limits
        
        # 2. Humidity (%): Inversely correlated with temperature + noise
        base_humidity = 80.0 - (temperature - 20.0) * 1.5
        humidity_noise = np.random.normal(0, 5)
        humidity = int(base_humidity + humidity_noise)
        humidity = max(15, min(humidity, 95))
        
        # 3. Combustion Proxy (Traffic/Industry activity coefficients)
        # Higher on weekdays, peaks at rush hours: 8-10 AM and 5-8 PM
        rush_hour_coeff = 0.0
        if not is_weekend:
            if 8 <= hour <= 10:
                rush_hour_coeff = 2.5
            elif 17 <= hour <= 20:
                rush_hour_coeff = 3.0
            elif 11 <= hour <= 16:
                rush_hour_coeff = 1.2
            else:
                rush_hour_coeff = 0.5
        else: # weekends
            if 10 <= hour <= 14:
                rush_hour_coeff = 1.5
            elif 18 <= hour <= 21:
                rush_hour_coeff = 1.8
            else:
                rush_hour_coeff = 0.6
                
        # Atmospheric Inversion Layer effect: at night and early morning (11 PM - 7 AM), 
        # cooler air traps pollutants closer to ground, increasing concentration.
        inversion_coeff = 1.4 if (hour >= 23 or hour <= 7) else 0.8
        
        # Base pollutant values
        # PM2.5 (ug/m3) - Clean day base ~10, Polluted base ~80
        pm25_base = np.random.choice([12.0, 45.0, 75.0], p=[0.5, 0.3, 0.2])
        pm25_noise = np.random.lognormal(mean=1.5, sigma=0.4)
        pm25 = pm25_base * rush_hour_coeff * inversion_coeff + pm25_noise
        pm25 = max(1.0, min(pm25, 350.0)) # Clip within bounds
        
        # PM10 (ug/m3) - Correlated with PM2.5 but includes dust/soil particles (wind effect simulation)
        wind_speed = np.random.uniform(2, 25)
        dust_coeff = 1.0 + (wind_speed / 15) if wind_speed > 15 else 1.0
        pm10 = pm25 * np.random.uniform(1.2, 1.8) + (wind_speed * dust_coeff)
        pm10 = max(pm25 + 1.0, min(pm10, 450.0))
        
        # NO2 (ppb) - Traffic exhaust related
        no2 = 10.0 * rush_hour_coeff * inversion_coeff + np.random.normal(5, 2)
        no2 = max(1.0, min(no2, 150.0))
        
        # SO2 (ppb) - Industrial emission
        so2 = 4.0 * inversion_coeff + np.random.normal(2, 1)
        so2 = max(0.5, min(so2, 80.0))
        
        # CO (ppm) - Combustion incomplete exhaust
        co = 0.4 * rush_hour_coeff * inversion_coeff + np.random.normal(0.2, 0.08)
        co = max(0.1, min(co, 15.0))
        
        # Calculate true EPA AQI
        aqi_calculated = calculate_epa_aqi(pm25, pm10, no2, so2, co)
        # Add slight observation noise (representing sensor fluctuations)
        aqi_noise = np.random.normal(0, 2)
        aqi = int(max(0, min(500, aqi_calculated + aqi_noise)))
        
        # Round columns for clean storage
        data.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "temperature": round(temperature, 1),
            "humidity": int(humidity),
            "PM2.5": round(pm25, 1),
            "PM10": round(pm10, 1),
            "NO2": round(no2, 1),
            "SO2": round(so2, 1),
            "CO": round(co, 2),
            "AQI": aqi
        })

    df = pd.DataFrame(data)
    
    # Introduce synthetic missing values (~1% randomly) to test pipeline imputation
    mask_cols = ["temperature", "humidity", "PM2.5", "NO2"]
    for col in mask_cols:
        indices = np.random.choice(df.index, size=int(len(df) * 0.01), replace=False)
        df.loc[indices, col] = np.nan
        
    # Save directory creation
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Dataset successfully created and saved to '{output_path}'. Total records: {len(df)}")
    return df

if __name__ == "__main__":
    generate_synthetic_data()
