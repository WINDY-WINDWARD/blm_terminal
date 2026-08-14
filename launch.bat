@echo off
echo Starting BLM Terminal (Production Mode)...
cd /d "%~dp0"

:: Start Backend in a new separate window
echo Launching Backend in a new window...
start "BLM Backend" cmd /k "cd backend && (if not exist .venv python -m venv .venv) && call .venv\Scripts\activate.bat && pip install -e . && python scripts\ag_login.py && uvicorn main:app --port 4455"

:: Start Frontend in the current window
echo Setting up and starting Frontend...
call npm install
call npm run build
call npm start
