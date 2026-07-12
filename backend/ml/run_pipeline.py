"""
GaiaNet Earth - AQI Prediction ML Pipeline
File: backend/ml/run_pipeline.py
Purpose: Orchestrator script to run the entire Machine Learning pipeline end-to-end:
         1. Data Generation -> 2. Data Prep & Scaling -> 3. EDA Visuals -> 4. Model Training -> 5. Verification Test
"""

import os
import sys

# Dynamic path resolution: Ensure the backend/ml directory and backend/ml/src are in pythonpath
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, "src")
project_root = os.path.dirname(os.path.dirname(current_dir))

for path in [current_dir, src_dir, project_root]:
    if path not in sys.path:
        sys.path.append(path)

# Import our modular pipeline scripts
try:
    from src.data_generator import generate_synthetic_data
    from src.data_prep import load_and_preprocess_data
    from src.eda import run_eda
    from src.train import train_and_evaluate
    from src.predict import AQIPredictionEngine
except ImportError as e:
    # Fallback if imported from parent directories with other structures
    print(f"Initial import failed ({e}). Attempting relative path import fallback...")
    sys.path.append(os.path.join(os.getcwd(), 'backend', 'ml'))
    sys.path.append(os.path.join(os.getcwd(), 'backend', 'ml', 'src'))
    from src.data_generator import generate_synthetic_data
    from src.data_prep import load_and_preprocess_data
    from src.eda import run_eda
    from src.train import train_and_evaluate
    from src.predict import AQIPredictionEngine

def main():
    print("=" * 60)
    print("GAIANET EARTH - AQI PREDICTION PIPELINE RUNNER")
    print("=" * 60)
    
    # Define absolute or relative base paths depending on working directory
    # If we are in backend/ml, raw paths are in data/raw. If in root, they are in backend/ml/data/raw.
    # To be safe, we resolve relative to this script's directory.
    base_dir = os.path.dirname(os.path.abspath(__file__))
    raw_data_path = os.path.join(base_dir, "data", "raw", "synthetic_air_quality.csv")
    processed_dir = os.path.join(base_dir, "data", "processed")
    scaler_save_path = os.path.join(base_dir, "models", "scaler.joblib")
    models_dir = os.path.join(base_dir, "models")
    vis_dir = os.path.join(base_dir, "visualizations")
    
    # Step 1: Generate Dataset
    print("\n[STAGE 1/5] GENERATING SYNTHETIC ENVIRONMENTAL DATASET")
    print("-" * 50)
    generate_synthetic_data(output_path=raw_data_path, num_days=60, seed=42)
    
    # Step 2: Preprocess, Impute, Scale, and Split Data
    print("\n[STAGE 2/5] PREPROCESSING, CLEANING, AND SPLITTING DATA")
    print("-" * 50)
    load_and_preprocess_data(
        raw_data_path=raw_data_path,
        processed_dir=processed_dir,
        scaler_save_path=scaler_save_path,
        test_size=0.2,
        random_state=42
    )
    
    # Step 3: Run EDA and generate plots
    print("\n[STAGE 3/5] RUNNING EXPLORATORY DATA ANALYSIS (EDA)")
    print("-" * 50)
    run_eda(
        raw_data_path=raw_data_path,
        vis_dir=vis_dir
    )
    
    # Step 4: Train models and select best performer
    print("\n[STAGE 4/5] TRAINING REGRESSORS & SERIALIZING BEST MODEL")
    print("-" * 50)
    train_and_evaluate(
        processed_dir=processed_dir,
        models_dir=models_dir,
        vis_dir=vis_dir,
        random_state=42
    )
    
    # Step 5: Verification & Prediction Test
    print("\n[STAGE 5/5] VERIFYING MODEL WITH INFERENCE ENGINE")
    print("-" * 50)
    
    try:
        engine = AQIPredictionEngine(models_dir=models_dir)
        
        # Mock user input parameters
        test_input = {
            "temperature": 28.5,
            "humidity": 55,
            "PM2.5": 42.0,
            "PM10": 68.0,
            "NO2": 24.5,
            "SO2": 3.8,
            "CO": 0.85
        }
        
        print(f"Input Parameters: {test_input}")
        result = engine.predict(test_input)
        
        print("\nPrediction Results:")
        print(f"  - Predicted AQI: {result['predicted_aqi']}")
        print(f"  - Health Category: {result['category']} ({result['color']})")
        print(f"  - Model Confidence Score: {result['confidence_score_pct']}%")
        print(f"  - Dominant Contributor: {result['dominant_pollutant']}")
        print(f"  - Dominant Factor Percentage: {result['feature_contributions'][0]['relative_contribution_pct']}%")
        
        # Test forecast simulation
        print("\nStarting simulated 3-hour forecasting sequence...")
        forecast = engine.simulate_future_forecast(test_input, hours_ahead=3)
        for step in forecast:
            print(f"    Hour +{step['hour_step']}: AQI = {step['predicted_aqi']} ({step['category']})")
            
        print("\n" + "=" * 60)
        print("PIPELINE COMPLETED SUCCESSFULLY! ALL SHIPPED ASSETS VERIFIED.")
        print("=" * 60)
        
    except Exception as e:
        print(f"Pipeline verification test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
