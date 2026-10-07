@echo off
REM ============================================================
REM AI Job Search - daily run wrapper for Windows Task Scheduler
REM Runs the pipeline from the project directory so .env, resume/
REM and database/ resolve correctly, then logs the output.
REM ============================================================

REM Always run from the folder this script lives in.
cd /d "%~dp0"

REM Prefer the project virtual environment if present, else system python.
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

REM Timestamped log line, then run. Output appended to logs\job_radar.log
if not exist "logs" mkdir "logs"
echo [%date% %time%] Starting AI Job Search >> "logs\job_radar.log"
"%PY%" main.py %* >> "logs\job_radar.log" 2>&1
echo [%date% %time%] Finished with exit code %ERRORLEVEL% >> "logs\job_radar.log"
