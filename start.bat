@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=
set PYTHONUTF8=1
if defined SIRIUS_PYTHON goto run
if exist ".venv\Scripts\python.exe" goto existing
py -3.12 -m venv .venv
if errorlevel 1 (
  echo Python 3.12 x64 is required for source startup. Portable EXE does not require Python.
  exit /b 1
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
:existing
set "SIRIUS_PYTHON=%~dp0.venv\Scripts\python.exe"
:run
"%SIRIUS_PYTHON%" main.py %*
exit /b %errorlevel%
