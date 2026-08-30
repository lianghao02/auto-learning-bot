"""建立不使用 PyInstaller 單檔 EXE 的 Windows 可攜式發行版。

建置端會下載並封裝全部 Python 依賴；使用者端不需要安裝 Python、pip，
也不會在首次啟動時連線下載套件。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_version() -> str:
    version = (PROJECT_ROOT / "version.txt").read_text(encoding="utf-8-sig").strip().upper()
    if not version.startswith("V") or not version[1:].replace(".", "").isdigit():
        raise ValueError(f"version.txt 格式不正確：{version!r}")
    return version


VERSION = _read_version()
CONFIG = {
    "release_name": f"行政效能領航員_{VERSION}_Portable",
    # GitHub 會移除 Release asset 檔名中的非 ASCII 字元，導致更新器無法精確比對。
    # ZIP 內頂層資料夾仍保留中文，僅下載資產採穩定 ASCII 名稱。
    "archive_name": f"AdminEfficiencyPilot_{VERSION}_Portable",
    "python_version": "3.13",
    "python_abi": "cp313",
    "platform": "win_amd64",
    "dist_dir": "dist",
    "runtime_source": "python_embed",
    "requirements": "requirements-release.txt",
}

DIST_ROOT = (PROJECT_ROOT / CONFIG["dist_dir"]).resolve()
RELEASE_DIR = (DIST_ROOT / CONFIG["release_name"]).resolve()
CURRENT_DIR = RELEASE_DIR / "current"

APP_FILES = (
    "app.py",
    "ui.py",
    "quiz_bank.py",
    "taipei_eda_course.py",
    "usage_tracker.py",
    "config.json.example",
    "version.txt",
    "README.md",
)
APP_DIRS = ("drivers", "icons", "patches", "utils")

LAUNCHER = r"""@echo off
setlocal
cd /d "%~dp0"
title Admin Efficiency Pilot

if not exist "current\runtime\pythonw.exe" goto RUNTIME_ERROR
if not exist "data" mkdir "data"
if not exist "data\logs" mkdir "data\logs"
if not exist "data\config.json" copy /Y "current\config.json.example" "data\config.json" >nul

"current\runtime\python.exe" -B -c "import PySide6, selenium, requests, cv2, numpy, ddddocr, psutil" >"data\logs\startup_error.log" 2>&1
if errorlevel 1 goto IMPORT_ERROR
del /Q "data\logs\startup_error.log" >nul 2>&1

start "" /D "%~dp0current" "%~dp0current\runtime\pythonw.exe" -B "ui.py"
exit /b 0

:RUNTIME_ERROR
echo [ERROR] Portable runtime not found. Please extract the complete ZIP again.
pause
exit /b 1

:IMPORT_ERROR
echo [ERROR] Portable runtime is incomplete. See startup_error.log.
type "data\logs\startup_error.log"
pause
exit /b 1
"""

SHORTCUT_BAT = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\行政效能領航員.lnk'); if (Test-Path '%~dp0行政效能領航員.exe') { $Shortcut.TargetPath = '%~dp0行政效能領航員.exe'; $Shortcut.WorkingDirectory = '%~dp0'; $Shortcut.IconLocation = '%~dp0current\icons\app.ico, 0'; } else { $Shortcut.TargetPath = '%~dp0啟動程式.bat'; $Shortcut.WorkingDirectory = '%~dp0'; $Shortcut.IconLocation = '%~dp0current\icons\app.ico, 0'; }; $Shortcut.Description = '行政效能領航員 - 公務數位研習輔助系統'; $Shortcut.Save(); Write-Host '已成功於桌面建立「行政效能領航員」捷徑！' -ForegroundColor Green"
echo.
echo 已完成！請至桌面查看捷徑圖示。
pause
"""

RELEASE_INFO = f"""行政效能領航員 {VERSION} 可攜式版本

使用方式：
1. 將整個壓縮檔解壓縮至本機可寫入的位置（建議非系統槽或桌面）。
2. 雙擊「行政效能領航員.exe」（自帶專屬圖示，無黑窗啟動）或「啟動程式.bat」。
3. 亦可雙擊「建立桌面捷徑.bat」一鍵在桌面建立專屬圖示捷徑。
4. 第一次啟動後，在「帳號與系統設定」輸入自己的帳密並儲存。

安全說明：
- 專屬啟動器「行政效能領航員.exe」僅負責環境安全引導與背景喚起，不使用 PyInstaller 單檔自解壓。
- 不需要系統管理員權限，不修改登錄檔，不安裝 Windows 服務。
- 使用者端不執行 pip，也不會下載 Python 套件。
- config.json 含有使用者自行輸入的帳密，請勿轉寄或上傳。
- SHA256SUMS.txt 可供資訊人員核對檔案完整性。
"""


def _build_launcher_exe() -> None:
    """編譯內嵌專屬圖示的輕量 WinExe 啟動器。"""
    launcher_src = PROJECT_ROOT / "scripts" / "launcher" / "Launcher.cs"
    icon_path = PROJECT_ROOT / "icons" / "app.ico"
    output_exe = RELEASE_DIR / "行政效能領航員.exe"

    csc_candidates = [
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / r"Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / r"Microsoft.NET\Framework\v4.0.30319\csc.exe",
    ]
    csc_path = next((p for p in csc_candidates if p.is_file()), shutil.which("csc.exe"))
    if not csc_path:
        # 若無法動態編譯，使用預編譯好的 binary
        cached_exe = PROJECT_ROOT / "scripts" / "launcher" / "行政效能領航員.exe"
        if cached_exe.is_file():
            shutil.copy2(cached_exe, output_exe)
            return
        raise FileNotFoundError("找不到 C# 編譯器 csc.exe 且無預編譯啟動器")

    cmd = [
        str(csc_path),
        "/target:winexe",
        f"/win32icon:{icon_path}",
        f"/out:{output_exe}",
        "/optimize+",
        "/platform:anycpu",
        "/reference:System.Windows.Forms.dll,System.dll",
        str(launcher_src),
    ]
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True, capture_output=True)
    # 同步快取一份在 scripts/launcher/ 備用
    shutil.copy2(output_exe, PROJECT_ROOT / "scripts" / "launcher" / "行政效能領航員.exe")


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
        shutil.copy2(source, CURRENT_DIR / name)

    for name in APP_DIRS:
        source = PROJECT_ROOT / name
        if not source.is_dir():
            raise FileNotFoundError(f"缺少發行必要資料夾：{name}")
        shutil.copytree(source, CURRENT_DIR / name, ignore=ignore)


