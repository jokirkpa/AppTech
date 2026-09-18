@echo off
REM AppTech Local Builder launcher (Windows)
cd /d "%~dp0"
echo Starting AppTech Local Builder on http://localhost:5050
start "" python server.py
timeout /t 2 /nobreak >nul
start "" http://localhost:5050
