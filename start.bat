@echo off
title PolyMarket Bot Launcher
echo Starting PolyMarket Bot...
echo.

:: Start API server in a new window
start "PolyBot API (port 8010)" cmd /k "cd /d C:\Users\darwi\OneDrive\Desktop\Claude Code\PolyMarket_Bot && python -m uvicorn api.main:app --reload --port 8010"

:: Wait 3 seconds for API to start
timeout /t 3 /nobreak >nul

:: Start frontend in a new window
start "PolyBot Frontend (port 3010)" cmd /k "cd /d C:\Users\darwi\OneDrive\Desktop\Claude Code\PolyMarket_Bot\web && npm run dev"

:: Wait 5 seconds then open browser
timeout /t 5 /nobreak >nul
start http://localhost:3010/dashboard

echo.
echo Both servers started. Browser opening...
echo Close the two terminal windows to stop the servers.
