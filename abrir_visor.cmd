@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Falta el entorno .venv. Sigue la instalacion indicada en README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m scripts.serve_dashboard --open
if errorlevel 1 pause
