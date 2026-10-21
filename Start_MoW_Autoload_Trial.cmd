@echo off
cd /d "%~dp0"
call "%~dp0Run_Python.cmd" -m native_trial.mow_launch_probe
pause
