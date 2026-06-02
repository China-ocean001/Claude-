@echo off
title Claude Code Traffic Light - Clean

cd /d "%~dp0"

echo ==============================================
echo   Claude Code Traffic Light - Clean Config
echo ==============================================
echo.
echo This will:
echo   1. Remove traffic light hooks from settings.json
echo   2. Restore backup of settings.json (if exists)
echo   3. Clean state files
echo.

python traffic_light_windows.py --clean

echo.
echo Done!
pause
