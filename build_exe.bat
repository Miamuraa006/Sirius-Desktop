@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -File scripts\build_desktop.ps1 %*
exit /b %errorlevel%
