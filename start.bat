@echo off
rem SheetFlow launcher for Windows (double-click or run from a shortcut).
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
  .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) else (
  python -m pip install -q -r requirements.txt
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
)
pause
