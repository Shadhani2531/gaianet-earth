# GaiaNet Earth - Air Quality Index (AQI) Prediction Pipeline

This sub-project implements a modular, production-grade Machine Learning pipeline for predicting the Air Quality Index (AQI) from environmental and meteorological variables. It is designed to act as the predictive backend core for the **GaiaNet Earth - Digital Twin of the Planet** web application.

---

## 📂 Folder Structure
The ML subsystem is completely self-contained within `backend/ml/`:
```text
backend/ml/
├── requirements.txt         # ML packages (pandas, numpy, scikit-learn, xgboost, matplotlib, seaborn, joblib)
├── README.md                # This documentation file
├── run_pipeline.py          # Master orchestrator script to run the entire pipeline end-to-end
├── data/                    # Local storage for datasets (automatically created)
│   ├── raw/                 # Raw dataset (synthetic_air_quality.csv)
│   └── processed/           # Scaled, cleaned, train-test split datasets
├── models/                  # Serialized ML assets
│   ├── best_model.joblib    # Serialized best regressor (XGBoost / RandomForest)
│   ├── scaler.joblib        # Fitted StandardScaler for inference pipeline consistency
│   ├── feature_medians.joblib# Feature medians used as fallback values during imputation
│   ├── model_metadata.json  # Best model details & feature importances
│   └── model_comparison.json# Evaluation metrics (MAE, RMSE, R²) for all trained models
├── visualizations/          # Generated analytical graphs and charts
│   ├── correlation_matrix.png
│   ├── feature_distributions.png
│   ├── outlier_boxplots.png
│   ├── aqi_diurnal_trends.png
│   ├── model_comparison.png
│   ├── actual_vs_predicted.png
│   └── feature_importance.png
└── src/                     # Core pipeline modules
    ├── __init__.py          # Marks src/ as a python package
    ├── data_generator.py    # Simulates hourly physical environment & EPA AQI math
    ├── data_prep.py         # Imputes missing data, splits data, fits and dumps the scaler
    ├── eda.py               # Generates statistical plots & visual summaries
    ├── train.py             # Trains models (LR, RF, XGBoost) and exports evaluation charts
    └── predict.py           # Production inference wrapper, Z-score confidence, & temporal forecast simulator
```

---

## ⚙️ Module Responsibilities & GaiaNet Integration

| File | Purpose | GaiaNet Earth Connection |
| :--- | :--- | :--- |
| **`data_generator.py`** | Simulates 60 days of hourly temperature, humidity, and pollutants (PM2.5, PM10, NO2, SO2, CO) using realistic diurnal/rush-hour patterns. Calculates AQI using US EPA standard. | Replaces missing actual sensor grids with physically-bounded simulated readings for platform tests. |
| **`data_prep.py`** | Handles cleaning, median imputation for robustness, splitting, and scaling via `StandardScaler`. | Clean and scale incoming API data before passing to prediction engine. |
| **`eda.py`** | Creates analytical plots (correlations, distributions, outliers, 7-day diurnal trend timelines). | Feeds into the GaiaNet Analytics Dashboard, showing users environmental trends. |
| **`train.py`** | Fits Linear Regression, Random Forest, and XGBoost; computes MAE, RMSE, and $R^2$; dumps best model. | Backend training loop that updates the brain of the digital twin periodically. |
| **`predict.py`** | Main inference wrapper. Loads model & scaler. Offers **dynamic confidence score** and **5-hour temporal predictions**. | Backend core that answers `/api/predict-aqi` REST requests from the CesiumJS globe. |
| **`run_pipeline.py`**| Execution orchestrator. Runs stage 1-5 sequentially. | Script run via Cron job or developer tools to retrain/refresh model assets. |

---

## 🚀 Execution Instructions

Follow these step-by-step instructions to install requirements, run the pipeline, and verify the output.

### Step 1: Install Dependencies
Open your terminal (PowerShell, Command Prompt, or bash), navigate to the project directory, and activate your backend virtual environment.

On Windows PowerShell:
```powershell
# 1. Navigate to the backend directory
cd backend

# 2. Activate the virtual environment
.\venv\Scripts\Activate.ps1

# 3. Install ML dependencies
pip install -r ml/requirements.txt
```

*(If you are running the pipeline from the project root or without virtualenv, run `pip install -r backend/ml/requirements.txt`).*

### Step 2: Run the End-to-End Pipeline
Run the master orchestrator script. This generates data, prepares it, plots EDA figures, trains the model, compares them, serializes the best model, and runs verification checks.
```powershell
python ml/run_pipeline.py
```

