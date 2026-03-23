# GaiaNet Earth - Run Instructions

To properly view and interact with the **NASA-Level Immersive Digital Twin (5-Screen Flow)**, you need to run both the backend API and the frontend dashboard. 

## Quick Start (Recommended)
Double-click the `start_project.bat` file in the root directory. This will automatically:
1. Install backend dependencies.
2. Start the FastAPI backend on `http://localhost:8000`.
3. Start a local web server for the frontend.
4. Open the dashboard in your default browser.

---

## Manual Steps

### 1. Start the Backend
Open a terminal in the project root and run:
```powershell
cd backend
# Create virtual environment if it doesn't exist
python -m venv venv
# Activate virtual environment
.\venv\Scripts\activate
# Install dependencies
pip install -r requirements.txt
# Start the server
python main.py
```

### 2. Start the Frontend
Open another terminal in the project root and run:
```powershell
# Use any local web server. Python's built-in is easiest:
python -m http.server 8080
```
Then open [http://localhost:8080](http://localhost:8080) in your browser.

---

## Accessing the 5 Screens

1.  **🌍 Screen 1: Immersive Earth**: Visible by default upon loading (Cesium Globe).
2.  **📍 Screen 2: Location Insight**: Click any point on the globe or wait for the initial "India" analytics to load automatically after 2 seconds. A card will slide in from the right.
3.  **⏳ Screen 3: Time Slider**: Located at the bottom. Use the play button or slider to see temporal shifts.
4.  **🧠 Screen 4: Prediction Panel**: The right sidebar shows real-time analytics and predicted trends.
5.  **🚀 Screen 5: What-if Simulation**: Click the **Flask Icon (What-If Scenarios)** in the top navigation bar to open the simulation panel.
