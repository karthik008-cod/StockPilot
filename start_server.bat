@echo off
title StockPilot - NIFTY 50 Market Explorer
echo ================================================================
echo               StockPilot NIFTY 50 Market Explorer               
echo ================================================================
echo.

:: Change working directory to script directory
cd /d "%~dp0"

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in your system PATH.
    echo Please install Python 3.10+ and add it to your PATH.
    echo.
    pause
    exit /b 1
)

echo [*] Starting web server on http://127.0.0.1:8000 ...
echo [*] Opening browser in 2 seconds...
echo.

:: Launch browser in background after 2 seconds to allow server startup
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"

:: Start Uvicorn server in foreground
python -m uvicorn web.app:app --host 127.0.0.1 --port 8000 --reload

echo.
echo Server stopped.
pause
