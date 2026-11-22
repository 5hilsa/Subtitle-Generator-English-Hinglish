@echo off
rem Double-click to try the full website on this PC: test sign-in, simulated payments.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe ( echo Run start-windows.bat once first to set things up. & pause & exit /b 1 )
set DEMO_MODE=1
.venv\Scripts\python app.py
pause
