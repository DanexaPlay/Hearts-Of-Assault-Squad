@echo off
setlocal
cd /d "%~dp0"
if defined BRIDGE_PYTHON (
  "%BRIDGE_PYTHON%" %*
  exit /b
)
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" %*
  exit /b
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 %*
  exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
  python %*
  exit /b
)
echo Python 3.12 or newer is required. Install it from python.org.
exit /b 1