def _create_seed_database() -> None:
    """由版本庫內的 answers.json 建立唯讀種子題庫，避免夾帶本機 questions.db。"""
    source = PROJECT_ROOT / "answers.json"
    rows = json.loads(source.read_text(encoding="utf-8")) if source.is_file() else []
    assets = CURRENT_DIR / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    target = assets / "questions_seed.db"
    conn = sqlite3.connect(target)
    try:
        conn.execute("CREATE TABLE questions (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT UNIQUE NOT NULL, option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT, answer TEXT)")
        for row in rows:
            if isinstance(row, dict) and row.get("題目"):
                conn.execute(
                    "INSERT OR REPLACE INTO questions (question, answer) VALUES (?, ?)",
                    (str(row["題目"]), str(row.get("答案", ""))),
                )
        conn.commit()
    finally:
        conn.close()


def _prepare_runtime() -> None:
    runtime_source = PROJECT_ROOT / CONFIG["runtime_source"]
    runtime_target = CURRENT_DIR / "runtime"
    if not runtime_source.is_dir():
        raise FileNotFoundError("找不到官方 Python 嵌入式執行環境")
    shutil.copytree(runtime_source, runtime_target)

    # python_embed 可能是開發者已使用過的環境。發行版不可混入其中的
    # 舊套件，因此只清理「輸出副本」後再依鎖定清單乾淨安裝。
    site_packages = runtime_target / "Lib" / "site-packages"
    if site_packages.exists():
        shutil.rmtree(site_packages)
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

    compact_version = CONFIG["python_version"].replace(".", "")
    pth_path = runtime_target / f"python{compact_version}._pth"
    pth_path.write_text(
        f"python{compact_version}.zip\n.\nLib\\site-packages\nimport site\n",
        encoding="utf-8",
    )

    runtime_python = runtime_target / "python.exe"
    version_result = subprocess.run(
        [str(runtime_python), "--version"],
        cwd=CURRENT_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    runtime_version = (version_result.stdout or version_result.stderr).strip()
    if not runtime_version.startswith(f"Python {CONFIG['python_version']}."):
        raise RuntimeError(f"可攜 runtime 版本不符：{runtime_version}")

    subprocess.run(
        [
            str(runtime_python),
            "-B",
            "-c",
            "import PySide6, selenium, requests, cv2, numpy, ddddocr, psutil",
        ],
        cwd=CURRENT_DIR,
        check=True,
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
        # Qt runtime 已含大量壓縮資源；等級 6 可大幅縮短建置時間，
        # 對最終檔案大小的影響有限。
        compresslevel=6,
    ) as archive:
        for path in sorted(RELEASE_DIR.rglob("*")):
            if not path.is_file() or not _is_distributable(path):
                continue
            relative = path.relative_to(RELEASE_DIR).as_posix()
            archive.write(path, f"{CONFIG['release_name']}/{relative}")



def safe_rmtree(path: Path) -> None:
    if not path.exists():
        return
    import stat
    def on_error(func, p, _):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    try:
        subprocess.run(f'cmd /c "rmdir /s /q \"{path}\""', shell=True, check=False)
    except Exception:
        pass
    if path.exists():
        shutil.rmtree(path, onerror=on_error)

def main() -> int:
    _assert_safe_release_path()
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    if RELEASE_DIR.exists():
        safe_rmtree(RELEASE_DIR)
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        _copy_application_files()
        _create_seed_database()
        _prepare_runtime()
        # 使用純 ASCII 且不含 BOM，確保 Windows cmd 能正確辨識 @echo off。
        (RELEASE_DIR / "啟動程式.bat").write_text(LAUNCHER, encoding="ascii")
        # 建立專屬圖示之輕量 WinExe 啟動器
        _build_launcher_exe()
        # 建立桌面捷徑腳本
        (RELEASE_DIR / "建立桌面捷徑.bat").write_text(SHORTCUT_BAT, encoding="utf-8")
        # Windows PowerShell 5.1 需 BOM 才能可靠辨識中文路徑與訊息。
        updater_source = (PROJECT_ROOT / "scripts" / "auto_update.ps1").read_text(
            encoding="utf-8-sig"
        )
        (RELEASE_DIR / "auto_update.ps1").write_text(
            updater_source,
            encoding="utf-8-sig",
        )
        (RELEASE_DIR / "發行說明.txt").write_text(RELEASE_INFO, encoding="utf-8-sig")
        _write_manifest()

        archive_base = DIST_ROOT / CONFIG["archive_name"]
        # 發行名稱含版本點號，不能用 with_suffix()，否則 V2.2.0 會被
        # 誤判成副檔名並截成 V2.2.zip。
        archive_path = Path(f"{archive_base}.zip")
        if archive_path.exists():
            archive_path.unlink()
        _create_archive(archive_path)
        archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        archive_path.with_suffix(".zip.sha256").write_text(
            f"{archive_hash} *{archive_path.name}\n",
            encoding="utf-8",
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
