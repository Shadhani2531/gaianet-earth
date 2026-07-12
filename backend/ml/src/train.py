"""
GaiaNet Earth - AQI Prediction ML Pipeline
File: backend/ml/src/train.py
Purpose: Trains multiple regressor models, evaluates and compares their accuracy,
         selects the best model, extracts feature importances, and serializes the assets.
"""

import os
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import joblib

from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import xgboost as xgb

def train_and_evaluate(
    processed_dir="backend/ml/data/processed",
    models_dir="backend/ml/models",
    vis_dir="backend/ml/visualizations",
    random_state=42
):
    """
    Trains multiple models, evaluates performance, dumps best model, and creates metrics plots.
    """
    print("Initializing model training pipeline...")
    
    train_path = os.path.join(processed_dir, "train_data.csv")
    test_path = os.path.join(processed_dir, "test_data.csv")
    
    if not os.path.exists(train_path) or not os.path.exists(test_path):
        raise FileNotFoundError("Processed datasets not found. Please run data_prep first.")
        
    train_df = pd.read_csv(train_path)
    test_df = pd.read_csv(test_path)
    
    # Separate features and target
    X_train = train_df.drop(columns=['AQI'])
    y_train = train_df['AQI']
    X_test = test_df.drop(columns=['AQI'])
    y_test = test_df['AQI']
    
    feature_names = list(X_train.columns)
    
    # 1. Define models to train
    models = {
        "Linear Regression": LinearRegression(),
        "Random Forest": RandomForestRegressor(n_estimators=100, random_state=random_state, n_jobs=-1),
        "XGBoost": xgb.XGBRegressor(n_estimators=100, random_state=random_state, n_jobs=-1, learning_rate=0.1, max_depth=5)
    }
    
    metrics_summary = {}
    trained_models = {}
    
    print("\n--- Training Models ---")
    for name, model in models.items():
        print(f"Training {name} Regressor...")
        model.fit(X_train, y_train)
        trained_models[name] = model
        
        # Predict on test set
        y_pred = model.predict(X_test)
        
        # Calculate metrics
        mae = mean_absolute_error(y_test, y_pred)
        mse = mean_squared_error(y_test, y_pred)
        rmse = np.sqrt(mse)
        r2 = r2_score(y_test, y_pred)
        
        metrics_summary[name] = {
            "MAE": round(float(mae), 4),
            "RMSE": round(float(rmse), 4),
            "R2": round(float(r2), 4)
        }
        
        print(f"  - {name} Results: MAE = {mae:.2f} | RMSE = {rmse:.2f} | R2 = {r2:.4f}")
        
    # Save comparison metrics to JSON
    os.makedirs(models_dir, exist_ok=True)
    metrics_path = os.path.join(models_dir, "model_comparison.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics_summary, f, indent=4)
    print(f"\nSaved model comparison metrics to '{metrics_path}'")
    
    # 2. Select Best Model
    # We select the best model based on the highest R² Score (Coefficient of Determination)
    best_model_name = max(metrics_summary, key=lambda k: metrics_summary[k]["R2"])
    best_model = trained_models[best_model_name]
    best_r2 = metrics_summary[best_model_name]["R2"]
    
    print(f"\n=======================================================")
    print(f"BEST PERFORMING MODEL: {best_model_name} (R2 = {best_r2:.4f})")
    print(f"=======================================================")
    
    # Save the best model
    model_save_path = os.path.join(models_dir, "best_model.joblib")
    joblib.dump(best_model, model_save_path)
    print(f"Successfully saved {best_model_name} as '{model_save_path}'")
    
    # Save metadata about the best model configuration
    metadata = {
        "model_name": best_model_name,
        "features": feature_names,
        "metrics": metrics_summary[best_model_name]
    }
    metadata_path = os.path.join(models_dir, "model_metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=4)
        
    # Set premium style for visualizations
    sns.set_theme(style="whitegrid")
    os.makedirs(vis_dir, exist_ok=True)
    
    # 3. Visualization: Model Comparison Chart
    print("\nGenerating Model Comparison Visualization...")
    comparison_df = pd.DataFrame(metrics_summary).T.reset_index().rename(columns={'index': 'Model'})
    
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    metrics_list = ["MAE", "RMSE", "R2"]
    colors = ["#74b9ff", "#ff7675", "#55efc4"]
    
    for idx, metric in enumerate(metrics_list):
        sns.barplot(
            x="Model", 
            y=metric, 
            data=comparison_df, 
            ax=axes[idx], 
            palette=colors,
            hue="Model",
            legend=False
        )
        axes[idx].set_title(f"Comparison: {metric}")
        axes[idx].set_xlabel("")
        axes[idx].set_ylabel(metric)
        # Add labels on top of bars
        for container in axes[idx].containers:
            axes[idx].bar_label(container, fmt='%.3f', padding=3)
            
    plt.suptitle("GaiaNet Earth - Model Performance Comparison", y=1.02)
    plt.tight_layout()
    comparison_plot_path = os.path.join(vis_dir, "model_comparison.png")
    plt.savefig(comparison_plot_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved model comparison plot to '{comparison_plot_path}'")
    
    # 4. Visualization: Actual vs Predicted AQI Scatter Plot (for best model)
    print("Generating Actual vs Predicted AQI Scatter Plot...")
    y_pred_best = best_model.predict(X_test)
    
    plt.figure(figsize=(8, 8))
    sns.scatterplot(x=y_test, y=y_pred_best, alpha=0.6, color="#0984e3", edgecolor="white", s=40)
    
    # Add ideal 45-degree reference line
    min_val = min(y_test.min(), y_pred_best.min())
    max_val = max(y_test.max(), y_pred_best.max())
    plt.plot([min_val, max_val], [min_val, max_val], color='#d63031', linestyle='--', linewidth=2, label="Perfect Predictor")
    
    plt.title(f"Actual vs. Predicted AQI ({best_model_name})", pad=15)
    plt.xlabel("Actual AQI Values (Sensor Data)")
    plt.ylabel("Predicted AQI Values (Model Predictions)")
    plt.legend(loc="upper left")
    plt.grid(True, linestyle=':', alpha=0.6)
    plt.tight_layout()
    
    scatter_plot_path = os.path.join(vis_dir, "actual_vs_predicted.png")
    plt.savefig(scatter_plot_path, dpi=150)
    plt.close()
    print(f"Saved scatter plot to '{scatter_plot_path}'")
    
    # 5. Visualization: Feature Importance Ranking (for best model)
    print("Extracting Feature Importance...")
    importances = []
    
    if hasattr(best_model, "feature_importances_"):
        importances = best_model.feature_importances_
        imp_title = f"Feature Importance Ranking ({best_model_name})"
    elif hasattr(best_model, "coef_"):
        # For Linear Regression, use the absolute value of coefficients
        importances = np.abs(best_model.coef_)
        imp_title = f"Absolute Coefficient Magnitude ({best_model_name})"
    else:
        # Fallback if no importances available
        importances = np.ones(len(feature_names)) / len(feature_names)
        imp_title = "Feature Contribution (Equal Weights)"
        
    importance_df = pd.DataFrame({
        "Feature": feature_names,
        "Importance": importances
    }).sort_values(by="Importance", ascending=False)
    
    # Save importance list to metadata
    metadata["feature_importance_ranking"] = importance_df.to_dict(orient="records")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=4)
        
    plt.figure(figsize=(10, 6))
    sns.barplot(
        x="Importance", 
        y="Feature", 
        data=importance_df, 
        palette="viridis",
        hue="Feature",
        legend=False
    )
    plt.title(imp_title, pad=15)
    plt.xlabel("Importance / Coefficient Magnitude")
    plt.ylabel("Environmental Indicator")
    plt.tight_layout()
    
    importance_plot_path = os.path.join(vis_dir, "feature_importance.png")
    plt.savefig(importance_plot_path, dpi=150)
    plt.close()
    print(f"Saved feature importance plot to '{importance_plot_path}'")
    print("Model training and selection completed successfully.\n")
    
    return best_model, metrics_summary

if __name__ == "__main__":
    train_and_evaluate()
