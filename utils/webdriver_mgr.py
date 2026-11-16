# -*- coding: utf-8 -*-
import sys
import requests, zipfile, io, os, platform, shutil
from pathlib import Path
import logging

if sys.platform == "win32":
    import winreg

logger = logging.getLogger("LearningPilot")


def get_local_chrome_version() -> str | None:
    """透過 Windows 登錄檔獲取本機 Chrome 版本（僅 Windows）；找不到時回傳 None。"""
    if sys.platform != "win32":
        return None
    reg_path = r"SOFTWARE\Google\Chrome\BLBeacon"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, reg_path) as key:
                ver = str(winreg.QueryValueEx(key, "version")[0] or "").strip()
                if ver:
                    return ver
        except OSError:
            continue
    return None


def _resolve_target_folder(folder_name: str = "drivers") -> str:
    if getattr(sys, "frozen", False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, folder_name)


def _kill_scoped_chromedrivers(target_folder: str) -> None:
    """僅終止執行路徑位於本專案 driver 目錄內的 chromedriver，避免誤殺其他程式進程。"""
    import time
    import psutil

    scoped_dir = str(Path(target_folder).resolve()).casefold()
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if "chromedriver" not in name:
                continue
            exe = proc.info.get("exe") or ""
            if exe and str(Path(exe).resolve()).casefold().startswith(scoped_dir):
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    time.sleep(0.5)


def _extract_driver_zip(zip_url: str, target_folder: str, local_version: str) -> str:
    """下載並驗證 ChromeDriver ZIP（檢查 HTTP 狀態並禁止 zip-slip 路徑穿越）。"""
    resp = requests.get(zip_url, timeout=30)
    resp.raise_for_status()
    target_root = Path(target_folder).resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for member in zf.infolist():
            member_path = (target_root / member.filename).resolve()
            if target_root not in member_path.parents and member_path != target_root:
                raise ValueError(f"ChromeDriver ZIP 含有不安全路徑：{member.filename}")
        zf.extractall(target_root)

    driver = next(target_root.rglob("chromedriver.exe"), None)
    if not driver:
        raise RuntimeError("解壓縮後找不到 chromedriver.exe")

    final_path = os.path.join(str(target_root), "chromedriver.exe")
    shutil.move(str(driver), final_path)

    try:
        version_file = os.path.join(str(target_root), "driver_version.txt")
        with open(version_file, "w", encoding="utf-8") as f:
            f.write(local_version)
    except OSError:
        pass

    logger.info(f"驅動配置完成: {final_path}")
    return final_path


