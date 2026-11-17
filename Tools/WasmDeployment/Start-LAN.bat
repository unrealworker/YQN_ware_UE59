@echo off
cd /d "%~dp0"
"Runtime\python.exe" -I -B start_server.py %*
if errorlevel 1 pause
