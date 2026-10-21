@echo off
cd /d "%~dp0"
call "%~dp0Run_Python.cmd" -m bridge.return_recovery --keep-current
pause
