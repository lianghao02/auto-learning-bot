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

from ui_parts.shared import (
    GLOBAL_QUIZ_DIALOG_LOCK,
    SafeMarkdownBrowser,
    _DownloadProgressSignal,
    get_ui_msgbox,
    get_ui_os,
    icon,
    resource_path,
)


class UpdateDialog(QDialog):
    """兩階段更新對話框：階段一顯示版本資訊，階段二顯示下載進度與重啟"""

    def __init__(self, parent, latest: str, changelog: str, url: str, size: int, expected_sha256: str = ""):
        super().__init__(parent)
        self.latest = latest
        self.changelog = changelog
        self.url = url
        self.size = size
        self.expected_sha256 = expected_sha256
        self.downloaded_path = None  # 下載完成後的暫存檔案路徑

        from app import AdminEfficiencyPilot as _AEP
        self.current_version = _AEP.VERSION

        self.setWindowTitle("應用程式更新")
        self.setFixedWidth(460)
        self.setStyleSheet("""
            QDialog { background: #f5f7fa; }
            QLabel { color: #2c3e50; background: transparent; }
        """)

        # 外層 layout 只裝一個 _container widget
        self._outer = QVBoxLayout(self)
        self._outer.setSpacing(0)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._container = None

        self._build_stage_one()

    # ---------- 共用元件 ----------
    def _reset_container(self):
        """移除舊容器並建立新的 container widget"""
        if self._container is not None:
            self._outer.removeWidget(self._container)
            self._container.deleteLater()
            self._container = None
        self._container = QWidget(self)
        self._container.setStyleSheet("background: #f5f7fa;")
        self._outer.addWidget(self._container)
        # 強制重新計算尺寸
        self.adjustSize()
        return QVBoxLayout(self._container)

    def _make_header(self, layout):
        header = QLabel()
        header.setFixedHeight(6)
        header.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #70889B,stop:1 #5F798E);")
        layout.addWidget(header)

    def _fmt_size(self, n: int) -> str:
        if n <= 0:
            return "未知大小"
        mb = n / 1024 / 1024
        if mb >= 1:
            return f"{mb:.1f} MB"
        return f"{n / 1024:.0f} KB"

    # ---------- 階段一：版本資訊 ----------
    def _build_stage_one(self):
        layout = self._reset_container()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self._make_header(layout)

        content = QVBoxLayout()
        content.setSpacing(12)
        content.setContentsMargins(28, 24, 28, 20)

        # 標題列（圖示 + 標題）
        title_row = QHBoxLayout()
        title_row.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setStyleSheet("""
            background: #EAEFF2;
            border-radius: 8px;
            color: #5F798E;
            font-size: 22px;
            font-weight: bold;
            qproperty-alignment: AlignCenter;
        """)
        icon_lbl.setText("⬇")
        title_row.addWidget(icon_lbl)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel(f"新版本 {self.latest} 可用")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #2F3B43;")
        title_box.addWidget(title)

        size_txt = self._fmt_size(self.size) if self.size else ""
        sub = QLabel(f"將下載 {size_txt} 的更新檔，並在安裝前驗證檔案。" if size_txt
                     else "將下載新版本更新檔，並在安裝前驗證檔案。")
        sub.setStyleSheet("font-size: 11px; color: #7f8c8d;")
        sub.setWordWrap(True)
        title_box.addWidget(sub)
        title_row.addLayout(title_box, 1)

        content.addLayout(title_row)

        # 版本資訊框
        info_box = QFrame()
        info_box.setObjectName("infoBox")
        info_box.setStyleSheet("""
            QFrame#infoBox {
                background: #ffffff;
                border: 1px solid #e1e7ed;
                border-radius: 6px;
            }
            QFrame#infoBox QLabel { color: #555f6e; font-size: 12px; padding: 4px 2px; border: none; background: transparent; min-height: 18px; }
        """)
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(6)
        info_layout.addWidget(QLabel(f"目前版本：{self.current_version}"))
        info_layout.addWidget(QLabel("平台：windows-amd64"))
        content.addWidget(info_box)

        # Changelog（可選）
        if self.changelog:
            change_title = QLabel("更新內容")
            change_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #34495e; margin-top: 4px;")
            content.addWidget(change_title)
            change_body = SafeMarkdownBrowser(self)
            change_body.setMarkdown(self.changelog)
            change_body.setMinimumHeight(180)
            change_body.setMaximumHeight(320)
            change_body.setStyleSheet("""
                font-size: 11px; color: #555f6e;
                padding: 8px 12px; background: #eaf4fb;
                border-left: 3px solid #4fc3f7; border-radius: 4px;
            """)
            content.addWidget(change_body)

        # 警告框
        warn = QLabel("安裝前會驗證下載雜湊、更新包內容與版本；若驗證失敗，請至 GitHub Releases 手動下載完整 Portable ZIP。")
        warn.setStyleSheet("""
            font-size: 11px; color: #8a6d3b;
            background: #fcf3cf; border: 1px solid #f5e6a8;
            border-radius: 4px; padding: 8px 10px;
        """)
        warn.setWordWrap(True)
        content.addWidget(warn)

        # 按鈕列
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_later = QPushButton("稍後")
        btn_later.setFixedHeight(36)
        btn_later.setStyleSheet("""
            QPushButton {
                background: #ecf0f1; color: #7f8c8d;
                border-radius: 6px; padding: 0 22px; font-size: 13px;
                border: 1px solid #dce1e7;
            }
            QPushButton:hover { background: #dde3e8; }
        """)
        btn_later.clicked.connect(self.reject)

        can_auto_update = bool(self.expected_sha256) and is_portable_layout()
        btn_download = QPushButton("下載並安全更新" if can_auto_update else "開啟 GitHub Releases")
        btn_download.setFixedHeight(36)
        btn_download.setStyleSheet("""
            QPushButton {
                background: #5F798E; color: #fff; font-weight: bold;
                border-radius: 6px; padding: 0 22px; font-size: 13px;
                border: none;
            }
            QPushButton:hover { background: #4D6477; }
        """)
        if can_auto_update:
            btn_download.clicked.connect(self._start_download)
        else:
            btn_download.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.url)))

        btn_row.addStretch()
        btn_row.addWidget(btn_later)
        btn_row.addWidget(btn_download)
        content.addLayout(btn_row)
        layout.addLayout(content)

    # ---------- 階段二：下載中 / 完成 ----------
    def _build_stage_two(self, done: bool = False):
        layout = self._reset_container()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self._make_header(layout)

        content = QVBoxLayout()
        content.setSpacing(12)
        content.setContentsMargins(28, 24, 28, 20)

        # 標題列
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(40, 40)
        if done:
            icon_lbl.setText("✓")
            icon_lbl.setStyleSheet("""
                background: #e8f5e9; border-radius: 8px;
                color: #2e7d32; font-size: 22px; font-weight: bold;
                qproperty-alignment: AlignCenter;
            """)
        else:
            icon_lbl.setText("⬇")
            icon_lbl.setStyleSheet("""
                background: #e3f2fd; border-radius: 8px;
                color: #0288d1; font-size: 22px; font-weight: bold;
                qproperty-alignment: AlignCenter;
            """)
        title_row.addWidget(icon_lbl)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        if done:
            title = QLabel("更新已準備完成")
            title.setStyleSheet("font-size: 16px; font-weight: bold; color: #2e7d32;")
            sub = QLabel(f"重新啟動後會替換目前版本並開啟新版 {self.latest}。")
        else:
            title = QLabel(f"正在下載 {self.latest}")
            title.setStyleSheet("font-size: 16px; font-weight: bold; color: #0277bd;")
            sub = QLabel("下載完成前請勿關閉視窗。")
        sub.setStyleSheet("font-size: 11px; color: #7f8c8d;")
        sub.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(sub)
        title_row.addLayout(title_box, 1)
        content.addLayout(title_row)

        # 進度條
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        if done:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
        else:
            self.progress_bar.setRange(0, max(self.size, 1))
            self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: #e1e7ed; border: none; border-radius: 5px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4fc3f7,stop:1 #0288d1);
                border-radius: 5px;
            }
        """)
        content.addWidget(self.progress_bar)

        # 進度文字
        self.progress_label = QLabel("0 MB / " + self._fmt_size(self.size) + "    0%")
        if done:
            self.progress_label.setText(f"{self._fmt_size(self.size)}    100%")
        self.progress_label.setStyleSheet("font-size: 11px; color: #7f8c8d;")
        content.addWidget(self.progress_label)

        # 版本資訊框
        info_box = QFrame()
        info_box.setObjectName("infoBox")
        info_box.setStyleSheet("""
            QFrame#infoBox { background: #ffffff; border: 1px solid #e1e7ed; border-radius: 6px; }
            QFrame#infoBox QLabel { color: #555f6e; font-size: 12px; padding: 4px 2px; border: none; background: transparent; min-height: 18px; }
        """)
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(6)
        info_layout.addWidget(QLabel(f"目前版本：{self.current_version}"))
        info_layout.addWidget(QLabel("平台：windows-amd64"))
        content.addWidget(info_box)

        # 警告框
        warn = QLabel("自動更新功能仍屬於「實驗性」功能，若自動更新失敗，請至 GitHub Releases 手動下載。")
        warn.setStyleSheet("""
            font-size: 11px; color: #8a6d3b;
            background: #fcf3cf; border: 1px solid #f5e6a8;
            border-radius: 4px; padding: 8px 10px;
        """)
        warn.setWordWrap(True)
        content.addWidget(warn)

        # 按鈕列
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_later = QPushButton("稍後")
        btn_later.setFixedHeight(36)
        btn_later.setStyleSheet("""
            QPushButton {
                background: #ecf0f1; color: #7f8c8d;
                border-radius: 6px; padding: 0 22px; font-size: 13px;
                border: 1px solid #dce1e7;
            }
            QPushButton:hover { background: #dde3e8; }
        """)
        btn_later.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(btn_later)

        if done:
            btn_install = QPushButton("重新啟動安裝")
            btn_install.setFixedHeight(36)
            btn_install.setStyleSheet("""
                QPushButton {
                    background: #2e7d32; color: #fff; font-weight: bold;
                    border-radius: 6px; padding: 0 22px; font-size: 13px;
                    border: none;
                }
                QPushButton:hover { background: #1b5e20; }
            """)
            btn_install.clicked.connect(self._install_and_restart)
            btn_row.addWidget(btn_install)
        content.addLayout(btn_row)
        layout.addLayout(content)

    # ---------- 下載邏輯 ----------
    def _start_download(self):
        import tempfile, os
        if not is_portable_layout():
            get_ui_msgbox().warning(
                self, "無法自動更新",
                "自動更新僅支援新版 Portable 目錄結構，請至 GitHub Releases 手動下載。"
            )
            return
        if not self.expected_sha256:
            get_ui_msgbox().warning(self, "缺少完整性摘要", "此 Release 未提供 SHA-256 digest，禁止自動安裝。")
            return

        self._build_stage_two(done=False)

        # 暫存檔案路徑
        tmp_dir = tempfile.gettempdir()
        self.downloaded_path = os.path.join(tmp_dir, f"AdminEfficiencyPilot_{self.latest}_Portable.zip")

        # 訊號
        self._dl_signal = _DownloadProgressSignal()
        self._dl_signal.progress.connect(self._on_progress)
        self._dl_signal.finished.connect(self._on_finished)
        self._dl_signal.failed.connect(self._on_failed)

        # 背景下載
        threading.Thread(target=self._download_worker, daemon=True).start()

    def _download_worker(self):
        import requests as _req
        try:
            with _req.get(self.url, stream=True, timeout=30, allow_redirects=True) as r:
                if r.status_code != 200:
                    self._dl_signal.failed.emit(f"HTTP {r.status_code}")
                    return
                total = int(r.headers.get("Content-Length", self.size or 0))
                downloaded = 0
                with open(self.downloaded_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        self._dl_signal.progress.emit(downloaded, total)

            if self.expected_sha256:
                if not verify_file_sha256(self.downloaded_path, self.expected_sha256):
                    try:
                        if os.path.exists(self.downloaded_path):
                            os.remove(self.downloaded_path)
                    except Exception:
                        pass
                    self._dl_signal.failed.emit("下載檔案 SHA-256 完整性校驗失敗，檔案可能已受損或遭竄改，已終止更新。")
                    return

            self._dl_signal.finished.emit(self.downloaded_path)
        except Exception as e:
            self._dl_signal.failed.emit(str(e))

    def _on_progress(self, downloaded: int, total: int):
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(downloaded)
            pct = int(downloaded / total * 100)
        else:
            pct = 0
        self.progress_label.setText(
            f"{self._fmt_size(downloaded)} / {self._fmt_size(total)}    {pct}%"
        )

    def _on_finished(self, path: str):
        self.downloaded_path = path
        self._build_stage_two(done=True)

    def _on_failed(self, msg: str):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        RELEASES_URL = "https://github.com/lianghao02/auto-learning-bot/releases/latest"

        fail_dlg = QDialog(self)
        fail_dlg.setWindowTitle("自動下載失敗")
        fail_dlg.setFixedWidth(440)
        fail_dlg.setStyleSheet("""
            QDialog { background: #f5f7fa; }
            QLabel { color: #2c3e50; background: transparent; }
        """)
        f_outer = QVBoxLayout(fail_dlg)
        f_outer.setSpacing(0)
        f_outer.setContentsMargins(0, 0, 0, 0)

        # 紅色頂部色帶
        f_header = QLabel()
        f_header.setFixedHeight(6)
        f_header.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ef5350,stop:1 #c62828);")
        f_outer.addWidget(f_header)

        body = QVBoxLayout()
        body.setSpacing(12)
        body.setContentsMargins(28, 22, 28, 18)

        # 標題列
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        ico = QLabel("⚠")
        ico.setFixedSize(40, 40)
        ico.setStyleSheet("""
            background: #ffebee; border-radius: 8px;
            color: #c62828; font-size: 22px; font-weight: bold;
            qproperty-alignment: AlignCenter;
        """)
        title_row.addWidget(ico)

        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        ttl = QLabel("自動下載失敗")
        ttl.setStyleSheet("font-size: 16px; font-weight: bold; color: #c62828;")
        sub = QLabel(f"錯誤：{msg}")
        sub.setStyleSheet("font-size: 11px; color: #7f8c8d;")
        sub.setWordWrap(True)
        tbox.addWidget(ttl)
        tbox.addWidget(sub)
        title_row.addLayout(tbox, 1)
        body.addLayout(title_row)

        # 指引文字
        guide = QLabel(
            "請前往 GitHub Releases 下載最新版 <b>Portable ZIP</b>，完整解壓至新資料夾；"
            "不要以單檔覆蓋目前正在使用的程式目錄。"
        )
        guide.setStyleSheet("""
            font-size: 12px; color: #555f6e;
            padding: 10px 12px; background: #ffffff;
            border: 1px solid #e1e7ed; border-radius: 6px;
        """)
        guide.setWordWrap(True)
        guide.setTextFormat(Qt.RichText)
        body.addWidget(guide)

        # 按鈕列
        b_row = QHBoxLayout()
        b_row.setSpacing(10)

        btn_close = QPushButton("關閉")
        btn_close.setFixedHeight(36)
        btn_close.setStyleSheet("""
            QPushButton {
                background: #ecf0f1; color: #7f8c8d;
                border-radius: 6px; padding: 0 22px; font-size: 13px;
                border: 1px solid #dce1e7;
            }
            QPushButton:hover { background: #dde3e8; }
        """)
        btn_close.clicked.connect(fail_dlg.reject)

        btn_open = QPushButton("開啟下載頁面")
        btn_open.setFixedHeight(36)
        btn_open.setStyleSheet("""
            QPushButton {
                background: #0288d1; color: #fff; font-weight: bold;
                border-radius: 6px; padding: 0 22px; font-size: 13px;
                border: none;
            }
            QPushButton:hover { background: #0277bd; }
        """)
        btn_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        btn_open.clicked.connect(fail_dlg.accept)

        b_row.addStretch()
        b_row.addWidget(btn_close)
        b_row.addWidget(btn_open)
        body.addLayout(b_row)

        f_outer.addLayout(body)
        fail_dlg.exec()
        self.reject()

    # ---------- 安裝（Portable staging 切換並重啟）----------
    def _install_and_restart(self):
        import shutil
        import subprocess

        if not self.downloaded_path or not os.path.exists(self.downloaded_path):
            self._on_failed("找不到已下載的更新檔（可能被防毒軟體刪除）")
            return
        try:
            staging_dir, staged_current = stage_portable_zip(
                self.downloaded_path,
                install_root(),
                self.latest,
            )
        except Exception as e:
            self._on_failed(f"更新包 staging 驗證失敗：{e}")
            return

        updater = install_root() / "auto_update.ps1"
        if not updater.is_file():
            shutil.rmtree(staging_dir, ignore_errors=True)
            self._on_failed("安裝目錄缺少 auto_update.ps1，請手動下載完整 Portable ZIP。")
            return
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    str(updater),
                    "-InstallRoot",
                    str(install_root()),
                    "-StagedCurrent",
                    str(staged_current),
                    "-ArchivePath",
                    str(self.downloaded_path),
                    "-MainPid",
                    str(os.getpid()),
                ],
                creationflags=0x00000200,
                startupinfo=si,
                close_fds=True,
            )
        except Exception as e:
            shutil.rmtree(staging_dir, ignore_errors=True)
            self._on_failed(f"無法啟動更新程式：{e}")
            return

        self.accept()
        QApplication.processEvents()
        QApplication.quit()
        sys.exit(0)


# =========================
# 全域人機協同排隊鎖（防範雙開模態事件循環衝突與閃退）
# =========================


# =========================
# 人機協同測驗助理彈窗
# =========================
class InteractiveQuizDialog(QDialog):
    """遇到測驗時彈出的人機協同作答助理（支援一鍵複製 Prompt、Gemini 批次極速作答、答案貼上解析與跳過自動補填問卷）"""

    gemini_batch_completed = Signal(dict)

    def __init__(self, course_name: str, questions_data: list, timeout_sec: int = 180, parent=None, config: dict = None):
        super().__init__(parent)
        self.gemini_batch_completed.connect(self._on_gemini_batch_completed)
        self.course_name = course_name
        self.questions_data = questions_data
        self.timeout_sec = timeout_sec
        self.remaining_sec = timeout_sec
        self.is_paused = False
        self.parsed_result = None
        self.config = config or {}

        if not self.config:
            try:
                from utils.app_paths import user_data_path
                import json
                cfg_path = user_data_path("config.json")
                if cfg_path.exists():
                    self.config = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                self.config = {}

        self.setWindowTitle(f"📝 測驗作答助理 - {course_name}")
        self.resize(880, 620)
        self.setModal(True)

        self.prompt_text = format_quiz_prompt(course_name, questions_data)
        self._init_ui()

        # 自動將 Prompt 複製至剪貼簿，省去點擊複製步驟
        try:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.prompt_text)
        except Exception:
            pass

        # 啟動倒數計時器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)


    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 頂部狀態列（課程名稱與倒數計時）
        top_bar = QHBoxLayout()
        title_lbl = QLabel(f"<b>課程：</b>{self.course_name}", self)
        title_lbl.setStyleSheet("font-size: 15px; color: #1E293B; font-weight: bold;")
        top_bar.addWidget(title_lbl)

        top_bar.addStretch()

        m, s = divmod(self.remaining_sec, 60)
        self.timer_lbl = QLabel(f"⏱️ 剩餘作答時間: {m:02d}:{s:02d}（上限 180 秒／03:00）", self)
        self.timer_lbl.setStyleSheet("font-size: 14px; color: #DC2626; font-weight: bold;")
        top_bar.addWidget(self.timer_lbl)
        layout.addLayout(top_bar)

        # 中間左右分割：左側 AI Prompt / 右側答案回貼
        split_layout = QHBoxLayout()
        split_layout.setSpacing(16)

        # ── 左側：AI Prompt 預覽 ──
        left_box = QVBoxLayout()
        left_title = QLabel("🤖 1. AI 提問詞（已為您自動彙整題目）", self)
        left_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #334155;")
        left_box.addWidget(left_title)

        self.prompt_preview = QTextEdit(self)
        self.prompt_preview.setPlainText(self.prompt_text)
        self.prompt_preview.setReadOnly(True)
        self.prompt_preview.setStyleSheet("""
            QTextEdit {
                background: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 8px;
                font-family: 'Cascadia Mono', 'Consolas', 'Microsoft JhengHei', monospace;
                font-size: 12px; color: #334155; padding: 10px;
            }
        """)
        left_box.addWidget(self.prompt_preview)

        self.copy_btn = QPushButton("📋 一鍵複製 AI 提問 Prompt", self)
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background: #2563EB; color: #FFFFFF; font-weight: bold; font-size: 13px;
                padding: 10px 16px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background: #1D4ED8; }
            QPushButton:pressed { background: #1E40AF; }
        """)
        self.copy_btn.clicked.connect(self._copy_prompt)
        left_box.addWidget(self.copy_btn)

        # 🌐 AI 平台快速捷徑按鈕列
        ai_btn_row = QHBoxLayout()
        ai_btn_row.setSpacing(10)

        self.chatgpt_btn = QPushButton("🌐 開啟 ChatGPT", self)
        self.chatgpt_btn.setToolTip("點此使用預設瀏覽器開啟 ChatGPT (chatgpt.com)")
        self.chatgpt_btn.setStyleSheet("""
            QPushButton {
                background: #10A37F; color: #FFFFFF; font-weight: bold; font-size: 12px;
                padding: 8px 12px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background: #0E8A6C; }
            QPushButton:pressed { background: #0B6E56; }
        """)
        self.chatgpt_btn.clicked.connect(self._open_chatgpt)

        self.gemini_btn = QPushButton("✨ 開啟 Gemini", self)
        self.gemini_btn.setToolTip("點此使用預設瀏覽器開啟 Google Gemini (gemini.google.com)")
        self.gemini_btn.setStyleSheet("""
            QPushButton {
                background: #4E7BE8; color: #FFFFFF; font-weight: bold; font-size: 12px;
                padding: 8px 12px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background: #3B66D1; }
            QPushButton:pressed { background: #2F52AB; }
        """)
        self.gemini_btn.clicked.connect(self._open_gemini)

        ai_btn_row.addWidget(self.chatgpt_btn)
        ai_btn_row.addWidget(self.gemini_btn)
        left_box.addLayout(ai_btn_row)

        split_layout.addLayout(left_box, 1)

        # 右側欄位
        right_box = QFrame()
        right_box.setStyleSheet("background: #F9FAFB; border: 1px solid #E5E7EB; border-radius: 8px; padding: 10px;")
        right_layout = QVBoxLayout(right_box)
        right_lbl = QLabel("📥 答案回貼區（貼上 ChatGPT / Gemini 回覆的內容）")
        right_lbl.setStyleSheet("font-weight: bold; color: #374151; font-size: 13px;")

        self.answer_input = QTextEdit()
        self.answer_input.setAcceptRichText(False)  # 🔒 強制純文字貼上，防止 HTML/富文本標籤干擾解析
        self.answer_input.setPlaceholderText("請在此貼上 AI 回覆的內容（支援直接 Ctrl+V）...\n例如：\n1. B\n2. ⭕\n3. 以上皆是\n4. A, B, C")
        self.answer_input.setStyleSheet("""
            QTextEdit {
                background: #FFFFFF; border: 1px solid #D1D5DB; border-radius: 6px;
                font-family: 'Consolas', 'Microsoft JhengHei', monospace; font-size: 13px;
                color: #111827; padding: 8px;
            }
        """)
        self.answer_input.textChanged.connect(self._on_answer_text_changed)

        self.paste_btn = QPushButton("📋 從剪貼簿直接貼上")
        self.paste_btn.setStyleSheet("""
            QPushButton {
                background: #8B5CF6; color: #FFFFFF; font-weight: bold; font-size: 13px;
                padding: 10px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background: #7C3AED; }
        """)
        self.paste_btn.clicked.connect(self._paste_from_clipboard)

        # 即時解析狀態反饋標籤
        self.parse_status_lbl = QLabel("💡 請直接貼上 AI 回覆內容（支援直接 Ctrl+V）")
        self.parse_status_lbl.setStyleSheet("color: #6B7280; font-size: 12px; padding: 2px;")
        self.parse_status_lbl.setWordWrap(True)

        right_layout.addWidget(right_lbl)
        right_layout.addWidget(self.answer_input)
        right_layout.addWidget(self.paste_btn)
        right_layout.addWidget(self.parse_status_lbl)
        split_layout.addWidget(right_box, 1)

        layout.addLayout(split_layout)

        # 底部操作列
        bottom_bar = QHBoxLayout()
        self.gemini_batch_btn = QPushButton("✨ Gemini 1 秒智慧作答", self)
        self.gemini_batch_btn.setToolTip("使用 Google Gemini API 批次解析整份考卷並自動填入")
        self.gemini_batch_btn.setStyleSheet("""
            QPushButton {
                background: #4F46E5; color: #FFFFFF; font-weight: bold; font-size: 13px;
                padding: 10px 18px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background: #4338CA; }
            QPushButton:disabled { background: #9CA3AF; color: #E5E7EB; }
        """)
        self.gemini_batch_btn.clicked.connect(self._run_gemini_batch_solve)

        self.submit_btn = QPushButton("🚀 解析並自動填入考卷")
        self.submit_btn.setStyleSheet("""
            QPushButton {
                background: #10B981; color: #FFFFFF; font-weight: bold; font-size: 14px;
                padding: 10px 20px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background: #059669; }
            QPushButton:disabled { background: #A7F3D0; color: #065F46; }
        """)
        self.submit_btn.clicked.connect(self._submit)

        self.pause_btn = QPushButton("⏸️ 暫停倒數")
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background: #F59E0B; color: #FFFFFF; font-weight: bold; font-size: 13px;
                padding: 10px 14px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background: #D97706; }
        """)
        self.pause_btn.clicked.connect(self._toggle_pause)

        self.skip_btn = QPushButton("⏭️ 立即跳過測驗")
        self.skip_btn.setToolTip("跳過測驗並自動為您檢查與填寫課程問卷")
        self.skip_btn.setStyleSheet("""
            QPushButton {
                background: #6B7280; color: #FFFFFF; font-weight: bold; font-size: 13px;
                padding: 10px 14px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background: #4B5563; }
        """)
        self.skip_btn.clicked.connect(self._skip)

        bottom_bar.addWidget(self.gemini_batch_btn)
        bottom_bar.addWidget(self.submit_btn)
        bottom_bar.addWidget(self.pause_btn)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.skip_btn)
        layout.addLayout(bottom_bar)

    def _run_gemini_batch_solve(self):
        settings = self.config.get("settings", {}) if self.config else {}
        provider = settings.get("ai_provider", "Gemini")
        ai_keys = settings.get("ai_keys", {}) or {}
        api_key = (ai_keys.get(provider) or settings.get("ai_api_key", "")).strip()

        if not api_key:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("🔑 尚未設定 API Key")
            msg_box.setText("您尚未在系統設定中填入 Gemini API Key。\n\n• Google AI Studio 提供免費 Key（Free Tier 免費層配額，免綁信用卡）。\n• 是否前往 Google AI Studio 網站免費申請？\n\n※ 實際免費配額以 Google 官方公告為準。")
            msg_box.setIcon(QMessageBox.Information)
            open_btn = msg_box.addButton("🔗 前往申請 (Google AI Studio)", QMessageBox.ActionRole)
            cancel_btn = msg_box.addButton("稍後設定", QMessageBox.RejectRole)
            msg_box.exec()
            if msg_box.clickedButton() == open_btn:
                self._open_url_native("https://aistudio.google.com/app/apikey")
            return

        self.is_paused = True
        self.gemini_batch_btn.setEnabled(False)
        self.gemini_batch_btn.setText("⚡ 正在請求 Gemini 批次作答...")
        self.parse_status_lbl.setText("⚡ 正在連線 Gemini 批次分析考卷，請稍候約 1~2 秒...")
        self.parse_status_lbl.setStyleSheet("color: #4F46E5; font-size: 12px; font-weight: bold; padding: 2px;")


        import threading
        def _worker():
            from quiz_bank import ai_batch_solve_quiz
            res = ai_batch_solve_quiz(self.course_name, self.questions_data, settings)
            self.gemini_batch_completed.emit(res)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_gemini_batch_completed(self, res: dict):
        self.gemini_batch_btn.setEnabled(True)
        self.gemini_batch_btn.setText("✨ Gemini 1 秒智慧作答")
        self.is_paused = False

        if res.get("success") and res.get("answers"):
            answers_dict = res["answers"]
            lines = [f"{k}. {v}" for k, v in sorted(answers_dict.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 999)]
            formatted_text = "\n".join(lines)
            self.answer_input.setPlainText(formatted_text)
            self.parse_status_lbl.setText(f"✅ Gemini 批次智慧作答完成！成功辨識 {len(answers_dict)} 題，正在自動送出...")
            self.parse_status_lbl.setStyleSheet("color: #059669; font-size: 12px; font-weight: bold; padding: 2px;")
            QTimer.singleShot(500, self._submit)
        else:
            err = res.get("error", "未知錯誤")
            self.parse_status_lbl.setText(f"❌ {err}（可改用手動複製貼上）")
            self.parse_status_lbl.setStyleSheet("color: #DC2626; font-size: 12px; font-weight: bold; padding: 2px;")

    def _tick(self):
        if self.is_paused:
            return
        self.remaining_sec -= 1
        if self.remaining_sec > 0:
            m, s = divmod(self.remaining_sec, 60)
            self.timer_lbl.setText(f"⏱️ 剩餘作答時間: {m:02d}:{s:02d}（上限 180 秒／03:00）")
        else:
            self.timer.stop()
            self.timer_lbl.setText("⏱️ 已逾時（180 秒已到），等待決策...")

            # 彈出明確決策對話框，取消隱性自動跳過
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("⏱️ 作答逾時提示")
            msg_box.setText(f"【{self.course_name}】測驗助理已達 180 秒倒數上限。\n\n請選擇後續處理方式：")
            msg_box.setIcon(QMessageBox.Question)

            retry_btn = msg_box.addButton("🔄 重新計時 180 秒", QMessageBox.ActionRole)
            skip_btn = msg_box.addButton("⏩ 跳過此測驗並填寫問卷", QMessageBox.ActionRole)
            stop_btn = msg_box.addButton("🛑 結束本次執行", QMessageBox.DestructiveRole)

            msg_box.exec()
            clicked = msg_box.clickedButton()

            if clicked == retry_btn:
                self.remaining_sec = self.timeout_sec
                self.is_paused = False
                self.pause_btn.setText("⏸️ 暫停倒數")
                m, s = divmod(self.remaining_sec, 60)
                self.timer_lbl.setText(f"⏱️ 剩餘作答時間: {m:02d}:{s:02d}（上限 180 秒／03:00）")
                self.timer.start(1000)
            elif clicked == stop_btn:
                self.parsed_result = "STOP_ALL"
                self.reject()
            else:
                self.parsed_result = "SKIP"
                self.reject()

    def _copy_prompt(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.prompt_text)
        self.copy_btn.setText("✅ 已複製至剪貼簿！")
        QTimer.singleShot(2000, lambda: self.copy_btn.setText("📋 一鍵複製 AI 提問 Prompt"))

    def _open_url_native(self, url: str):
        """使用系統原生機制與雙層備援開啟網頁，確保在 Windows 各種環境下 100% 成功喚起預設瀏覽器"""
        try:
            import webbrowser
            webbrowser.open_new_tab(url)
        except Exception:
            try:
                import os
                get_ui_os().startfile(url)
            except Exception:
                try:
                    QDesktopServices.openUrl(QUrl(url))
                except Exception:
                    pass

    def _open_chatgpt(self):
        self._open_url_native("https://chatgpt.com/")

    def _open_gemini(self):
        self._open_url_native("https://gemini.google.com/")

    def _on_answer_text_changed(self):
        raw = self.answer_input.toPlainText().strip()
        if not raw:
            self.parse_status_lbl.setText("💡 請直接貼上 AI 回覆內容（支援直接 Ctrl+V）")
            self.parse_status_lbl.setStyleSheet("color: #6B7280; font-size: 12px; padding: 2px;")
            return
        parsed = parse_ai_quiz_answers(raw, self.questions_data)
        total_q = len(self.questions_data)
        if parsed:
            summary_items = []
            for k, v in sorted(parsed.items()):
                summary_items.append(f"{k}. {','.join(v)}")
            summary_str = "、".join(summary_items[:6])
            if len(summary_items) > 6:
                summary_str += "..."
            self.parse_status_lbl.setText(f"✅ 已成功辨識 {len(parsed)}/{total_q} 題解答：{summary_str}")
            self.parse_status_lbl.setStyleSheet("color: #059669; font-size: 12px; font-weight: bold; padding: 2px;")
        else:
            self.parse_status_lbl.setText("⚠️ 尚未辨識出答案代號，請確認格式包含題號（如 1. B 或 1. ⭕）")
            self.parse_status_lbl.setStyleSheet("color: #D97706; font-size: 12px; padding: 2px;")

    def _paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        self.answer_input.setPlainText(clipboard.text())

    def _toggle_pause(self):
        self.is_paused = not self.is_paused
        m, s = divmod(self.remaining_sec, 60)
        if self.is_paused:
            self.pause_btn.setText("▶️ 繼續倒數")
            self.timer_lbl.setText(f"⏸️ 倒數已暫停（剩餘 {m:02d}:{s:02d}）")
        else:
            self.pause_btn.setText("⏸️ 暫停倒數")
            self.timer_lbl.setText(f"⏱️ 剩餘作答時間: {m:02d}:{s:02d}（上限 180 秒／03:00）")

    def _submit(self):
        raw = self.answer_input.toPlainText().strip()
        if not raw:
            get_ui_msgbox().warning(self, "提示", "請先在右側回貼區貼上 AI 回覆的答案！")
            return
        parsed = parse_ai_quiz_answers(raw, self.questions_data)
        if not parsed:
            get_ui_msgbox().warning(
                self, "解析提示", "未能從貼上的內容中辨識出題號與選項代號，請檢查格式是否包含題號（如 1. B, 2. ⭕ 等）！"
            )
            return
        self.parsed_result = parsed
        self.timer.stop()
        self.accept()

    def _skip(self):
        self.parsed_result = "SKIP"
        self.timer.stop()
        self.reject()

