@echo off
cd /d "%~dp0"
call "%~dp0Run_Python.cmd" -m native_trial.mow_launch_probe --source sessions/automatic/71df69ba79b54f9fbe238cbec65dc317 --require-closed
pause
