@echo off
cd /d "%~dp0"
call "%~dp0Run_Python.cmd" -m bridge.cancel_transition --restart
pause
