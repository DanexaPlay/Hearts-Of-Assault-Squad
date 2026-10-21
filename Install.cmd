@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist "%~dp0installer.py" (
  echo Extract the complete release ZIP into a permanent folder before running Install.cmd.
  pause
  exit /b 1
)
if defined BRIDGE_PYTHON goto check_python
if exist "%~dp0.venv\Scripts\python.exe" (
  set "BRIDGE_PYTHON=%~dp0.venv\Scripts\python.exe"
  goto check_python
)
for %%V in (313 312 314) do if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" (
  set "BRIDGE_PYTHON=%LocalAppData%\Programs\Python\Python%%V\python.exe"
  goto check_python
)
py -3 -c "import struct,sys; sys.exit(not (sys.version_info >= (3,12) and struct.calcsize('P') == 8))" >nul 2>nul
if not errorlevel 1 goto use_py
python -c "import struct,sys; sys.exit(not (sys.version_info >= (3,12) and struct.calcsize('P') == 8))" >nul 2>nul
if not errorlevel 1 (
  set "BRIDGE_PYTHON=python"
  goto check_python
)
echo Python 3.12+ x64 was not found.
choice /c YN /m "Install official Python 3.13 through winget?"
if errorlevel 2 goto missing_python
winget install --id Python.Python.3.13 --exact --source winget --scope user
if errorlevel 1 goto missing_python
if not exist "%LocalAppData%\Programs\Python\Python313\python.exe" goto missing_python
set "BRIDGE_PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
goto check_python

:use_py
py -3 installer.py %*
set "INSTALL_RESULT=%errorlevel%"
goto finish

:check_python
"%BRIDGE_PYTHON%" -c "import struct,sys; sys.exit(not (sys.version_info >= (3,12) and struct.calcsize('P') == 8))"
if errorlevel 1 goto missing_python
"%BRIDGE_PYTHON%" installer.py %*
set "INSTALL_RESULT=%errorlevel%"
goto finish

:missing_python
echo Install Python 3.12+ x64 from https://www.python.org/downloads/windows/ and run Install.cmd again.
set "INSTALL_RESULT=1"
:finish
echo.
if not "%INSTALL_RESULT%"=="0" echo Installation did not complete. See the message above and runtime\installer.log.
pause
exit /b %INSTALL_RESULT%
