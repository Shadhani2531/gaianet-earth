"""
GaiaNet Earth - AQI Prediction ML Pipeline
File: backend/ml/src/predict.py
Purpose: Loads the trained best model and scaler, accepts arbitrary environmental inputs,
         calculates predictions, estimates confidence scores, ranks feature contributions,
         and simulates future hourly forecasts.
"""

import os
import json
import numpy as np
import pandas as pd
import joblib

class AQIPredictionEngine:
    """
    Production-ready inference engine for predicting AQI and simulating forecasts.
    """
    def __init__(self, models_dir="backend/ml/models"):
        self.models_dir = models_dir
        self.model_path = os.path.join(models_dir, "best_model.joblib")
        self.scaler_path = os.path.join(models_dir, "scaler.joblib")
        self.metadata_path = os.path.join(models_dir, "model_metadata.json")
        self.medians_path = os.path.join(models_dir, "feature_medians.joblib")
        
        # Load assets
        if not os.path.exists(self.model_path) or not os.path.exists(self.scaler_path):
            raise FileNotFoundError(
                f"Model or Scaler not found in {models_dir}. Please run train.py first."
            )
            
        self.model = joblib.load(self.model_path)
        self.scaler = joblib.load(self.scaler_path)
        
        # Load optional metadata and medians
        self.metadata = {}
        if os.path.exists(self.metadata_path):
            with open(self.metadata_path, "r") as f:
                self.metadata = json.load(f)
                
        self.medians = {}
        if os.path.exists(self.medians_path):
            self.medians = joblib.load(self.medians_path)

        self.feature_names = ['temperature', 'humidity', 'PM2.5', 'PM10', 'NO2', 'SO2', 'CO']
        
    def get_health_category(self, aqi):
        """
        Classifies AQI into US EPA health standard categories.
        """
        if aqi <= 50:
            return "Good", "Green", "Air quality is satisfactory, and air pollution poses little or no risk."
        elif aqi <= 100:
            return "Moderate", "Yellow", "Air quality is acceptable. However, there may be a risk for some people."
        elif aqi <= 150:
            return "Unhealthy for Sensitive Groups", "Orange", "Members of sensitive groups may experience health effects."
        elif aqi <= 200:
            return "Unhealthy", "Red", "Everyone may begin to experience health effects; members of sensitive groups may experience more serious health effects."
        elif aqi <= 300:
            return "Very Unhealthy", "Purple", "Health alert: The risk of health effects is increased for everyone."
        else:
            return "Hazardous", "Maroon", "Health warning of emergency conditions: Everyone is more likely to be affected."

    def predict(self, input_dict):
        """
        Predicts AQI for a single set of environmental inputs.
        - input_dict: {'temperature': 25.0, 'humidity': 60, 'PM2.5': 15.0, ...}
        
        Returns: Dict containing predicted AQI, category, confidence, and feature contributions.
        """
        # Validate and impute missing fields using training medians
        cleaned_input = []
        for feat in self.feature_names:
            val = input_dict.get(feat)
            if val is None or np.isnan(val):
                val = self.medians.get(feat, 0.0)
            cleaned_input.append(float(val))
            
        # Convert to DataFrame with feature names to avoid sklearn StandardScaler warnings
        raw_features_df = pd.DataFrame([cleaned_input], columns=self.feature_names)
        
        # Scale the features
        scaled_features = self.scaler.transform(raw_features_df)
        
        # Predict AQI
        # Pass a DataFrame with feature names if the model is fitted with them,
        # or convert scaled_features back to a DataFrame.
        # Let's wrap scaled_features in a DataFrame as well to satisfy the model.
        scaled_features_df = pd.DataFrame(scaled_features, columns=self.feature_names)
        predicted_aqi = self.model.predict(scaled_features_df)[0]
        # Keep AQI in valid bounds (0 to 500)
        predicted_aqi = max(0.0, min(500.0, float(predicted_aqi)))
        
        # 1. Calculate Confidence Score
        # R2 score represents baseline capability (e.g. 90%).
        # We penalize confidence if the input features deviate significantly (outliers) from the train set.
        # Average Absolute Z-score measures deviation.
        avg_z = np.mean(np.abs(scaled_features[0]))
        r2_pct = self.metadata.get("metrics", {}).get("R2", 0.90) * 100
        
        # Outlier penalty: decrease confidence if average Z-score is high (e.g. > 1.5 standard deviations)
        outlier_penalty = max(0.0, (avg_z - 1.5) * 12.0)
        confidence_score = max(40.0, min(99.0, r2_pct - outlier_penalty))
        
        # 2. Calculate Feature Contribution Summary
        # Approximated by taking: |scaled_input * feature_importance| and normalizing to 100%
        importances = []
        if self.metadata and "feature_importance_ranking" in self.metadata:
            # Map saved importances to the feature list order
            imp_map = {item["Feature"]: item["Importance"] for item in self.metadata["feature_importance_ranking"]}
            importances = [imp_map.get(f, 1.0/len(self.feature_names)) for f in self.feature_names]
        else:
            importances = [1.0/len(self.feature_names)] * len(self.feature_names)
            
        contributions = np.abs(scaled_features[0]) * np.array(importances)
        total_contrib = np.sum(contributions)
        if total_contrib > 0:
            contributions = (contributions / total_contrib) * 100
        else:
            contributions = np.ones(len(self.feature_names)) * (100.0 / len(self.feature_names))
            
        contrib_ranking = [
            {
                "feature": self.feature_names[idx],
                "raw_value": cleaned_input[idx],
                "relative_contribution_pct": round(float(contributions[idx]), 1)
            } for idx in range(len(self.feature_names))
        ]
        contrib_ranking = sorted(contrib_ranking, key=lambda x: x["relative_contribution_pct"], reverse=True)
        
        category, color, health_advice = self.get_health_category(predicted_aqi)
        
        return {
            "predicted_aqi": round(predicted_aqi, 1),
            "category": category,
            "color": color,
            "health_advice": health_advice,
            "confidence_score_pct": round(confidence_score, 1),
            "dominant_pollutant": contrib_ranking[0]["feature"],
            "feature_contributions": contrib_ranking
        }

    def simulate_future_forecast(self, base_inputs, hours_ahead=5):
        """
        Simulates future AQI hourly readings starting from base_inputs.
        Models natural diurnal cycles (e.g. rising/cooling temp, rush-hour build-ups).
        """
        forecast = []
        current_temp = base_inputs.get("temperature", 25.0)
        current_humidity = base_inputs.get("humidity", 50.0)
        current_pm25 = base_inputs.get("PM2.5", 35.0)
        current_pm10 = base_inputs.get("PM10", 55.0)
        current_no2 = base_inputs.get("NO2", 15.0)
        current_so2 = base_inputs.get("SO2", 4.0)
        current_co = base_inputs.get("CO", 0.6)
        
        print(f"Simulating {hours_ahead}-hour environmental prediction sequence...")
        
        for hour in range(1, hours_ahead + 1):
            # Model temporal physics modifications
            # 1. Temperature: cycles slightly (e.g., warmer or cooler depending on step)
            # Let's assume temp changes by +0.8C or -0.8C per hour depending on time. We'll alternate.
            temp_delta = 0.5 * np.cos(hour * np.pi / 6)
            current_temp = max(15.0, min(42.0, current_temp + temp_delta))
            
            # 2. Humidity: inverse of temperature
            humidity_delta = -1.2 * temp_delta
            current_humidity = max(20.0, min(95.0, current_humidity + humidity_delta))
            
            # 3. Particulates (PM2.5/PM10): accumulate slightly under static conditions (+2% per hour)
            # but fluctuates with small random dispersion
            current_pm25 = max(1.0, current_pm25 * 1.02 + np.random.normal(0, 1.5))
            current_pm10 = max(current_pm25 + 1.0, current_pm10 * 1.02 + np.random.normal(0, 2.0))
            
            # 4. Gaseous emissions (NO2, CO): Traffic rush simulation peaks
            # Alternate accumulation
            current_no2 = max(1.0, current_no2 * 1.01 + np.random.normal(0, 0.5))
            current_co = max(0.1, current_co * 1.01 + np.random.normal(0, 0.02))
            
            step_inputs = {
                "temperature": round(current_temp, 1),
                "humidity": int(current_humidity),
                "PM2.5": round(current_pm25, 1),
                "PM10": round(current_pm10, 1),
                "NO2": round(current_no2, 1),
                "SO2": round(current_so2, 1),
                "CO": round(current_co, 2)
            }
            
            pred_result = self.predict(step_inputs)
            
            forecast.append({
                "hour_step": hour,
                "predicted_aqi": pred_result["predicted_aqi"],
                "category": pred_result["category"],
                "dominant_pollutant": pred_result["dominant_pollutant"],
                "simulated_inputs": step_inputs
            })
            
        return forecast

