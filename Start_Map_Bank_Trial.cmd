@echo off
cd /d "%~dp0"
call "%~dp0Run_Python.cmd" -m native_trial.unique_maps_probe --all-maps
pause
