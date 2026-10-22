@echo off
REM Run the CA Copilot automated test suite.
cd /d %~dp0
if not exist .venv (
    echo Run run_windows.bat once first to create the environment.
    pause
    exit /b 1
)
call .venv\Scripts\activate
pytest tests/ -q
pause
