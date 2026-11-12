@echo off
rem Starts FRAMEWORK AI on Windows: backend and app in two windows, then opens the browser.
cd /d "%~dp0"
start "FRAMEWORK backend" cmd /k "cd backend && .venv\Scripts\python -m uvicorn app.main:app --reload --port 8000"
start "FRAMEWORK app" cmd /k "cd frontend && npm run dev"
timeout /t 10 /nobreak >nul
start "" http://localhost:3000
