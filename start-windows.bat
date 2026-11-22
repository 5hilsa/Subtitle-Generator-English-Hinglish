@echo off
rem Double-click to start on Windows. First run sets everything up (a few minutes).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Setting up for the first time...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 (
    echo Python 3.9+ is required: https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
    pause
    exit /b 1
  )
)
.venv\Scripts\python -m pip install -q --upgrade pip
.venv\Scripts\python -m pip install -q -r requirements.txt
if errorlevel 1 ( echo Install failed. & pause & exit /b 1 )
nvidia-smi >nul 2>&1 && .venv\Scripts\python -m pip install -q -r requirements-nvidia.txt
.venv\Scripts\python app.py
pause
