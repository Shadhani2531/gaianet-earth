"""
GaiaNet Earth - AQI Prediction ML Pipeline
File: backend/ml/src/eda.py
Purpose: Performs Exploratory Data Analysis (EDA) on environmental datasets
         and generates visual analytics for the frontend and dashboard.
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

def run_eda(
    raw_data_path="backend/ml/data/raw/synthetic_air_quality.csv",
    vis_dir="backend/ml/visualizations"
):
    """
    Loads raw environmental dataset, prints statistical summaries,
    and generates/saves visual analysis plots.
    """
    print(f"Starting Exploratory Data Analysis on '{raw_data_path}'...")
    if not os.path.exists(raw_data_path):
        raise FileNotFoundError(f"Raw dataset not found at {raw_data_path}. Please run data_generator first.")
        
    df = pd.read_csv(raw_data_path)
    
    # Ensure visualizations directory exists
    os.makedirs(vis_dir, exist_ok=True)
    
    # 1. Print Basic Statistical Summary
    print("\n--- DATASET SUMMARY INFO ---")
    print(df.info())
    print("\n--- DESCRIPTIVE STATISTICS ---")
    print(df.describe())
    
    # Set premium plotting theme
    sns.set_theme(style="whitegrid")
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.size': 11,
        'axes.labelsize': 12,
        'axes.titlesize': 14,
        'xtick.labelsize': 10,
        'ytick.labelsize': 10,
        'figure.titlesize': 16
    })
    
    # 2. Correlation Matrix Heatmap
    print("\nGenerating Correlation Matrix Heatmap...")
    plt.figure(figsize=(10, 8))
    # Select numeric columns (exclude timestamp)
    numeric_df = df.select_dtypes(include=[np.number])
    corr_matrix = numeric_df.corr()
    
    # Plot using a clean warm-cool colormap
    sns.heatmap(
        corr_matrix, 
        annot=True, 
        cmap="coolwarm", 
        fmt=".2f", 
        linewidths=0.5, 
        cbar_kws={'label': 'Correlation Coefficient'}
    )
    plt.title("GaiaNet Earth - Environmental Feature Correlation Matrix", pad=20)
    plt.tight_layout()
    corr_path = os.path.join(vis_dir, "correlation_matrix.png")
    plt.savefig(corr_path, dpi=150)
    plt.close()
    print(f"Saved correlation heatmap to '{corr_path}'")
    
    # 3. Feature Distributions (Subplots)
    print("Generating Feature Distributions...")
    fig, axes = plt.subplots(3, 3, figsize=(15, 12))
    axes = axes.flatten()
    
    features = ['temperature', 'humidity', 'PM2.5', 'PM10', 'NO2', 'SO2', 'CO', 'AQI']
    colors = ['#ff7675', '#74b9ff', '#a29bfe', '#ffeaa7', '#55efc4', '#fab1a0', '#fd79a8', '#00cec9']
    
    for i, col in enumerate(features):
        if col in df.columns:
            # Clean temporary NaN values for visual plotting
            temp_series = df[col].dropna()
            sns.histplot(
                temp_series, 
                kde=True, 
                ax=axes[i], 
                color=colors[i % len(colors)],
                edgecolor="white",
                alpha=0.7
            )
            axes[i].set_title(f"{col} Distribution")
            axes[i].set_xlabel("")
            axes[i].set_ylabel("Count")
            
    # Hide the 9th empty plot
    axes[8].axis('off')
    
    plt.suptitle("GaiaNet Earth - Distribution of Environmental Variables", y=0.98)
    plt.tight_layout()
    dist_path = os.path.join(vis_dir, "feature_distributions.png")
    plt.savefig(dist_path, dpi=150)
    plt.close()
    print(f"Saved feature distributions to '{dist_path}'")
    
    # 4. Outlier Analysis Boxplots
    print("Generating Outlier Analysis Boxplots...")
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    axes = axes.flatten()
    
    pollutants = ['PM2.5', 'PM10', 'NO2', 'SO2', 'CO', 'AQI']
    box_colors = ['#e17055', '#fdcb6e', '#6c5ce7', '#00b894', '#ffeaa7', '#d63031']
    
    for i, col in enumerate(pollutants):
        if col in df.columns:
            sns.boxplot(
                y=df[col], 
                ax=axes[i], 
                color=box_colors[i],
                width=0.4,
                flierprops={"marker": "x", "markerfacecolor": "red", "markersize": 6}
            )
            axes[i].set_title(f"{col} Range & Outliers")
            axes[i].set_ylabel("Concentration / Value")
            
    plt.suptitle("GaiaNet Earth - Environmental Pollutant Outlier Analysis", y=0.98)
    plt.tight_layout()
    outlier_path = os.path.join(vis_dir, "outlier_boxplots.png")
    plt.savefig(outlier_path, dpi=150)
    plt.close()
    print(f"Saved outlier boxplots to '{outlier_path}'")
    
    # 5. AQI Trends (Diurnal & Weekly profile)
    print("Generating Diurnal AQI Trend Profile...")
    plt.figure(figsize=(12, 6))
    
    # Convert timestamp to datetime for time extraction
    df['dt'] = pd.to_datetime(df['timestamp'])
    
    # Plot the first 7 days of raw data to see diurnal waves clearly
    first_week_df = df.head(24 * 7)
    plt.plot(first_week_df['dt'], first_week_df['AQI'], color='#2d3436', linewidth=2, label="AQI")
    
    # Fill color ranges based on EPA categories
    # Good (0-50: Green), Moderate (51-100: Yellow), Unhealthy (101-150+: Orange/Red)
    xlims = plt.gca().get_xlim()
    plt.axhspan(0, 50, color='#55efc4', alpha=0.2, label="Good (0-50)")
    plt.axhspan(50, 100, color='#ffeaa7', alpha=0.2, label="Moderate (51-100)")
    plt.axhspan(100, 150, color='#fab1a0', alpha=0.2, label="Sensitive Groups (101-150)")
    plt.axhspan(150, df['AQI'].max() + 20, color='#ff7675', alpha=0.2, label="Unhealthy (>150)")
    
    plt.title("GaiaNet Earth - Simulated 7-Day Diurnal AQI Fluctuation Timeline", pad=15)
    plt.xlabel("Date & Time")
    plt.ylabel("Air Quality Index (AQI)")
    plt.legend(loc="upper right", frameon=True)
    plt.xticks(rotation=15)
    plt.tight_layout()
    
    trend_path = os.path.join(vis_dir, "aqi_diurnal_trends.png")
    plt.savefig(trend_path, dpi=150)
    plt.close()
    print(f"Saved diurnal AQI trend plot to '{trend_path}'")
    
    # Clean up column we added
    df.drop(columns=['dt'], inplace=True, errors='ignore')
    
    print("Exploratory Data Analysis completed successfully.\n")

if __name__ == "__main__":
    run_eda()
