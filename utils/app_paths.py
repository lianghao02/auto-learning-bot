"""應用程式、安裝目錄與使用者資料路徑管理。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


USER_DATA_FILES = ("config.json", "questions.db", "answers.json")


def app_dir() -> Path:
    """回傳目前程式檔所在目錄；可攜版為 ``<安裝目錄>/current``。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def install_root() -> Path:
    """回傳可攜版安裝根目錄；原始碼執行時即為專案根目錄。"""
    root = app_dir()
    return root.parent if root.name.lower() == "current" else root


def data_dir(create: bool = False) -> Path:
    path = install_root() / "data"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def user_data_path(name: str, *, migrate: bool = True) -> Path:
    """取得資料檔路徑，首次使用時複製舊版根目錄資料但不刪除原檔。"""
    target = data_dir(create=True) / Path(name).name
    legacy = app_dir() / Path(name).name
    if migrate and not target.exists() and legacy.is_file() and legacy != target:
        shutil.copy2(legacy, target)
    return target


def ensure_seeded_database() -> Path:
    """確保使用者題庫存在；新安裝從唯讀種子題庫建立。"""
    target = user_data_path("questions.db")
    if target.exists():
        return target
    seed = app_dir() / "assets" / "questions_seed.db"
    if seed.is_file():
        shutil.copy2(seed, target)
    return target


def log_path(name: str) -> Path:
    logs = data_dir(create=True) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / Path(name).name


def update_cache_path() -> Path:
    return data_dir(create=True) / "update_cache.json"


def is_portable_layout() -> bool:
    return app_dir().name.lower() == "current" and (install_root() / "啟動程式.bat").is_file()


def prepare_user_data() -> None:
    for name in USER_DATA_FILES:
        user_data_path(name)
    ensure_seeded_database()


def same_volume(path_a: str | Path, path_b: str | Path) -> bool:
    drive_a = os.path.splitdrive(str(Path(path_a).resolve()))[0].lower()
    drive_b = os.path.splitdrive(str(Path(path_b).resolve()))[0].lower()
    return drive_a == drive_b
