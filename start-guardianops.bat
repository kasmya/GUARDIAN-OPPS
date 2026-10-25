@echo off
REM ============================================================
REM  GuardianOps — one-click local launcher (no Docker required)
REM  Starts fraud-api, guardian, chaos-injector, and the frontend
REM  static server, each in its own window, then opens the
REM  dashboard in your default browser.
REM ============================================================

setlocal
cd /d "%~dp0"

echo ============================================================
echo   GuardianOps — starting all services
echo ============================================================
echo.

REM --- 0. Sanity check: python must be on PATH -----------------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python was not found on PATH. Install Python 3.11+
    echo         and make sure "python" runs from a terminal first.
    pause
    exit /b 1
)

REM --- 1. Install dependencies (safe to re-run; pip skips what's
REM        already satisfied) -----------------------------------
echo [1/6] Installing fraud-api dependencies...
pip install -q -r services\fraud-api\requirements.txt

echo [2/6] Installing guardian dependencies...
pip install -q -r services\guardian\requirements.txt

echo [3/6] Installing chaos-injector dependencies...
pip install -q -r services\chaos-injector\requirements.txt

REM --- 2. Reset shared state so a previous crash/corrupt flag
REM        can't poison this run's baseline capture -------------
echo [4/6] Resetting shared state to normal...
> shared\state.json echo {"mode": "normal", "slow_ms": 0, "corrupt": false}

REM --- 3. Launch each service in its own window -----------------
echo [5/6] Launching services in separate windows...

set STATE_FILE=%cd%\shared\state.json
start "GuardianOps: fraud-api (8001)" cmd /k "set STATE_FILE=%STATE_FILE% && python -m uvicorn app.main:app --app-dir services\fraud-api --port 8001 --host 127.0.0.1"

set FRAUD_API_URL=http://127.0.0.1:8001
set DATA_DIR=%cd%\data\guardian
set REPORTS_DIR=%cd%\data\reports
set MLFLOW_TRACKING_URI=file:///%cd:\=/%/data/mlflow
start "GuardianOps: guardian (8002)" cmd /k "set FRAUD_API_URL=%FRAUD_API_URL% && set DATA_DIR=%DATA_DIR% && set REPORTS_DIR=%REPORTS_DIR% && set MLFLOW_TRACKING_URI=%MLFLOW_TRACKING_URI% && python -m uvicorn app.main:app --app-dir services\guardian --port 8002 --host 127.0.0.1"

start "GuardianOps: chaos-injector (8003)" cmd /k "set FRAUD_API_URL=%FRAUD_API_URL% && python -m uvicorn app.main:app --app-dir services\chaos-injector --port 8003 --host 127.0.0.1"

start "GuardianOps: frontend (8080)" cmd /k "python -m http.server 8080 --directory frontend --bind 127.0.0.1"

REM --- 4. Wait for Guardian to warm up (baseline capture takes
REM        roughly 30-60s) then open the browser -----------------
echo [6/6] Waiting ~15s for services to come up, then opening the dashboard...
timeout /t 15 /nobreak >nul
start "" "http://127.0.0.1:8080"

echo.
echo ============================================================
echo   All 4 services are starting in their own windows:
echo     fraud-api        http://127.0.0.1:8001/docs
echo     guardian         http://127.0.0.1:8002/docs
echo     chaos-injector   http://127.0.0.1:8003/docs
echo     dashboard        http://127.0.0.1:8080
echo.
echo   Guardian needs ~30-60s on first boot to capture its
echo   200-sample baseline. Until then the confidence gauge
echo   sits at 100 with no drift data.
echo.
echo   To stop everything: close the 4 new terminal windows,
echo   or run stop-guardianops.bat
echo ============================================================
pause
