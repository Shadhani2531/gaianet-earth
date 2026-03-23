@echo off
SETLOCAL EnableDelayedExpansion

echo ==========================================
echo    GaiaNet Earth - NASA Digital Twin
echo          Initializing Project...
echo ==========================================

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed. Please install Python to continue.
    pause
    exit /b
)

:: 1. Setup Backend & Frontend
echo [1/2] Setting up Unified Server...
cd backend
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate
echo Installing dependencies...
pip install -r requirements.txt >nul
start "GaiaNet Unified Server" cmd /k "venv\Scripts\activate && python main.py"
cd ..

:: 2. Launch Browser
echo [2/2] Launching Dashboard...
timeout /t 5 /nobreak >nul
start http://localhost:8000

echo ==========================================
echo    GaiaNet Earth is running!
echo    - Global Dashboard: http://localhost:8000
echo    - API Docs: http://localhost:8000/docs
echo ==========================================
pause
