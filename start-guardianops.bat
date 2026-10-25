@echo off
REM ============================================================
REM  GuardianOps - one-click local launcher (Windows, no Docker)
REM
REM  1. creates an isolated virtual environment in .venv (first run only)
REM  2. installs the pinned dependencies of the 3 services into it
REM  3. starts fraud-api, guardian, chaos-injector and the dashboard
REM     web server, each in its own console window
REM  4. waits until all four answer, then opens the dashboard
REM
REM  Usage:   start-guardianops.bat            (normal, opens browser)
REM           start-guardianops.bat nobrowser  (no browser, no final pause)
REM ============================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "NOBROWSER=0"
if /i "%~1"=="nobrowser" set "NOBROWSER=1"

echo ============================================================
echo   GuardianOps - starting all services
echo ============================================================
echo.

REM --- 0. Python must be available ------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python was not found on PATH.
    echo         Install Python 3.11 or newer and open a NEW terminal.
    if "%NOBROWSER%"=="0" pause
    exit /b 1
)

REM --- 0b. Refuse to start if a port is already taken -------------
REM     (otherwise a stale process would answer the readiness check
REM      while the new service silently fails to bind)
set "BUSY="
for %%P in (8001 8002 8003 8080) do (
    netstat -ano | findstr /R /C:":%%P .*LISTENING" >nul && set "BUSY=!BUSY! %%P"
)
if defined BUSY (
    echo [ERROR] These ports are already in use:%BUSY%
    echo         Run stop-guardianops.bat first, or stop "docker compose" if it is running.
    if "%NOBROWSER%"=="0" pause
    exit /b 1
)

REM --- 1. Isolated virtual environment (keeps your global Python clean)
if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] could not create the virtual environment.
        if "%NOBROWSER%"=="0" pause
        exit /b 1
    )
) else (
    echo [1/5] Virtual environment already exists.
)
set "PY=%cd%\.venv\Scripts\python.exe"

REM --- 2. Dependencies (pip skips what is already installed) -----
echo [2/5] Installing dependencies (first run takes a few minutes) ...
"%PY%" -m pip install -q --disable-pip-version-check --default-timeout=120 --retries 5 -r services\fraud-api\requirements.txt
if errorlevel 1 goto :pipfail
"%PY%" -m pip install -q --disable-pip-version-check --default-timeout=120 --retries 5 -r services\guardian\requirements.txt
if errorlevel 1 goto :pipfail
"%PY%" -m pip install -q --disable-pip-version-check --default-timeout=120 --retries 5 -r services\chaos-injector\requirements.txt
if errorlevel 1 goto :pipfail

REM --- 3. Environment inherited by the service windows ----------
REM     (set "VAR=value" form: no stray trailing spaces)
set "STATE_FILE=%cd%\shared\state.json"
set "FRAUD_API_URL=http://127.0.0.1:8001"
set "DATA_DIR=%cd%\data\guardian"
set "REPORTS_DIR=%cd%\data\reports"
set "MLFLOW_TRACKING_URI=file:///%cd:\=/%/data/mlflow"
if not exist "data\guardian" mkdir "data\guardian"
if not exist "data\reports"  mkdir "data\reports"

REM --- 4. Launch the four services -------------------------------
echo [3/5] Launching services in separate windows ...
start "GuardianOps: fraud-api (8001)"      cmd /k ""%PY%" -m uvicorn app.main:app --app-dir services\fraud-api --port 8001 --host 127.0.0.1"
start "GuardianOps: guardian (8002)"       cmd /k ""%PY%" -m uvicorn app.main:app --app-dir services\guardian --port 8002 --host 127.0.0.1"
start "GuardianOps: chaos-injector (8003)" cmd /k ""%PY%" -m uvicorn app.main:app --app-dir services\chaos-injector --port 8003 --host 127.0.0.1"
start "GuardianOps: dashboard (8080)"      cmd /k ""%PY%" -m http.server 8080 --directory frontend --bind 127.0.0.1"

REM --- 5. Wait until every service answers -----------------------
echo [4/5] Waiting for the services to answer ...
set /a TRIES=0
:waitloop
set /a TRIES+=1
curl.exe -s -f -o nul -m 2 http://127.0.0.1:8001/health && curl.exe -s -f -o nul -m 2 http://127.0.0.1:8002/health && curl.exe -s -f -o nul -m 2 http://127.0.0.1:8003/health && curl.exe -s -f -o nul -m 2 http://127.0.0.1:8080/index.html && goto :ready
if %TRIES% GEQ 45 goto :notready
timeout /t 2 /nobreak >nul
goto :waitloop

:notready
echo [WARN] Not every service answered within 90 s. Check the four service windows for errors.
goto :done

:ready
echo        all four services are answering.

:done
echo [5/5] Done.
echo.
echo ============================================================
echo   fraud-api        http://127.0.0.1:8001/docs
echo   guardian         http://127.0.0.1:8002/docs
echo   chaos-injector   http://127.0.0.1:8003/docs
echo   DASHBOARD        http://127.0.0.1:8080
echo.
echo   Guardian needs about 30-60 s after start to capture its
echo   200-sample baseline; the confidence gauge settles at 100
echo   when that is finished.
echo.
echo   Local mode has no container restart policy: after you click
echo   TERMINATE PROCESS, re-run this file (or the fraud-api window
echo   command) to bring fraud-api back. For the full stack with
echo   auto-restart, Grafana and MLflow use:  docker compose up --build
echo.
echo   To stop everything run stop-guardianops.bat
echo ============================================================
if "%NOBROWSER%"=="0" (
    start "" "http://127.0.0.1:8080"
    pause
)
exit /b 0

:pipfail
echo [ERROR] pip could not install the dependencies. Scroll up for the message.
if "%NOBROWSER%"=="0" pause
exit /b 1
