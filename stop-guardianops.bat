@echo off
REM ============================================================
REM  GuardianOps - stop the local services started by
REM  start-guardianops.bat. Only closes windows whose title starts
REM  with "GuardianOps:", so nothing else on your machine is touched.
REM ============================================================
echo Stopping GuardianOps services ...
taskkill /FI "WINDOWTITLE eq GuardianOps: fraud-api*"      /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq GuardianOps: guardian*"       /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq GuardianOps: chaos-injector*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq GuardianOps: dashboard*"      /T /F >nul 2>nul
echo Done. If a window is still open, close it by hand.
if /i not "%~1"=="nopause" pause
