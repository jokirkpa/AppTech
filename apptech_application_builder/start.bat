@echo off
cd /d "%~dp0"
echo Starting AppTech Application Builder on http://localhost:8765
start python server.py
timeout /t 2 /nobreak >nul
start http://localhost:8765
