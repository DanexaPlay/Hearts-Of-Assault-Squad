@echo off
cd /d "%~dp0"
call "%~dp0Run_Python.cmd" Configure.py %*
pause
