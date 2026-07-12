"""
GaiaNet Earth - AQI Prediction ML Pipeline
File: backend/ml/src/data_prep.py
Purpose: Loads, cleans, imputes, normalizes, and splits environmental dataset.
"""

import os
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import joblib

def load_and_preprocess_data(
    raw_data_path="backend/ml/data/raw/synthetic_air_quality.csv",
    processed_dir="backend/ml/data/processed",
    scaler_save_path="backend/ml/models/scaler.joblib",
    test_size=0.2,
    random_state=42
):
    """
    Loads raw CSV, cleans missing values, fits and saves feature scaler,
    splits data into train/test, and saves processed sets.
    """
    print(f"Loading raw data from '{raw_data_path}'...")
    if not os.path.exists(raw_data_path):
        raise FileNotFoundError(f"Raw dataset not found at {raw_data_path}. Please run data_generator first.")
        
    df = pd.read_csv(raw_data_path)
    
    # Keep track of columns
    feature_cols = ['temperature', 'humidity', 'PM2.5', 'PM10', 'NO2', 'SO2', 'CO']
    target_col = 'AQI'
    
    # 1. Missing Value Handling
    # Fill missing values using the median of each column. 
    # Median is robust against outliers (which are common in pollution data).
    print("Handling missing values using column medians...")
    medians = {}
    for col in feature_cols:
        col_median = df[col].median()
        medians[col] = col_median
        missing_count = df[col].isnull().sum()
        if missing_count > 0:
            df[col] = df[col].fillna(col_median)
            print(f"  - Imputed {missing_count} missing values in column '{col}' with median: {col_median}")
            
    # Save the medians of features as fallback info for API input verification
    os.makedirs(os.path.dirname(scaler_save_path), exist_ok=True)
    joblib.dump(medians, os.path.join(os.path.dirname(scaler_save_path), "feature_medians.joblib"))
    
    # 2. Split Features (X) and Target (y)
    X = df[feature_cols]
    y = df[target_col]
    
    # 3. Train-Test Split (before scaling to prevent data leakage)
    print(f"Splitting dataset into train/test (ratio: {100*(1-test_size)}%/{100*test_size}%)...")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state
    )
    
    # 4. Feature Scaling (Normalization)
    # Standardize features by removing the mean and scaling to unit variance.
    # This is critical for Linear Regression and helpful for other algorithms.
    print("Scaling features using StandardScaler...")
    scaler = StandardScaler()
    
    # Fit scaler on training data only
    X_train_scaled = scaler.fit_transform(X_train)
    # Transform test data using the fitted scaler
    X_test_scaled = scaler.transform(X_test)
    
    # Save scaler for prediction server
    joblib.dump(scaler, scaler_save_path)
    print(f"Saved fitted StandardScaler to '{scaler_save_path}'")
    
    # Convert scaled features back to DataFrames to preserve column names
    X_train_scaled_df = pd.DataFrame(X_train_scaled, columns=feature_cols, index=X_train.index)
    X_test_scaled_df = pd.DataFrame(X_test_scaled, columns=feature_cols, index=X_test.index)
    
    # Combine features and target for saving
    train_processed = pd.concat([X_train_scaled_df, y_train], axis=1)
    test_processed = pd.concat([X_test_scaled_df, y_test], axis=1)
    
    # Save processed datasets
    os.makedirs(processed_dir, exist_ok=True)
    train_path = os.path.join(processed_dir, "train_data.csv")
    test_path = os.path.join(processed_dir, "test_data.csv")
    
    train_processed.to_csv(train_path, index=False)
    test_processed.to_csv(test_path, index=False)
    
    print(f"Processed training set saved to '{train_path}' ({len(train_processed)} samples)")
    print(f"Processed test set saved to '{test_path}' ({len(test_processed)} samples)")
    
    return train_processed, test_processed, feature_cols, target_col

if __name__ == "__main__":
    load_and_preprocess_data()