def download_best_chromedriver(folder_name="drivers"):
    """自動下載並匹配 Windows 版 ChromeDriver，優先找完全相同版本"""
    target_folder = _resolve_target_folder(folder_name)
    driver_file = os.path.join(target_folder, "chromedriver.exe")
    version_file = os.path.join(target_folder, "driver_version.txt")

    local_version = get_local_chrome_version()
    if not local_version:
        if os.path.exists(driver_file):
            logger.warning("⚠️ 無法偵測本機 Chrome 版本，沿用既有的本機 chromedriver")
            return driver_file
        raise RuntimeError("無法從系統登錄檔偵測 Chrome 版本，且找不到本機 chromedriver.exe")

    parts = local_version.split(".")

    try:
        if os.path.exists(driver_file):
            # 比對 Chrome major 版本，不符就刪除重下
            chrome_major = parts[0]
            cached_major = None
            if os.path.exists(version_file):
                try:
                    cached_major = open(version_file, encoding="utf-8").read().strip().split(".")[0]
                except Exception:
                    pass
            if cached_major == chrome_major:
                logger.info(f"✅ 已確認背景 Driver 進程狀態（版本相符 {chrome_major}.x）: {driver_file}")
                return driver_file
            else:
                logger.info(f"Chrome 版本已更新（{cached_major} → {chrome_major}），重新下載 driver...")
                try:
                    os.remove(driver_file)
                except PermissionError:
                    try:
                        _kill_scoped_chromedrivers(target_folder)
                        if os.path.exists(driver_file):
                            os.remove(driver_file)
                    except Exception as _pe:
                        logger.warning(f"無法刪除鎖定的 driver 檔案: {_pe}")
                if os.path.exists(version_file):
                    try:
                        os.remove(version_file)
                    except Exception:
                        pass

        os.makedirs(target_folder, exist_ok=True)
    except Exception as e:
        logger.warning(f"清理驅動目錄時發生警告: {e}")

    prefix3 = ".".join(parts[:3])
    logger.info(f"偵測到本機 Chrome 版本: {local_version}")

    # 策略一：known-good-versions，優先找完全相同版本
    try:
        known_url = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
        logger.info(f"正在尋找與 {local_version} 完全匹配的驅動...")
        resp = requests.get(known_url, timeout=15)
        resp.raise_for_status()
        versions = resp.json().get("versions", [])

        exact = next((v for v in versions if v["version"] == local_version), None)
        if not exact:
            same_build = [v for v in versions if v["version"].startswith(prefix3 + ".")]
            if same_build:
                local_patch = int(parts[3]) if len(parts) > 3 else 0
                exact = min(
                    same_build,
                    key=lambda v: abs(int(v["version"].split(".")[3]) - local_patch),
                )
                logger.info(f"找不到完全匹配，改用最接近版本: {exact['version']}")

        if exact:
            url = next(
                (
                    d["url"]
                    for d in exact["downloads"].get("chromedriver", [])
                    if d["platform"] == "win64"
                ),
                None,
            )
            if url:
                logger.info(f"正在下載驅動程式: {url}")
                return _extract_driver_zip(url, target_folder, local_version)
    except Exception as e:
        logger.warning(f"精確版本查詢失敗，改用 patch API: {e}")

    # 策略二：patch API fallback
    try:
        json_url = "https://raw.githubusercontent.com/GoogleChromeLabs/chrome-for-testing/refs/heads/gh-pages/latest-patch-versions-per-build-with-downloads.json"
        logger.info(f"正在從 GitHub 獲取匹配 {prefix3} 的驅動資訊...")
        resp = requests.get(json_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        entry = data["builds"][prefix3]
        url = next(
            d["url"]
            for d in entry["downloads"]["chromedriver"]
            if d["platform"] == "win64"
        )
        logger.info(f"正在下載驅動程式: {url}")
        return _extract_driver_zip(url, target_folder, local_version)
    except Exception as e:
        logger.error(f"Driver 下載或配置故障: {e}")
        fallback = os.path.join(target_folder, "chromedriver.exe")
        if os.path.exists(fallback):
            return fallback
        raise e


def download_best_chromedriver_with_fallback(folder_name="drivers"):
    """
    手動版專用：
    1. 先試自動下載（同標準版）
    2. 下載失敗 → 找 drivers/ 資料夾內的 chromedriver.exe
    3. 再失敗 → 找系統 PATH 內的 chromedriver
    4. 都沒有 → 報錯說明
    """
    # ── 策略一：自動下載 ──
    try:
        return download_best_chromedriver(folder_name)
    except Exception as e:
        logger.warning(f"自動下載 driver 失敗（{e}），改用本機 driver...")

    # ── 策略二：drivers/ 資料夾內 ──
    if getattr(sys, "frozen", False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_path = os.path.join(base_path, folder_name, "chromedriver.exe")
    if os.path.exists(local_path):
        logger.info(f"✅ 使用本機 driver: {local_path}")
        return local_path

    # ── 策略三：系統 PATH ──
    path_driver = shutil.which("chromedriver") or shutil.which("chromedriver.exe")
    if path_driver:
        logger.info(f"✅ 使用系統 PATH driver: {path_driver}")
        return path_driver

    # ── 全部失敗 ──
    logger.error(
        "❌ 無法取得 ChromeDriver。\n"
        "請至 https://googlechromelabs.github.io/chrome-for-testing/ "
        "下載與您 Chrome 版本相符的 chromedriver，\n"
        "解壓縮後將 chromedriver.exe 放入程式同層的 drivers\\ 資料夾再重新執行。"
    )
    raise RuntimeError("找不到可用的 ChromeDriver")


def download_best_chromedriver_milestone(folder_name="drivers"):
    """
    手動版專用，比標準版多一條 milestone API 策略：
    1. known-good-versions（同標準版策略一）
    2. latest-patch-versions-per-build（同標準版策略二）
    3. latest-versions-per-milestone（新增，專門處理最新 Chrome 還沒收錄的情況）
    4. 以上都失敗 → 找 drivers/ 或系統 PATH 的本機 driver
    """
    target_folder = _resolve_target_folder(folder_name)
    local_version = get_local_chrome_version()
    if not local_version:
        local_path = os.path.join(target_folder, "chromedriver.exe")
        if os.path.exists(local_path):
            logger.warning("⚠️ 無法偵測本機 Chrome 版本，沿用既有的本機 driver")
            return local_path
        path_driver = shutil.which("chromedriver") or shutil.which("chromedriver.exe")
        if path_driver:
            return path_driver
        raise RuntimeError("找不到可用的 ChromeDriver（無法偵測本機 Chrome 版本）")

    parts = local_version.split(".")
    major = parts[0]          # e.g. "147"
    prefix3 = ".".join(parts[:3])
    logger.info(f"偵測到本機 Chrome 版本: {local_version}")

    os.makedirs(target_folder, exist_ok=True)

    # ── 策略一：known-good-versions ──
    try:
        known_url = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
        logger.info(f"[milestone版] 策略一：尋找與 {local_version} 完全匹配的驅動...")
        resp = requests.get(known_url, timeout=15)
        resp.raise_for_status()
        versions = resp.json().get("versions", [])
        exact = next((v for v in versions if v["version"] == local_version), None)
        if exact:
            url = next((d["url"] for d in exact["downloads"].get("chromedriver", []) if d["platform"] == "win64"), None)
            if url:
                logger.info(f"策略一成功，下載: {url}")
                return _extract_driver_zip(url, target_folder, local_version)
    except Exception as e:
        logger.warning(f"策略一失敗: {e}")

    # ── 策略二：latest-patch-versions-per-build ──
    try:
        patch_url = "https://raw.githubusercontent.com/GoogleChromeLabs/chrome-for-testing/refs/heads/gh-pages/latest-patch-versions-per-build-with-downloads.json"
        logger.info(f"[milestone版] 策略二：查詢 {prefix3} patch 版本...")
        resp = requests.get(patch_url, timeout=10)
        resp.raise_for_status()
        entry = resp.json()["builds"][prefix3]
        url = next(d["url"] for d in entry["downloads"]["chromedriver"] if d["platform"] == "win64")
        logger.info(f"策略二成功，下載: {url}")
        return _extract_driver_zip(url, target_folder, local_version)
    except Exception as e:
        logger.warning(f"策略二失敗: {e}")

    # ── 策略三：latest-versions-per-milestone（新增）──
    try:
        milestone_url = "https://googlechromelabs.github.io/chrome-for-testing/latest-versions-per-milestone-with-downloads.json"
        logger.info(f"[milestone版] 策略三：查詢 milestone {major} 的 driver...")
        resp = requests.get(milestone_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        entry = data["milestones"][major]
        url = next((d["url"] for d in entry["downloads"].get("chromedriver", []) if d["platform"] == "win64"), None)
        if url:
            logger.info(f"策略三成功（milestone {major}），下載: {url}")
            return _extract_driver_zip(url, target_folder, local_version)
    except Exception as e:
        logger.warning(f"策略三失敗: {e}")

    # ── 策略四：本機 driver fallback ──
    local_path = os.path.join(target_folder, "chromedriver.exe")
    if os.path.exists(local_path):
        logger.info(f"✅ 使用本機 driver: {local_path}")
        return local_path

    path_driver = shutil.which("chromedriver") or shutil.which("chromedriver.exe")
    if path_driver:
        logger.info(f"✅ 使用系統 PATH driver: {path_driver}")
        return path_driver

    logger.error(
        "❌ 無法取得 ChromeDriver。\n"
        "請至 https://googlechromelabs.github.io/chrome-for-testing/ "
        "下載與您 Chrome 版本相符的 chromedriver，\n"
        "解壓縮後將 chromedriver.exe 放入程式同層的 drivers\\ 資料夾再重新執行。"
    )
    raise RuntimeError("找不到可用的 ChromeDriver")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path = download_best_chromedriver()
    print(f"Result: {path}")