if __name__ == "__main__":
    # Test script directly
    try:
        engine = AQIPredictionEngine()
        
        # Test Case 1: Healthy Day Inputs
        healthy_inputs = {
            "temperature": 22.5,
            "humidity": 45,
            "PM2.5": 8.5,
            "PM10": 14.0,
            "NO2": 4.2,
            "SO2": 1.5,
            "CO": 0.25
        }
        
        # Test Case 2: Smoggy Day Inputs (Outlier Condition)
        smoggy_inputs = {
            "temperature": 32.0,
            "humidity": 75,
            "PM2.5": 142.5,
            "PM10": 195.0,
            "NO2": 48.0,
            "SO2": 12.5,
            "CO": 2.4
        }
        
        print("\n" + "="*50)
        print("RUNNING INFERENCE TEST CASES")
        print("="*50)
        
        print("\n--- TEST CASE 1: HEALTHY DAY ---")
        res1 = engine.predict(healthy_inputs)
        print(f"Predicted AQI: {res1['predicted_aqi']} ({res1['category']})")
        print(f"Confidence: {res1['confidence_score_pct']}%")
        print(f"Dominant Driver: {res1['dominant_pollutant']}")
        print(f"Top 3 Feature Contributions:")
        for idx in range(3):
            item = res1['feature_contributions'][idx]
            print(f"  - {item['feature']}: {item['relative_contribution_pct']}% (Value: {item['raw_value']})")
            
        print("\n--- TEST CASE 2: SMOGGY DAY (OUTLIER CONDITION) ---")
        res2 = engine.predict(smoggy_inputs)
        print(f"Predicted AQI: {res2['predicted_aqi']} ({res2['category']})")
        print(f"Confidence: {res2['confidence_score_pct']}%")
        print(f"Dominant Driver: {res2['dominant_pollutant']}")
        print(f"Top 3 Feature Contributions:")
        for idx in range(3):
            item = res2['feature_contributions'][idx]
            print(f"  - {item['feature']}: {item['relative_contribution_pct']}% (Value: {item['raw_value']})")
            
        print("\n--- TEST CASE 3: 5-HOUR预测 FORECAST SIMULATION (Starting from Smoggy Day) ---")
        forecast = engine.simulate_future_forecast(smoggy_inputs, hours_ahead=5)
        for step in forecast:
            print(f"  Hour +{step['hour_step']}: Predicted AQI = {step['predicted_aqi']} ({step['category']}) | Dominant: {step['dominant_pollutant']}")
            
        print("\nPrediction tests executed successfully.")
        
    except Exception as e:
        print(f"\nError running prediction engine test: {e}")
        print("Tip: Make sure to train the models first by running train.py.")
