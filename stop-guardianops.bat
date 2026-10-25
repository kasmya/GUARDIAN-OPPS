@echo off
REM ============================================================
REM  GuardianOps — stop all local services started by
REM  start-guardianops.bat. Closes only the 4 windows that were
REM  opened with the "GuardianOps:" title prefix, so it will not
REM  touch any other python/terminal windows you have open.
REM ============================================================

echo Stopping GuardianOps services...

taskkill /FI "WINDOWTITLE eq GuardianOps: fraud-api*"        /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq GuardianOps: guardian*"          /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq GuardianOps: chaos-injector*"    /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq GuardianOps: frontend*"          /T /F >nul 2>nul

echo Done. If a window is still open, close it manually.
pause
