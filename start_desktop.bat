@echo off
title Claude Code Traffic Light - Desktop

cd /d "%~dp0"

echo ==============================================
echo   Claude Code Traffic Light - Desktop Overlay
echo ==============================================
echo.
echo Starting desktop floating window...
echo.
echo Usage:
echo   - Left-click and drag to move the window
echo   - Right-click for project menu / exit
echo.

python traffic_light_desktop.py

pause
