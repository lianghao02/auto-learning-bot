@echo off
chcp 65001 > nul
title Auto Learning Bot Launcher

cd /d "%~dp0"

echo ============================================================
echo Auto Learning Bot - Initializing System...
echo ============================================================

:: 1. Check existing .venv
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import PySide6, selenium, requests" >nul 2>&1
    if not errorlevel 1 (
        echo [OK] Valid virtual environment detected.
        goto LAUNCH_VENV
    )
    echo [INFO] Existing .venv is incomplete or missing packages. Installing dependencies...
    goto INSTALL_DEPS
)

:: 2. Search Python with venv support
set PYTHON_CMD=python

%PYTHON_CMD% -c "import venv" >nul 2>&1
if errorlevel 1 (
    if exist "python\python.exe" (
        python\python.exe -c "import venv" >nul 2>&1
        if not errorlevel 1 (
            set PYTHON_CMD=python\python.exe
            echo [INFO] Found Python in python folder.
        )
    )
)

:: Check Python availability & venv capability
%PYTHON_CMD% -c "import venv" >nul 2>&1
if errorlevel 1 (
    echo ============================================================
    echo [ERROR] Python 3.10+ with 'venv' module not found!
    echo.
    echo Solutions:
    echo   1. Install official Python 3.10+ (check Add Python to PATH)
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
if not exist ".venv\Scripts\activate.bat" (
    echo ============================================================
    echo [ERROR] Failed to create virtual environment (.venv).
    echo Please make sure system Python includes the venv module.
    echo ============================================================
    pause
    exit /b 1
)

:INSTALL_DEPS
call .venv\Scripts\activate.bat
echo [INFO] Installing required packages...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt
echo [OK] Package installation completed!

:LAUNCH_VENV
echo [OK] Launching GUI...
echo ============================================================

".venv\Scripts\python.exe" -c "import PySide6, selenium, requests" >"startup_error.log" 2>&1
if errorlevel 1 (
    echo [ERROR] Virtual environment is incomplete or failed to launch.
    echo ------------------------------------------------------------
    type "startup_error.log"
    echo ------------------------------------------------------------
    pause
    exit /b 1
)
if exist "startup_error.log" del /Q "startup_error.log" >nul 2>&1

start "" .venv\Scripts\pythonw.exe ui.py
exit /b 0
