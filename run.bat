@echo off
echo ========================================
echo   SPOTDOWN - Neon Edition
echo ========================================

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.11+
    pause
    exit /b 1
)

ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] FFmpeg not found. Install FFmpeg and add to PATH
    pause
    exit /b 1
)

echo [1/4] Checking for existing server on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo     Killing PID %%a ...
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo [2/4] Installing Python dependencies...
pip install -r requirements.txt -q --index-url https://pypi.org/simple/

if not exist .env (
    echo [WARNING] .env not found. Copying from .env.example...
    copy .env.example .env
    echo Please edit .env with your Spotify credentials.
)

if not exist downloads mkdir downloads
if not exist logs mkdir logs

echo [3/4] Starting Uvicorn server...
echo [4/4] Server running at http://localhost:8000
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
