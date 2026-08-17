"""建立不使用 PyInstaller 單檔 EXE 的 Windows 可攜式發行版。

建置端會下載並封裝全部 Python 依賴；使用者端不需要安裝 Python、pip，
也不會在首次啟動時連線下載套件。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


CONFIG = {
    "release_name": "行政效能領航員_V2.2.1_Portable",
    "python_version": "3.11",
    "python_abi": "cp311",
    "platform": "win_amd64",
    "dist_dir": "dist",
    "runtime_source": "python_embed",
    "requirements": "requirements-release.txt",
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_ROOT = (PROJECT_ROOT / CONFIG["dist_dir"]).resolve()
RELEASE_DIR = (DIST_ROOT / CONFIG["release_name"]).resolve()

APP_FILES = (
    "app.py",
    "ui.py",
    "quiz_bank.py",
    "taipei_eda_course.py",
    "usage_tracker.py",
    "answers.json",
    "questions.db",
    "config.json.example",
    "version.txt",
    "README.md",
)
APP_DIRS = ("drivers", "icons", "patches", "utils")

LAUNCHER = r"""@echo off
setlocal
cd /d "%~dp0"
title Admin Efficiency Pilot

if not exist "runtime\pythonw.exe" goto RUNTIME_ERROR
if not exist "config.json" copy /Y "config.json.example" "config.json" >nul

"runtime\python.exe" -B -c "import PySide6, selenium, requests" >"startup_error.log" 2>&1
if errorlevel 1 goto IMPORT_ERROR
del /Q "startup_error.log" >nul 2>&1

start "" "runtime\pythonw.exe" -B "ui.py"
exit /b 0

:RUNTIME_ERROR
echo [ERROR] Portable runtime not found. Please extract the complete ZIP again.
pause
exit /b 1

:IMPORT_ERROR
echo [ERROR] Portable runtime is incomplete. See startup_error.log.
type "startup_error.log"
pause
exit /b 1
"""

RELEASE_INFO = """行政效能領航員 V2.2.1 可攜式版本

使用方式：
1. 將整個資料夾解壓縮至本機可寫入的位置。
2. 雙擊「啟動程式.bat」。
3. 第一次啟動後，在「帳號與系統設定」輸入自己的帳密。

安全說明：
- 本版本不使用 PyInstaller 單檔自解壓 EXE。
- 不需要系統管理員權限，不修改登錄檔，不安裝 Windows 服務。
- 使用者端不執行 pip，也不會下載 Python 套件。
- config.json 含有使用者自行輸入的帳密，請勿轉寄或上傳。
- SHA256SUMS.txt 可供資訊人員核對檔案完整性。
"""


def _assert_safe_release_path() -> None:
    """避免清理流程超出專案 dist 目錄。"""
    if RELEASE_DIR.parent != DIST_ROOT or DIST_ROOT.parent != PROJECT_ROOT:
        raise RuntimeError(f"拒絕使用非預期輸出路徑：{RELEASE_DIR}")


def _copy_application_files() -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.log", "config.json")
    for name in APP_FILES:
        source = PROJECT_ROOT / name
        if not source.is_file():
            raise FileNotFoundError(f"缺少發行必要檔案：{name}")
        shutil.copy2(source, RELEASE_DIR / name)

    for name in APP_DIRS:
        source = PROJECT_ROOT / name
        if not source.is_dir():
            raise FileNotFoundError(f"缺少發行必要資料夾：{name}")
        shutil.copytree(source, RELEASE_DIR / name, ignore=ignore)


def _prepare_runtime() -> None:
    runtime_source = PROJECT_ROOT / CONFIG["runtime_source"]
    runtime_target = RELEASE_DIR / "runtime"
    if not runtime_source.is_dir():
        raise FileNotFoundError("找不到官方 Python 嵌入式執行環境")
    shutil.copytree(runtime_source, runtime_target)

    site_packages = runtime_target / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    requirements = PROJECT_ROOT / CONFIG["requirements"]
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-compile",
        "--only-binary=:all:",
        f"--platform={CONFIG['platform']}",
        f"--python-version={CONFIG['python_version']}",
        "--implementation=cp",
        f"--abi={CONFIG['python_abi']}",
        "--target",
        str(site_packages),
        "--requirement",
        str(requirements),
    ]
    print("[BUILD] 正在下載並封裝 Windows 離線依賴套件...")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)

    pth_path = runtime_target / "python311._pth"
    pth_path.write_text(
        "python311.zip\n.\n..\nLib\\site-packages\nimport site\n",
        encoding="utf-8",
    )

    # pip 可能仍從快取帶入其他 Python 版本的 bytecode，發行前一律移除。
    for cache_dir in sorted(runtime_target.rglob("__pycache__"), reverse=True):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir)
    for bytecode in runtime_target.rglob("*.py[co]"):
        bytecode.unlink()


def _write_manifest() -> None:
    rows = []
    for path in sorted(RELEASE_DIR.rglob("*")):
        relative = path.relative_to(RELEASE_DIR).as_posix()
        if (
            not path.is_file()
            or path.name == "SHA256SUMS.txt"
            or relative == "config.json"
            or path.suffix.lower() == ".log"
            or "__pycache__" in path.parts
            or path.suffix.lower() in {".pyc", ".pyo"}
        ):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest} *{relative}")
    (RELEASE_DIR / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _is_distributable(path: Path) -> bool:
    """排除執行後才產生的個人設定、日誌與快取。"""
    relative = path.relative_to(RELEASE_DIR).as_posix()
    return not (
        relative == "config.json"
        or path.suffix.lower() == ".log"
        or "__pycache__" in path.parts
        or path.suffix.lower() in {".pyc", ".pyo"}
    )


def _create_archive(archive_path: Path) -> None:
    """建立含頂層資料夾且不夾帶個人執行資料的 ZIP。"""
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(RELEASE_DIR.rglob("*")):
            if not path.is_file() or not _is_distributable(path):
                continue
            relative = path.relative_to(RELEASE_DIR).as_posix()
            archive.write(path, f"{CONFIG['release_name']}/{relative}")


def main() -> int:
    _assert_safe_release_path()
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR)
    RELEASE_DIR.mkdir(parents=True)

    try:
        _copy_application_files()
        _prepare_runtime()
        # 使用純 ASCII 且不含 BOM，確保 Windows cmd 能正確辨識 @echo off。
        (RELEASE_DIR / "啟動程式.bat").write_text(LAUNCHER, encoding="ascii")
        (RELEASE_DIR / "發行說明.txt").write_text(RELEASE_INFO, encoding="utf-8-sig")
        _write_manifest()

        archive_base = DIST_ROOT / CONFIG["release_name"]
        # 發行名稱含版本點號，不能用 with_suffix()，否則 V2.2.0 會被
        # 誤判成副檔名並截成 V2.2.zip。
        archive_path = Path(f"{archive_base}.zip")
        if archive_path.exists():
            archive_path.unlink()
        _create_archive(archive_path)
        archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        archive_path.with_suffix(".zip.sha256").write_text(
            f"{archive_hash} *{archive_path.name}\n",
            encoding="ascii",
        )
    except Exception:
        print("[ERROR] 建置失敗，保留輸出目錄供檢查。")
        raise

    print(f"[OK] 可攜式發行資料夾：{RELEASE_DIR}")
    print(f"[OK] 可交付壓縮檔：{archive_path}")
    print(f"[OK] ZIP SHA-256：{archive_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
