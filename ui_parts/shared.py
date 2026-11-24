from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from utils.app_paths import (
    app_dir,
    install_root,
    is_portable_layout,
    log_path,
    prepare_user_data,
    update_cache_path,
    user_data_path,
)
from utils.config_io import write_json_atomically
from utils.helpers import (
    INTERACTIVE_QUIZ_TIMEOUT_SECONDS,
    format_quiz_prompt,
    get_logger,
    parse_ai_quiz_answers,
)
from utils.log_feed import FILTERS as LOG_FILTERS, LogFeed, matches_filter as log_matches_filter
from utils.office_theme import (
    INK as THEME_INK,
    ROW_COLORS,
    apply_office_theme,
    assistant_label,
    button_qss,
    render_log_entry,
)
from utils.portable_update import stage_portable_zip
from utils.security import validate_ai_base_url, verify_file_sha256

LOG_MAX_ENTRIES = 1500


BASE_DIR = str(app_dir())
CONFIG_PATH = str(user_data_path("config.json"))

logger = get_logger()


def icon(name):
    return QIcon(resource_path(f"icons/{name}"))


def resource_path(relative_path):
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(BASE_DIR, relative_path)


def version_tuple(version):
    nums = re.findall(r"\d+", str(version or ""))
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def is_newer_version(latest, current):
    return version_tuple(latest) > version_tuple(current)


def parse_release_update(data: dict, current_version: str):
    """解析 GitHub latest release，精確選取同版本 Portable ZIP。"""
    latest = str(data.get("tag_name") or "").strip()
    if not latest.upper().startswith("V") or not is_newer_version(latest, current_version):
        return None
    changelog = str(data.get("body") or "").strip()
    release_url = str(
        data.get("html_url")
        or "https://github.com/lianghao02/auto-learning-bot/releases/latest"
    )
    expected_name = f"AdminEfficiencyPilot_{latest.upper()}_Portable.zip".casefold()
    asset = next(
        (
            item
            for item in (data.get("assets") or [])
            if str(item.get("name") or "").casefold() == expected_name
        ),
        None,
    )
    if not asset:
        return latest, changelog, release_url, 0, ""
    digest = str(asset.get("digest") or "")
    digest_value = digest.split(":", 1)[-1]
    if (
        not digest.lower().startswith("sha256:")
        or len(digest_value) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in digest_value)
    ):
        return latest, changelog, release_url, int(asset.get("size", 0) or 0), ""
    return (
        latest,
        changelog,
        str(asset.get("browser_download_url") or release_url),
        int(asset.get("size", 0) or 0),
        digest,
    )


def looks_like_legacy_taipei_account(account):
    """辨識舊設定中被誤標為 egov 的臺北E大帳號，僅供 UI 遷移使用。"""
    if not isinstance(account, dict):
        return False
    if account.get("login_type") == "taipei_eda":
        return True
    name = re.sub(r"[\s_-]+", "", str(account.get("name", ""))).lower()
    return name == "e大" or "taipei" in name or "臺北" in name or "台北" in name





# =========================
# 全域樣式（莫蘭迪視覺系統基準 Tokens）
# =========================
GLOBAL_QSS = """
QWidget {
    background-color: transparent;
    color: #2F3B43;
    font-family: "Microsoft JhengHei UI", "Microsoft JhengHei", "Segoe UI", sans-serif;
}
#card {
    background-color: #FAF9F6;
    border-radius: 12px;
    border: 1px solid #D6D3CC;
    padding: 14px;
}
QPushButton {
    background-color: #E8E5DF;
    color: #2F3B43;
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 13px;
    font-weight: 600;
    text-align: center;
    border: 1px solid #C9C5BE;
}
QPushButton:hover {
    background-color: #DCD8D0;
    border: 1px solid #B5B0A8;
}
QPushButton:pressed {
    background-color: #CFCAC0;
    border: 1px solid #9E9990;
}
QPushButton:disabled {
    background-color: #E4E0DA;
    color: #8A8782;
    border: 1px solid #D4D0C8;
}
QPushButton#ghost {
    background-color: transparent;
    border: 1px solid #D6D3CC;
    color: #55626D;
    border-radius: 8px;
    padding: 6px 12px;
}
QPushButton#ghost:hover {
    border: 1px solid #B9B5AE;
    color: #2F3B43;
}
QComboBox {
    background-color: #F3F1ED;
    border: 1px solid #B9B5AE;
    border-radius: 6px;
    padding: 6px 10px;
    color: #2F3B43;
}
"""