### Step 3: Verify the Saved Artifacts
After the script finishes with a `🎉 PIPELINE COMPLETED SUCCESSFULLY!` message, check the following directories:
1. **Data files**: Check `backend/ml/data/raw/` and `backend/ml/data/processed/`. You should see `synthetic_air_quality.csv`, `train_data.csv`, and `test_data.csv`.
2. **Visualizations**: Check `backend/ml/visualizations/`. Double-click and open the `.png` charts to verify they show clear, readable labels.
3. **Saved Models**: Check `backend/ml/models/`. You should see `best_model.joblib`, `scaler.joblib`, `model_metadata.json`, and `model_comparison.json`.

---

## 🔌 FastAPI Integration (Connecting to GaiaNet Earth)

To expose this ML prediction engine as an API route in GaiaNet's main web gateway, modify `backend/main.py` by incorporating the following snippet:

```python
# --- ADD AT START OF backend/main.py ---
from ml.src.predict import AQIPredictionEngine
from pydantic import BaseModel

# Initialize the ML Prediction Engine once at startup
try:
    ml_engine = AQIPredictionEngine(models_dir="ml/models")
    logger.info("GaiaNet ML Prediction Engine initialized successfully.")
except Exception as e:
    logger.error(f"Failed to load ML Prediction Engine: {e}. Run run_pipeline.py first.")
    ml_engine = None

# Define API request schema
class AQIPredictionRequest(BaseModel):
    temperature: float = 25.0
    humidity: int = 50
    pm25: float = 15.0
    pm10: float = 25.0
    no2: float = 12.0
    so2: float = 2.5
    co: float = 0.50

# --- ADD ROUTE TO backend/main.py ---
@app.post("/api/predict-aqi")
def predict_aqi(payload: AQIPredictionRequest):
    """
    Predicts live AQI and provides a 5-hour simulated future forecast.
    Accepts current environmental conditions, returns predictive analytics.
    """
    if ml_engine is None:
        raise HTTPException(status_code=503, detail="ML prediction engine is not initialized.")
        
    input_data = {
        "temperature": payload.temperature,
        "humidity": payload.humidity,
        "PM2.5": payload.pm25,
        "PM10": payload.pm10,
        "NO2": payload.no2,
        "SO2": payload.so2,
        "CO": payload.co
    }
    
    try:
        prediction = ml_engine.predict(input_data)
        forecast = ml_engine.simulate_future_forecast(input_data, hours_ahead=5)
        
        return {
            "status": "success",
            "current_prediction": prediction,
            "forecast_simulation": forecast
        }
    except Exception as e:
        logger.error(f"AQI Prediction Error: {e}")
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")
```

With this endpoint added, the React + CesiumJS frontend can send a POST request with the station's readings or live inputs to `/api/predict-aqi` and display live ratings, risk zones, confidence levels, and future trends directly in the client dashboard.

---

## 📈 Future Scalability Roadmap

1. **Connect Live NOAA/NASA/OpenWeather APIs**:
   - In production, instead of generating synthetic datasets, write a script under `backend/services/weather.py` that query OpenWeather (for real-time air quality pollutants and temperature/humidity) and NASA FIRMS (for fire/smog anomalies).
   - Feed this live dictionary to `AQIPredictionEngine.predict()` directly.

2. **CesiumJS 3D Prediction Globe Overlay**:
   - Query predictions for a grid of latitude/longitude coordinates across a region (e.g. an urban center or state).
   - Construct a GeoJSON feature collection of coordinate nodes with predicted AQI values.
   - Load this JSON in CesiumJS as a `GeoJsonDataSource` and use an entity color-mapping function (using the `color` field returned by the backend) to display an interactive 3D heatmap overlay of future environmental risk zones.

3. **Time-Series Forecasting**:
   - Swap the current regression algorithms with time-series forecasting models (such as Prophet, ARIMA, or LSTM/GRU networks) by storing historical inputs in SQLite (`reports.db`). This allows the system to recognize seasonal climate shifts and multi-day temporal correlation patterns.

---

## 🛠️ Troubleshooting & Common Fixes

* **Error: `ModuleNotFoundError: No module named 'xgboost'`**
  - **Fix**: You might be running python inside the wrong virtual environment, or forgot to run pip install. Make sure to run `pip install -r ml/requirements.txt` with your virtual environment activated.
  
* **Error: `FileNotFoundError: Model or Scaler not found...`**
  - **Fix**: You are calling `predict.py` or the FastAPI server without training first. Run `python ml/run_pipeline.py` or `python ml/src/train.py` to train models and write serialized joblib files.

* **Error: `ValueError: Feature shape mismatch...`**
  - **Fix**: This happens if the list of columns scaled during training does not match the list of columns passed in during prediction. Make sure that both `data_prep.py` and `predict.py` use the exact same feature list: `['temperature', 'humidity', 'PM2.5', 'PM10', 'NO2', 'SO2', 'CO']`.
