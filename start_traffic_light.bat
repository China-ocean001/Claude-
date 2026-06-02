@echo off
title Claude Code Traffic Light

echo ==============================================
echo   Claude Code Traffic Light - Windows
echo ==============================================
echo.

cd /d "%~dp0"

echo [1/2] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3.9+
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version

echo.
echo [2/2] Checking dependencies...
pip install -r requirements_windows.txt -q
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo Dependencies OK!

echo.
echo Starting traffic light monitor...
echo Right-click the tray icon for menu / Quit
echo.

python traffic_light_windows.py

pause