def style_btn(btn):
    btn.setStyleSheet("""
        background-color: rgba(255,255,255,0.25);
        border-radius: 14px;
        padding: 14px;
        font-size: 15px;
        font-family: "Noto Sans TC Rounded", "Microsoft JhengHei";
    """)


def add_hover_effect(btn):
    # ===== 陰影（柔和常態）
    shadow = QGraphicsDropShadowEffect(btn)
    shadow.setBlurRadius(20)
    shadow.setOffset(0, 4)
    shadow.setColor(QColor(0, 0, 0, 25))
    btn.shadow = shadow
    btn.setGraphicsEffect(shadow)

    orig_enter = getattr(btn, "enterEvent", None)
    orig_leave = getattr(btn, "leaveEvent", None)

    def enterEvent(event):
        btn.shadow.setBlurRadius(32)
        btn.shadow.setOffset(0, 8)
        btn.shadow.setColor(QColor(0, 0, 0, 55))
        if orig_enter:
            orig_enter(event)

    def leaveEvent(event):
        btn.shadow.setBlurRadius(20)
        btn.shadow.setOffset(0, 4)
        btn.shadow.setColor(QColor(0, 0, 0, 25))
        if orig_leave:
            orig_leave(event)

    btn.enterEvent = enterEvent
    btn.leaveEvent = leaveEvent


# =========================
# 設定與資料存取輔助函式
# =========================
def load_config_data() -> dict:
    """讀取 config.json 設定檔，若不存在或損壞則回傳預設結構"""
    path = get_config_path()
    if not os.path.exists(path):
        data = {"accounts": [], "settings": {}}
        write_json_atomically(path, data)
        return data
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {"accounts": [], "settings": {}}
            return json.loads(content)
    except Exception as e:
        logger.error(f"讀取設定檔失敗: {e}")
        return {"accounts": [], "settings": {}}


def save_config_data(data: dict) -> bool:
    """原子寫入 config.json 設定檔"""
    try:
        write_json_atomically(get_config_path(), data)
        return True
    except (OSError, IOError) as e:
        logger.error(f"設定儲存失敗: {e}")
        return False


# =========================
# 版本更新通知 Signal
# =========================
from PySide6.QtCore import QObject

class UpdateSignal(QObject):
    # (latest_version, changelog, download_url, file_size_bytes, sha256_digest)
    notify = Signal(str, str, str, int, str)
    up_to_date = Signal()           # 已是最新版
    failed = Signal(str)            # 檢查失敗或網路異常

    def emit(self, version, changelog, url, size=0, digest=""):
        self.notify.emit(version, changelog, url, size, digest)


class UsageSignal(QObject):
    online = Signal(int)


class _DownloadProgressSignal(QObject):
    """下載進度訊號 (downloaded_bytes, total_bytes)"""
    progress = Signal(int, int)
    finished = Signal(str)   # 下載完成，帶完成檔案路徑
    failed = Signal(str)     # 失敗，帶錯誤訊息


class SafeMarkdownBrowser(QTextBrowser):
    """不自動載入遠端資源，外部連結須經使用者確認。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._confirm_external_link)

    def loadResource(self, resource_type, name):
        if isinstance(name, QUrl) and name.scheme().lower() in {"http", "https", "file"}:
            return None
        return super().loadResource(resource_type, name)

    def _confirm_external_link(self, url: QUrl):
        if url.scheme().lower() not in {"https", "http"}:
            return
        answer = QMessageBox.question(
            self,
            "開啟外部連結",
            f"是否以預設瀏覽器開啟？\n{url.toString()}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            QDesktopServices.openUrl(url)



DEFAULT_CONFIG_PATH = CONFIG_PATH
GLOBAL_QUIZ_DIALOG_LOCK = threading.Lock()


def get_config_path() -> str:
    ui_mod = sys.modules.get("ui")
    return str(getattr(ui_mod, "CONFIG_PATH", DEFAULT_CONFIG_PATH))


def get_ui_os():
    ui_mod = sys.modules.get("ui")
    return getattr(ui_mod, "os", os)


def get_ui_msgbox():
    ui_mod = sys.modules.get("ui")
    return getattr(ui_mod, "QMessageBox", QMessageBox)
