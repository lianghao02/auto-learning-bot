@echo off
chcp 65001 > nul
title 行政效能領航員 - 開啟 UI 介面
setlocal

:: 切換到批次檔所在的目錄，防止工作目錄跑掉
cd /d "%~dp0"

:: 優先檢查並啟用本地虛擬環境
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

:: 檢查是否有安裝 uv (推薦)
where uv >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    start "" uv run pythonw ui.py
    exit
) else (
    start "" pythonw ui.py
    exit
)
