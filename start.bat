@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=C:\Users\30122\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" server.py
echo.
echo Server stopped. Press any key to close.
pause >nul
