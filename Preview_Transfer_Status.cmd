@echo off
cd /d "%~dp0"
call "%~dp0Run_Python.cmd" -m native_trial.status_panel_probe
pause
