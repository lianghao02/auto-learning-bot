@echo off
chcp 65001 > nul
title Auto Learning Bot Launcher

cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%PYTHONPATH%"

echo ============================================================
echo Auto Learning Bot - Initializing System...
echo ============================================================

:: 1. Try system Python first if PySide6 is ready
python -c "import PySide6" >nul 2>&1
if not errorlevel 1 goto LAUNCH_SYS

:: 2. Try .venv if PySide6 is ready
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import PySide6" >nul 2>&1
    if not errorlevel 1 goto LAUNCH_VENV
)

:: 3. Try embedded Python if PySide6 is ready
if exist "python_embed\python.exe" (
    "python_embed\python.exe" -c "import PySide6" >nul 2>&1
    if not errorlevel 1 goto LAUNCH_EMBED
    echo [INFO] Installing required GUI packages into embedded Python...
    "python_embed\python.exe" -m pip install -r requirements.txt
    goto LAUNCH_EMBED
)

:: 4. Fallback: Create .venv
echo [INFO] Creating new virtual environment (.venv)...
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
goto LAUNCH_VENV

:LAUNCH_SYS
echo [OK] Launching GUI with system Python...
echo ============================================================
start "" pythonw ui.py
exit /b 0

:LAUNCH_VENV
echo [OK] Launching GUI with virtual environment...
echo ============================================================
start "" .venv\Scripts\pythonw.exe ui.py
exit /b 0

:LAUNCH_EMBED
echo [OK] Launching GUI with embedded Python...
echo ============================================================
start "" python_embed\pythonw.exe ui.py
exit /b 0
