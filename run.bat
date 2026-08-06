@echo off
chcp 65001 > nul
title Auto Learning Bot Launcher

cd /d "%~dp0"

echo ============================================================
echo Auto Learning Bot - Initializing System...
echo ============================================================

:: 1. Check .venv first (If valid, launch directly)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        echo [OK] Valid virtual environment detected.
        goto LAUNCH_VENV
    )
    echo [WARNING] .venv path mismatched. Resetting .venv...
    if exist ".venv" rmdir /s /q .venv
)

:: 2. Search Embedded Python or System Python
set PYTHON_CMD=python
if exist "python_embed\python.exe" (
    set PYTHON_CMD=python_embed\python.exe
    echo [INFO] Found embedded Python in python_embed folder.
) else if exist "python\python.exe" (
    set PYTHON_CMD=python\python.exe
    echo [INFO] Found embedded Python in python folder.
)

:: Check Python availability
%PYTHON_CMD% --version >nul 2>&1
if errorlevel 1 (
    echo ============================================================
    echo [ERROR] Python 3.10+ environment not found!
    echo.
    echo Solutions:
    echo   1. Install official Python 3.10+ (check Add Python to PATH)
    echo   2. Download Python Embeddable package into 'python_embed' folder
    echo ============================================================
    pause
    exit /b 1
)

:: 3. Check config.json
if not exist "config.json" (
    if exist "config.json.example" (
        echo [INFO] Copying default config.json...
        copy "config.json.example" "config.json" >nul
    )
)

:: 4. Create virtual environment using detected Python
echo [INFO] Creating virtual environment (.venv)...
%PYTHON_CMD% -m venv .venv
call .venv\Scripts\activate.bat
echo [INFO] Installing required packages...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt
echo [OK] Package installation completed!

:LAUNCH_VENV
echo [OK] Launching GUI...
echo ============================================================
start "" .venv\Scripts\pythonw.exe ui.py
exit /b 0
