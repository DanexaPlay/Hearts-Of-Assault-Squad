@echo off
setlocal
cd /d "%~dp0"
if defined BRIDGE_PYTHON (
  set "_BRIDGE_SELECTED=%BRIDGE_PYTHON%"
  goto run_python
)
if exist "%~dp0.venv\Scripts\python.exe" (
  set "_BRIDGE_SELECTED=%~dp0.venv\Scripts\python.exe"
  goto run_python
)
where py >nul 2>nul
if not errorlevel 1 goto run_py_launcher
where python >nul 2>nul
if not errorlevel 1 (
  set "_BRIDGE_SELECTED=python"
  goto run_python
)
echo Python 3.12 or newer is required. Install it from python.org.
exit /b 1

:run_python
"%_BRIDGE_SELECTED%" %*
exit /b %errorlevel%

:run_py_launcher
py -3 %*
exit /b %errorlevel%
