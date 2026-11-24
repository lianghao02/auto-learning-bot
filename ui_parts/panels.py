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

from ui_parts.dialogs import InteractiveQuizDialog
from ui_parts.shared import (
    GLOBAL_QUIZ_DIALOG_LOCK,
    LOG_MAX_ENTRIES,
    get_config_path,
    get_ui_msgbox,
    get_ui_os,
    icon,
    looks_like_legacy_taipei_account,
    resource_path,
)

logger = get_logger()


class PlatformTabPanel(QWidget):
    log_signal = Signal(str)
    quiz_interactive_signal = Signal(str, list, int, object)
    course_state_signal = Signal(object)

    def __init__(self, platform_key, platform_title, on_start, on_stop, on_toggle_browser):
        super().__init__()
        self.platform_key = platform_key
        self.platform_title = platform_title
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_toggle_browser = on_toggle_browser
        self.browser_visible = False
        self._course_rows = {}  # course_id -> row_index
        self._summary_states = {}  # 僅供已載入課程的介面摘要使用

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 1. 旗艦緊湊操作儀表列 (Compact Ribbon) ─────────────────────
        ctrl_card = QFrame()
        ctrl_card.setObjectName("ctrlRibbonCard")
        ctrl_card.setStyleSheet("""
            QFrame#ctrlRibbonCard {
                background: #FAF9F6;
                border: 1px solid #D6D3CC;
                border-radius: 10px;
                padding: 6px 12px;
            }
        """)
        ctrl_layout = QVBoxLayout(ctrl_card)
        ctrl_layout.setContentsMargins(8, 6, 8, 6)
        ctrl_layout.setSpacing(6)

        # 第一排：平台資訊、狀態標籤、進度條、動作按鈕
        top_ctrl_row = QHBoxLayout()
        top_ctrl_row.setSpacing(8)

        self.info_lbl = QLabel(f"{platform_title}控制台")
        self.info_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.info_lbl.setMinimumWidth(120)
        self.info_lbl.setStyleSheet("color: #2F3B43; font-weight: 700; font-size: 14px; background: transparent; border: none;")

        self.execution_status_lbl = QLabel("● 待命")
        self.execution_status_lbl.setWordWrap(True)
        self.execution_status_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.execution_status_lbl.setStyleSheet("color: #66737D; font-size: 12px; font-weight: 700; background: transparent; border: none;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setToolTip("目前研習進度；各課程累計時數與百分比請見表格")
        self.progress_bar.setMinimumWidth(120)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #E4E0DA;
                border: 1px solid #C9C5BE;
                border-radius: 7px;
                text-align: center;
                color: #26343C;
                font-weight: bold;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #70889B, stop:1 #7F9A88);
                border-radius: 6px;
            }
        """)

        self.start_btn = QPushButton("▶️ 開始此平台")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: #6F917B; color: #FFFFFF; border-radius: 6px;
                padding: 6px 14px; font-weight: bold; font-size: 12px; border: none;
            }
            QPushButton:hover { background: #5D7D69; }
        """)
        self.start_btn.clicked.connect(self._handle_start)

        self.stop_btn = QPushButton("⏹ 停止此平台")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background: #A96F6B; color: #FFFFFF; border-radius: 6px;
                padding: 6px 14px; font-weight: bold; font-size: 12px; border: none;
            }
            QPushButton:hover { background: #925D59; }
            QPushButton:disabled { background: #DDD9D3; color: #8A8782; }
        """)
        self.stop_btn.clicked.connect(self._handle_stop)
        self.stop_btn.setEnabled(False)

        self.toggle_browser_btn = QPushButton("👁️ 顯示瀏覽器")
        self.toggle_browser_btn.setStyleSheet("""
            QPushButton {
                background: #748399; color: #FFFFFF; border-radius: 6px;
                padding: 6px 14px; font-weight: bold; font-size: 12px; border: none;
            }
            QPushButton:hover { background: #657489; }
        """)
        self.toggle_browser_btn.clicked.connect(self._handle_toggle_browser)

        self.assistant_art = assistant_label(resource_path("icons/office/office_assistant.png"))
        top_ctrl_row.addWidget(self.assistant_art)
        identity = QVBoxLayout()
        identity.setSpacing(2)
        identity.addWidget(self.info_lbl)
        identity.addWidget(self.execution_status_lbl)
        top_ctrl_row.addLayout(identity, 1)
        top_ctrl_row.addWidget(self.progress_bar, 0, Qt.AlignVCenter)
        self.total_progress_lbl = QLabel("已載入課程：0 門｜完成 0 門")
        self.total_progress_lbl.setStyleSheet("color: #514333; font-size: 12px; border: none;")
        top_ctrl_row.addWidget(self.total_progress_lbl, 0, Qt.AlignVCenter)
        ctrl_layout.addLayout(top_ctrl_row)

        # 第二排：測驗模式選擇與即時研習摘要
        bottom_ctrl_row = QHBoxLayout()
        bottom_ctrl_row.setSpacing(8)

        mode_label = QLabel("本次測驗處理方式：")
        mode_label.setStyleSheet("color: #4B5962; font-size: 12px; font-weight: 700; background: transparent; border: none;")

        self.exam_mode_combo = QComboBox()
        self.exam_mode_combo.addItem("1. 本機題庫秒殺模式（0 耗額）", "sqlite")
        self.exam_mode_combo.addItem("2. 人機協同助理（遇生題彈窗作答）", "interactive")
        self.exam_mode_combo.addItem("3. 跳過測驗（嘗試完成問卷）", "skip")
        self.exam_mode_combo.addItem("4. Gemini API 批次作答（整卷 AI 解析）", "gemini_direct")
        self.exam_mode_combo.setToolTip(
            "【測驗模式說明】僅影響本次執行：\n"
            "• 1. 本機題庫秒殺：本機題庫優先作答（0 耗額）\n"
            "• 2. 人機協同助理：遇未收錄題目彈窗提供一鍵複製 Prompt、手動回貼與 Gemini 一鍵秒答\n"
            "• 3. 跳過測驗：跳過測驗並嘗試完成滿意度問卷調查\n"
            "• 4. Gemini 批次作答：遇未收錄考卷直接背景呼叫 Gemini 3.5 Flash-Lite 批次解析（1 卷 1 次）"
        )
        self.exam_mode_combo.setMinimumWidth(200)
        self.exam_mode_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.exam_mode_combo.setStyleSheet("""
            QComboBox {
                background: #F3F1ED; color: #2F3B43;
                border: 1px solid #B9B5AE; border-radius: 6px;
                padding: 4px 26px 4px 8px; font-size: 12px; font-weight: 600;
            }
            QComboBox:hover { border-color: #70889B; background: #EBE8E3; }
            QComboBox:disabled { background: #E4E0DA; color: #88847E; }
            QComboBox QAbstractItemView {
                background: #FAF9F6; color: #2F3B43;
                selection-background-color: #70889B; selection-color: #FFFFFF;
                border: 1px solid #B9B5AE;
            }
        """)

        self.stats_lbl = QLabel("📊 研習時數：準備就緒")
        self.stats_lbl.setStyleSheet("color: #55626D; font-size: 12px; font-weight: 600; background: transparent; border: none;")

        bottom_ctrl_row.addWidget(mode_label)
        bottom_ctrl_row.addWidget(self.exam_mode_combo)
        bottom_ctrl_row.addStretch()
        bottom_ctrl_row.addWidget(self.start_btn)
        bottom_ctrl_row.addWidget(self.stop_btn)
        bottom_ctrl_row.addWidget(self.toggle_browser_btn)
        self.stats_lbl.setWordWrap(False)
        self.stats_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        ctrl_layout.addLayout(bottom_ctrl_row)
        identity.addWidget(self.stats_lbl)

        layout.addWidget(ctrl_card)

        # 保留相容性指針（避免外部程式以 hasattr 存取時失效）
        self.focus_course_lbl = QLabel()
        self.focus_badge_lbl = QLabel()
        self.focus_reason_lbl = QLabel()
        self.focus_next_lbl = QLabel()

        # ── 4. 分頁工作區：頁籤 1【課程狀態工作台】/ 頁籤 2【執行紀錄】 ──────
        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #D6D3CC;
                border-radius: 8px;
                background: #FAF9F6;
            }
            QTabBar::tab {
                background: #E8E5DF;
                color: #4A5660;
                font-weight: 700;
                font-size: 13px;
                padding: 6px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 3px;
            }
            QTabBar::tab:selected {
                background: #FAF9F6;
                color: #2F3B43;
                border: 1px solid #D6D3CC;
                border-bottom: none;
            }
        """)

        # 頁籤 1：課程狀態工作台（含空狀態／掃描狀態提示與課程佇列表格）
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(6, 6, 6, 6)
        table_layout.setSpacing(6)

        self.empty_state_lbl = QLabel(
            "📭 尚無課程資料 — 點擊上方「▶️ 開始此平台」後，系統將自動登入並掃描待研習課程清單"
        )
        self.empty_state_lbl.setAlignment(Qt.AlignCenter)
        self.empty_state_lbl.setWordWrap(True)
        self.empty_state_lbl.setStyleSheet("""
            QLabel {
                background: #F3F1ED;
                color: #55626D;
                border: 1px dashed #C9C5BE;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: 600;
            }
        """)
        table_layout.addWidget(self.empty_state_lbl)

        self.course_table = QTableWidget()
        self.course_table.setColumnCount(5)
        self.course_table.setHorizontalHeaderLabels(["課程名稱", "狀態", "研習時數", "原因", "下一步"])
        self.course_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.course_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.course_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.course_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.course_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.course_table.verticalHeader().setDefaultSectionSize(26)
        self.course_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.course_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.course_table.setStyleSheet("""
            QTableWidget {
                background: #FAF9F6;
                border: none;
                gridline-color: #E2DFD8;
                font-size: 12px;
                color: #2F3B43;
            }
            QHeaderView::section {
                background-color: #EDEAE2;
                color: #35434C;
                font-weight: 700;
                padding: 5px;
                border: 1px solid #DCD8D0;
            }
        """)
        table_layout.addWidget(self.course_table)
        self.workspace_tabs.addTab(table_container, "📋 課程任務告示板")

        # 頁籤 2：冒險日誌（篩選 + 目前研習即時卡片 + 整理後的事件流）
        self.log_feed = LogFeed(max_entries=LOG_MAX_ENTRIES)
        self.log_filter = "all"
        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(6, 6, 6, 6)
        log_layout.setSpacing(6)

        log_bar = QHBoxLayout()
        log_bar.setSpacing(4)
        self.log_filter_group = QButtonGroup(self)
        self.log_filter_group.setExclusive(True)
        self.log_filter_buttons = {}
        for key, (label, tip) in LOG_FILTERS.items():
            chip = QPushButton(label)
            chip.setObjectName("logFilterChip")
            chip.setCheckable(True)
            chip.setChecked(key == self.log_filter)
            chip.setToolTip(tip)
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, k=key: self._set_log_filter(k))
            self.log_filter_group.addButton(chip)
            self.log_filter_buttons[key] = chip
            log_bar.addWidget(chip)
        log_bar.addStretch()

        self.log_issue_btn = QPushButton("⚠ 0")
        self.log_issue_btn.setObjectName("logIssueBadge")
        self.log_issue_btn.setToolTip("本次警告與錯誤數；點擊只看重點")
        self.log_issue_btn.clicked.connect(lambda: self._set_log_filter("key"))
        self.log_issue_btn.hide()
        log_bar.addWidget(self.log_issue_btn)

        copy_btn = QPushButton("📋 複製")
        copy_btn.setToolTip("複製目前篩選中的紀錄")
        copy_btn.clicked.connect(self._copy_log_to_clipboard)
        open_dir_btn = QPushButton("📁 開啟日誌資料夾")
        open_dir_btn.clicked.connect(self._open_log_dir)
        clear_btn = QPushButton("🧹 清空")
        clear_btn.setToolTip("只清空畫面，不影響日誌檔")
        clear_btn.clicked.connect(self._clear_log_view)
        for btn in (copy_btn, open_dir_btn, clear_btn):
            btn.setObjectName("logToolButton")
            log_bar.addWidget(btn)
        log_layout.addLayout(log_bar)

        # 目前研習即時卡片：研習進度／進入單元原地更新，不再每 77 秒堆一行
        self.live_card = QFrame()
        self.live_card.setObjectName("liveCard")
        live_layout = QHBoxLayout(self.live_card)
        live_layout.setContentsMargins(10, 6, 10, 6)
        live_layout.setSpacing(10)
        self.live_icon_lbl = QLabel("⏱")
        self.live_icon_lbl.setObjectName("liveIcon")
        live_text = QVBoxLayout()
        live_text.setSpacing(0)
        self.live_course_lbl = QLabel("目前沒有研習中的課程")
        self.live_course_lbl.setObjectName("liveCourse")
        self.live_course_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.live_detail_lbl = QLabel("開始執行後，研習時數與目前單元會在這裡即時更新")
        self.live_detail_lbl.setObjectName("liveDetail")
        self.live_detail_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        live_text.addWidget(self.live_course_lbl)
        live_text.addWidget(self.live_detail_lbl)
        self.live_progress = QProgressBar()
        self.live_progress.setObjectName("liveProgress")
        self.live_progress.setRange(0, 1000)
        self.live_progress.setValue(0)
        self.live_progress.setFormat("--")
        self.live_progress.setFixedWidth(200)
        self.live_progress.setFixedHeight(18)
        live_layout.addWidget(self.live_icon_lbl)
        live_layout.addLayout(live_text, 1)
        live_layout.addWidget(self.live_progress)
        log_layout.addWidget(self.live_card)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(LOG_MAX_ENTRIES)
        log_layout.addWidget(self.log_view, 1)
        self.workspace_tabs.addTab(log_container, "📜 冒險日誌")
        layout.addWidget(self.workspace_tabs)

        self.log_signal.connect(self._append_text_safe)
        self.quiz_interactive_signal.connect(self._handle_quiz_interactive_request)
        self.course_state_signal.connect(self._handle_course_state_update)

    def _handle_quiz_interactive_request(self, course_name, questions_data, timeout_sec, holder):
        event, res_holder = holder
        try:
            # 🔒 全域排隊互斥鎖：確保雙開時同一時間僅有一個測驗助理彈窗，徹底防範 Qt 巢狀事件循環閃退
            with GLOBAL_QUIZ_DIALOG_LOCK:
                cfg = self.config if hasattr(self, 'config') and self.config else None
                dlg = InteractiveQuizDialog(course_name, questions_data, timeout_sec, parent=self, config=cfg)
                dlg.exec()
                res_holder["result"] = dlg.parsed_result

        except Exception as e:
            logger.error(f"人機協同彈窗發生異常: {e}")
            # 與使用者主動點選「跳過」區隔，避免背景流程把 UI 異常誤判為跳過指令。
            res_holder["result"] = "DIALOG_ERROR"
        finally:
            event.set()

    def prompt_quiz_interactive(self, course_name: str, questions_data: list, timeout_sec: int = INTERACTIVE_QUIZ_TIMEOUT_SECONDS):
        event = threading.Event()
        res_holder = {"result": None}
        self.quiz_interactive_signal.emit(course_name, questions_data, timeout_sec, (event, res_holder))
        # 等待使用者作答完成或對話框關閉
        event.wait()
        return res_holder["result"]

    def update_account_info(self, name: str, account: str):
        """動態更新控制台頂部的暱稱與帳號資訊"""
        display_name = name.strip() if name and name.strip() else "預設使用者"
        self.info_lbl.setText(f"{self.platform_title}｜{display_name}")
        self.info_lbl.setToolTip(f"目前使用者：{display_name}")

    def update_progress(self, current: int, total: int, status_text: str = None):
        """更新視覺化進度條與統計數字（防除零保護）"""
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        if status_text:
            self.stats_lbl.setText(f"📊 {status_text}")
        else:
            self.stats_lbl.setText(f"📊 研習進度：{current} / {total} 門課程 ({pct}%)")

    def _handle_start(self):
        self.execution_status_lbl.setText("● 正在啟動自動化流程…")
        self.execution_status_lbl.setStyleSheet(
            "color: #2563EB; font-size: 12px; font-weight: 700; background: transparent;"
        )
        if self.on_start:
            self.on_start(self.platform_key)

    def _handle_stop(self):
        if self.on_stop:
            self.on_stop(self.platform_key)

    def set_running_state(self, is_running: bool, message: str = None):
        """同步控制列可用狀態與固定摘要，避免誤按停止或重複啟動。"""
        self.start_btn.setEnabled(not is_running)
        self.stop_btn.setEnabled(is_running)
        self.exam_mode_combo.setEnabled(not is_running)
        if is_running:
            text = message or "● 執行中：請留意下方日誌與進度"
            color = "#526F5C"
            if hasattr(self, "empty_state_lbl") and self.course_table.rowCount() == 0:
                self.empty_state_lbl.setText("⏳ 正在登入並掃描課程清單，請稍候...")
                self.empty_state_lbl.show()
        else:
            text = message or "● 待命：尚未開始本次執行"
            color = "#66737D"
            if hasattr(self, "empty_state_lbl") and self.course_table.rowCount() == 0:
                self.empty_state_lbl.setText(
                    "📭 尚無課程資料 — 點擊上方「▶️ 開始此平台」後，系統將自動登入並掃描待研習課程清單"
                )
                self.empty_state_lbl.show()
        self.execution_status_lbl.setText(text)
        self.execution_status_lbl.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 700; background: transparent;"
        )

    def _handle_toggle_browser(self):
        self.browser_visible = not self.browser_visible
        if self.browser_visible:
            self.toggle_browser_btn.setText("🙈 隱藏瀏覽器")
        else:
            self.toggle_browser_btn.setText("👁️ 顯示瀏覽器")
        self.toggle_browser_btn.setStyleSheet(button_qss("browser"))
        if self.on_toggle_browser:
            self.on_toggle_browser(self.platform_key, self.browser_visible)

    def _copy_log_to_clipboard(self):
        """將目前篩選中的日誌複製至系統剪貼簿"""
        clipboard = QApplication.clipboard()
        if clipboard:
            lines = [e.plain for e in self.log_feed.entries if log_matches_filter(e, self.log_filter)]
            clipboard.setText("\n".join(lines))
            get_ui_msgbox().information(self, "複製完成", f"✅ 已複製 {len(lines)} 筆執行紀錄至剪貼簿！")

    def _open_log_dir(self):
        """開啟應用程式日誌所在的本機資料夾"""
        try:
            target_dir = str(log_path("app.log").parent)
            os.makedirs(target_dir, exist_ok=True)
            if os.path.exists(target_dir):
                get_ui_os().startfile(target_dir)
            else:
                get_ui_msgbox().warning(self, "資料夾不存在", f"找不到日誌資料夾：{target_dir}")
        except Exception as e:
            get_ui_msgbox().warning(self, "開啟失敗", f"無法開啟日誌資料夾：{e}")

    def emit_course_state(self, state):
        """提供後台線程透過信號安全更新 UI 課程狀態模型"""
        self.course_state_signal.emit(state)

    def _handle_course_state_update(self, state):
        """在主線程中更新表格行內焦點高亮 (In-Row Focus) 與狀態模型"""
        try:
            from models.course_state import CourseState, CourseStatus
            if not isinstance(state, CourseState):
                return

            if hasattr(self, "empty_state_lbl"):
                self.empty_state_lbl.hide()

            # 1. 更新相容標籤（避免外部相依失效）
            self.focus_course_lbl.setText(f"📚 目前課程：【{state.course_name}】")
            self.focus_badge_lbl.setText(state.status.badge_text)
            self.focus_reason_lbl.setText(f"💡 原因：{state.reason or '流程正常進行中'}")
            self.focus_next_lbl.setText(f"👉 下一步：{state.next_step or '等待目前步驟結束'}")

            # 2. 更新或插入課程佇列表格
            c_id = str(state.course_id or state.course_name)
            if c_id not in self._course_rows:
                row = self.course_table.rowCount()
                self.course_table.insertRow(row)
                self._course_rows[c_id] = row
            else:
                row = self._course_rows[c_id]

            # 3. 表格行內高亮 (In-Row Focus Highlight) 與異常列警示色
            is_active = (state.status in (CourseStatus.LEARNING, CourseStatus.QUIZ, CourseStatus.SURVEY))
            is_alert = (state.status in (CourseStatus.MANUAL_REVIEW, CourseStatus.ERROR) or bool(state.needs_manual))
            if is_alert:
                row_bg = QColor(ROW_COLORS["alert"])
            elif is_active:
                row_bg = QColor(ROW_COLORS["active"])
            else:
                row_bg = QColor(ROW_COLORS["even"] if row % 2 == 0 else ROW_COLORS["odd"])
            brush = QBrush(row_bg)
            text_brush = QBrush(QColor(THEME_INK))

            prefix = "▶ " if is_active else ""
            name_item = QTableWidgetItem(f"{prefix}{state.course_name}")
            name_item.setBackground(brush)
            name_item.setForeground(text_brush)
            if is_active or is_alert:
                f = name_item.font()
                f.setBold(True)
                name_item.setFont(f)
            name_item.setToolTip(f"課程名稱：{state.course_name}\n狀態：{state.status.value}\n累計：{state.formatted_study_progress}")
            self.course_table.setItem(row, 0, name_item)
            
            badge_item = QTableWidgetItem(state.status.badge_text)
            badge_item.setTextAlignment(Qt.AlignCenter)
            badge_item.setBackground(brush)
            badge_item.setForeground(QBrush(QColor(state.status.color_hex)))
            badge_font = badge_item.font()
            badge_font.setBold(True)
            badge_item.setFont(badge_font)
            self.course_table.setItem(row, 1, badge_item)

            time_item = QTableWidgetItem(state.formatted_study_progress)
            time_item.setTextAlignment(Qt.AlignCenter)
            time_item.setBackground(brush)
            time_item.setForeground(text_brush)
            self.course_table.setItem(row, 2, time_item)

            reason_str = state.reason or "-"
            reason_item = QTableWidgetItem(reason_str)
            reason_item.setBackground(brush)
            reason_item.setForeground(text_brush)
            reason_item.setToolTip(f"原因：{reason_str}")
            self.course_table.setItem(row, 3, reason_item)

            next_str = state.next_step or "-"
            next_item = QTableWidgetItem(next_str)
            next_item.setBackground(brush)
            next_item.setForeground(text_brush)
            next_item.setToolTip(f"下一步：{next_str}")
            self.course_table.setItem(row, 4, next_item)

            # 已載入課程摘要，不推測未掃描課程，也不回寫業務模型。
            self._summary_states[c_id] = state.status
            total = len(self._summary_states)
            completed = sum(status == CourseStatus.COMPLETED for status in self._summary_states.values())
            self.total_progress_lbl.setText(f"已載入課程：{total} 門｜完成 {completed} 門（{round(completed * 100 / total)}%）")

            # 4. 同步頂部狀態列摘要
            if is_active:
                self.stats_lbl.setText(f"📚 目前課程：{state.course_name} ({state.formatted_study_progress})")
                if state.progress_pct > 0:
                    self.progress_bar.setValue(int(state.progress_pct))

            elif state.status == CourseStatus.COMPLETED:
                self.stats_lbl.setText(f"✅ 已完成：{state.course_name}")
        except Exception as e:
            logger.debug(f"更新課程狀態 UI 異常: {e}")

    def append_text(self, text):
        self.log_signal.emit(text)

    def _set_log_filter(self, key):
        self.log_filter = key
        chip = self.log_filter_buttons.get(key)
        if chip and not chip.isChecked():
            chip.setChecked(True)
        self._rerender_log()

    def _clear_log_view(self):
        self.log_feed.clear()
        self.log_view.clear()
        self._refresh_live_card()
        self._refresh_issue_badge()

    def _rerender_log(self):
        self.log_view.setUpdatesEnabled(False)
        self.log_view.clear()
        for entry in self.log_feed.entries:
            if log_matches_filter(entry, self.log_filter):
                self.log_view.append(render_log_entry(entry))
        self.log_view.setUpdatesEnabled(True)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _refresh_issue_badge(self):
        count = self.log_feed.issue_count
        self.log_issue_btn.setText(f"⚠ {count} 則需留意")
        self.log_issue_btn.setVisible(count > 0)

    def _refresh_live_card(self):
        live = self.log_feed.live
        if live.course:
            self.live_course_lbl.setText(f"目前課程：{live.course}")
            self.live_course_lbl.setToolTip(live.course)
        elif not live.active:
            self.live_course_lbl.setText("目前沒有研習中的課程")
        if live.active:
            parts = [f"{live.elapsed} / {live.target}"]
            if live.unit:
                parts.append(f"單元：{live.unit}")
            parts.append(f"{live.updated} 更新")
            self.live_detail_lbl.setText("｜".join(parts))
            self.live_detail_lbl.setToolTip("\n".join(parts))
            self.live_progress.setValue(int(min(live.pct, 100) * 10))
            self.live_progress.setFormat(f"{live.pct:.1f}%")
        else:
            self.live_detail_lbl.setText("等待進入教室後回報研習時數" if live.course else "開始執行後，研習時數與目前單元會在這裡即時更新")
            self.live_progress.setValue(0)
            self.live_progress.setFormat("--")

    def _append_text_safe(self, text):
        for update in self.log_feed.add_text(text):
            self._apply_log_update(update)

    def _apply_log_update(self, update):
        msg_part = update.message

        if any(k in msg_part for k in ["所有任務圓滿達成", "所有任務完成", "流程未完整完成"]):
            self.set_running_state(False, "● 本次流程已結束，可再次開始執行")

        # 🧠 Log 智慧進度攔截器 (Auto Progress Interceptor)
        try:
            # 1. 攔截總課程門數進度：例如 "[3/10] 正在協助研習：..."
            m_course = re.search(r"\[(\d+)/(\d+)\]\s*正在協助研習\s*[:：]?\s*(.*)", msg_part)
            if m_course:
                c_curr, c_tot, c_name = int(m_course.group(1)), int(m_course.group(2)), m_course.group(3).strip()
                pct = int((c_curr / c_tot) * 100) if c_tot > 0 else 0
                self.progress_bar.setValue(pct)
                self.stats_lbl.setText(f"📊 研習進度：{c_curr} / {c_tot} 門 ({pct}%) - 正在處理: {c_name[:12]}...")

            # 2. 攔截單門課程觀看時數與趴數：例如 "研習進度：00:28:55 / 02:06:00 [----] 22.9%"
            m_time = re.search(r"研習進度\s*[:：]\s*(\d{2}:\d{2}:\d{2}\s*/\s*\d{2}:\d{2}:\d{2}).*?([\d\.]+)%", msg_part)
            if m_time:
                time_str, pct_float = m_time.group(1), float(m_time.group(2))
                self.progress_bar.setValue(min(100, max(0, int(pct_float))))
                self.stats_lbl.setText(f"📊 本課程研習時數：{time_str} ({pct_float:.1f}%)")
        except Exception:
            pass

        if update.live_changed:
            self._refresh_live_card()
        entry = update.entry
        if entry is None:
            return
        self._refresh_issue_badge()
        if not log_matches_filter(entry, self.log_filter):
            return

        bar = self.log_view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        if update.merged:
            doc = self.log_view.document()
            cursor = QTextCursor(doc.lastBlock())
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            if doc.blockCount() == 1 and not doc.firstBlock().text():
                self.log_view.clear()
        self.log_view.append(render_log_entry(entry))
        if at_bottom:
            bar.setValue(bar.maximum())


class AccountSettingsTabPanel(QWidget):
    def __init__(self):
        super().__init__()
        # 外層主版面配置
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # 滾動區域：支援不同螢幕高度與解析度，避免內容卡片被擠壓
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        lbl = QLabel("⚙️ 帳號管理與系統設定")
        lbl.setStyleSheet("color: #2F3B43; font-weight: bold; font-size: 16px; background: transparent;")
        lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lbl.setFixedHeight(30)
        layout.addWidget(lbl)

        input_style = """
            QLineEdit, QComboBox {
                background: #F3F1ED;
                color: #2F3B43;
                border: 1px solid #BDB9B2;
                border-radius: 6px;
                padding: 7px 10px;
                font-size: 13px;
                min-height: 20px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 2px solid #70889B;
                background: #FAF9F6;
            }
        """

        card_style = """
            QFrame.settingSectionCard {
                background: #FAF9F6;
                border: 1px solid #D6D3CC;
                border-radius: 10px;
                padding: 12px 14px;
            }
            QFrame.settingSectionCard QLabel {
                color: #35434C;
                font-weight: bold;
                font-size: 13px;
                background: transparent;
                border: none;
            }
        """

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：臺北E大帳號")
        self.name_input.setStyleSheet(input_style)

        self.acc_input = QLineEdit()
        self.acc_input.setPlaceholderText("臺北E大登入帳號")
        self.acc_input.setStyleSheet(input_style)

        self.pwd_input = QLineEdit()
        self.pwd_input.setEchoMode(QLineEdit.Password)
        self.pwd_input.setPlaceholderText("臺北E大登入密碼")
        self.pwd_input.setStyleSheet(input_style)

        self.egov_name_input = QLineEdit()
        self.egov_name_input.setPlaceholderText("例如：e等公務員帳號")
        self.egov_name_input.setStyleSheet(input_style)

        self.egov_type_combo = QComboBox()
        self.egov_type_combo.addItem("e等公務員 eCPA", "ecpa")
        self.egov_type_combo.addItem("我的 E 政府", "egov")
        self.egov_type_combo.setStyleSheet(input_style)

        self.egov_acc_input = QLineEdit()
        self.egov_acc_input.setPlaceholderText("eCPA 或我的 E 政府帳號")
        self.egov_acc_input.setStyleSheet(input_style)

        self.egov_pwd_input = QLineEdit()
        self.egov_pwd_input.setEchoMode(QLineEdit.Password)
        self.egov_pwd_input.setPlaceholderText("eCPA 或我的 E 政府密碼")
        self.egov_pwd_input.setStyleSheet(input_style)

        checkbox_style = """
            QCheckBox {
                color: #2F3B43;
                font-weight: bold;
                font-size: 13px;
                background: transparent;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #98958F;
                border-radius: 4px;
                background-color: #FAF9F6;
            }
            QCheckBox::indicator:hover {
                border-color: #70889B;
            }
            QCheckBox::indicator:checked {
                background-color: #70889B;
                border-color: #70889B;
            }
        """

        self.headless_cb = QCheckBox("隱藏瀏覽器視窗（背景執行）")
        self.headless_cb.setToolTip("勾選後瀏覽器不顯示在桌面；課程仍會在背景執行。")
        self.headless_cb.setStyleSheet(checkbox_style)

        self.cloud_sync_cb = QCheckBox("啟用雲端共用題庫同步與匿名統計（GAS 連線）")
        self.cloud_sync_cb.setChecked(False)
        self.cloud_sync_cb.setToolTip("預設關閉（僅本機 SQLite 題庫與設定之 AI 服務）；勾選後才連線外部 Google Apps Script 共用題庫與匿名統計。")
        self.cloud_sync_cb.setStyleSheet(checkbox_style)

        self.ai_key_input = QLineEdit()
        self.ai_key_input.setEchoMode(QLineEdit.Password)
        self.ai_key_input.setPlaceholderText("選填；未填時只使用本機題庫，不會呼叫 AI")
        self.ai_key_input.setStyleSheet(input_style)

        # ── 1. 雙平臺帳號設定（左右並列卡片） ─────────────────────
        platforms_row = QHBoxLayout()
        platforms_row.setSpacing(14)

        # 🏛️ 臺北 E 大 卡片
        taipei_card = QFrame()
        taipei_card.setProperty("class", "settingSectionCard")
        taipei_card.setStyleSheet(card_style)
        taipei_card_layout = QVBoxLayout(taipei_card)
        taipei_card_layout.setContentsMargins(12, 12, 12, 12)
        taipei_card_layout.setSpacing(10)

        taipei_title = QLabel("🏛️ 臺北 E 大 帳號設定")
        taipei_title.setStyleSheet("color: #2F3B43; font-weight: 700; font-size: 14px; background: transparent; border: none; padding-bottom: 2px;")
        taipei_card_layout.addWidget(taipei_title)

        taipei_form = QFormLayout()
        taipei_form.setSpacing(10)
        taipei_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        taipei_form.addRow(QLabel("顯示名稱:"), self.name_input)
        taipei_form.addRow(QLabel("登入帳號:"), self.acc_input)
        taipei_form.addRow(QLabel("登入密碼:"), self._wrap_secret_input(self.pwd_input))
        taipei_card_layout.addLayout(taipei_form)
        taipei_card_layout.addStretch(1)

        # 🏛️ e 等公務員 卡片
        egov_card = QFrame()
        egov_card.setProperty("class", "settingSectionCard")
        egov_card.setStyleSheet(card_style)
        egov_card_layout = QVBoxLayout(egov_card)
        egov_card_layout.setContentsMargins(12, 12, 12, 12)
        egov_card_layout.setSpacing(10)

        egov_title = QLabel("🏛️ e 等公務員 帳號設定")
        egov_title.setStyleSheet("color: #2F3B43; font-weight: 700; font-size: 14px; background: transparent; border: none; padding-bottom: 2px;")
        egov_card_layout.addWidget(egov_title)

        egov_form = QFormLayout()
        egov_form.setSpacing(10)
        egov_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        egov_form.addRow(QLabel("顯示名稱:"), self.egov_name_input)
        egov_form.addRow(QLabel("登入方式:"), self.egov_type_combo)
        egov_form.addRow(QLabel("登入帳號:"), self.egov_acc_input)
        egov_form.addRow(QLabel("登入密碼:"), self._wrap_secret_input(self.egov_pwd_input))
        egov_card_layout.addLayout(egov_form)
        egov_card_layout.addStretch(1)

        platforms_row.addWidget(taipei_card, 1)
        platforms_row.addWidget(egov_card, 1)
        layout.addLayout(platforms_row)

        # ── 2. 全域執行與 AI 擴充設定（獨立卡片） ──────────────────
        global_card = QFrame()
        global_card.setProperty("class", "settingSectionCard")
        global_card.setStyleSheet(card_style)
        global_layout = QVBoxLayout(global_card)
        global_layout.setContentsMargins(14, 12, 14, 12)
        global_layout.setSpacing(10)

        global_title = QLabel("⚙️ 全域執行與 AI 擴充設定")
        global_title.setStyleSheet("color: #2F3B43; font-weight: 700; font-size: 14px; background: transparent; border: none; padding-bottom: 2px;")
        global_layout.addWidget(global_title)

        global_form = QFormLayout()
        global_form.setSpacing(10)
        global_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        global_form.addRow(QLabel("執行模式:"), self.headless_cb)
        global_form.addRow(QLabel("雲端題庫與統計:"), self.cloud_sync_cb)
        global_form.addRow(QLabel("Gemini API Key（選填）:"), self._wrap_secret_input(self.ai_key_input))
        global_layout.addLayout(global_form)

        # 💡 Google Gemini API 免費申請與 0 元防扣款指南卡片
        ai_tip_box = QFrame()
        ai_tip_box.setStyleSheet("""
            QFrame {
                background: #F0FDF4;
                border: 1px solid #86EFAC;
                border-radius: 8px;
                padding: 6px;
            }
        """)
        ai_tip_layout = QVBoxLayout(ai_tip_box)
        ai_tip_layout.setContentsMargins(10, 6, 10, 6)
        ai_tip_layout.setSpacing(4)

        ai_tip_title = QLabel("💡 <b>Google Gemini API 申請與配額說明</b>")
        ai_tip_title.setStyleSheet("color: #166534; font-size: 13px; font-weight: bold; background: transparent; border: none;")

        ai_tip_text = QLabel(
            "• <b>快速取得</b>：前往 Google AI Studio 點擊「Create API key」即可取得 Key。<br>"
            "• <b>免費層配額（Free Tier）</b>：Google 提供 Free Tier 配額（※ 配額與費用請以 Google 帳戶及官方公告為準）。<br>"
            "• <b>費用與防護</b>：未在 Google Cloud 啟用付費帳單之專案，超額時僅會返回 429 暫停。<br>"
            "• <b>金鑰安全</b>：API Key 僅保存在本機 <code>data/config.json</code>，日誌自動遮罩脫敏，絕不上傳第三方伺服器。"
        )
        ai_tip_text.setStyleSheet("color: #15803D; font-size: 12px; line-height: 1.4; background: transparent; border: none;")
        ai_tip_text.setWordWrap(True)

        ai_btn_row = QHBoxLayout()
        open_ai_studio_btn = QPushButton("🔗 前往申請 Google Gemini API Key (Google AI Studio)")
        open_ai_studio_btn.setStyleSheet("""
            QPushButton {
                background: #16A34A; color: #FFFFFF; font-weight: bold; font-size: 12px;
                padding: 5px 12px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background: #15803D; }
        """)
        open_ai_studio_btn.clicked.connect(lambda: self._open_url_native("https://aistudio.google.com/app/apikey"))

        open_pricing_btn = QPushButton("📊 查看 Google 官方費率公告")
        open_pricing_btn.setStyleSheet("""
            QPushButton {
                background: #E2E8F0; color: #334155; font-size: 12px;
                padding: 5px 12px; border-radius: 6px; border: 1px solid #CBD5E1;
            }
            QPushButton:hover { background: #CBD5E1; }
        """)
        open_pricing_btn.clicked.connect(lambda: self._open_url_native("https://ai.google.dev/pricing"))

        ai_btn_row.addWidget(open_ai_studio_btn)
        ai_btn_row.addWidget(open_pricing_btn)
        ai_btn_row.addStretch()

        ai_tip_layout.addWidget(ai_tip_title)
        ai_tip_layout.addWidget(ai_tip_text)
        ai_tip_layout.addLayout(ai_btn_row)

        global_layout.addWidget(ai_tip_box)

        btn_bar = QHBoxLayout()
        self.save_btn = QPushButton("💾 儲存並套用設定")
        self.save_btn.setStyleSheet("""
            QPushButton {
                background: #70889B; color: #FFFFFF; border-radius: 8px;
                padding: 9px 24px; font-weight: bold; font-size: 14px; border: none;
            }
            QPushButton:hover { background: #60798D; }
        """)
        self.save_btn.clicked.connect(lambda: self.save_settings(silent=False))
        btn_bar.addStretch()
        btn_bar.addWidget(self.save_btn)
        global_layout.addLayout(btn_bar)

        layout.addWidget(global_card)
        layout.addStretch(1)


        scroll_area.setWidget(content_widget)
        outer_layout.addWidget(scroll_area)

        self._saved_snapshot = {}
        self.load_settings()

    def _wrap_secret_input(self, line_edit: QLineEdit) -> QWidget:
        """為密碼或 API Key 欄位加上顯示／隱藏切換按鈕，方便使用者核對輸入內容。"""
        row_widget = QWidget()
        row_widget.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        toggle_btn = QPushButton("👁️")
        toggle_btn.setCheckable(True)
        toggle_btn.setFixedWidth(36)
        toggle_btn.setToolTip("點擊切換顯示／隱藏內容")
        toggle_btn.setStyleSheet("""
            QPushButton {
                background: #E8E5DF;
                color: #4B5962;
                border: 1px solid #BDB9B2;
                border-radius: 6px;
                padding: 5px 4px;
                font-size: 12px;
            }
            QPushButton:hover { background: #DCD8D0; }
            QPushButton:checked { background: #70889B; color: #FFFFFF; border-color: #5F798E; }
        """)

        def _toggle(checked: bool):
            line_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

        toggle_btn.toggled.connect(_toggle)
        row_layout.addWidget(line_edit, 1)
        row_layout.addWidget(toggle_btn)
        return row_widget

    def _snapshot_current_state(self) -> dict:
        return {
            "name": self.name_input.text().strip(),
            "acc": self.acc_input.text().strip(),
            "pwd": self.pwd_input.text(),
            "egov_name": self.egov_name_input.text().strip(),
            "egov_type": self.egov_type_combo.currentData() or "ecpa",
            "egov_acc": self.egov_acc_input.text().strip(),
            "egov_pwd": self.egov_pwd_input.text(),
            "headless": self.headless_cb.isChecked(),
            "cloud_sync_enabled": self.cloud_sync_cb.isChecked(),
            "ai_api_key": self.ai_key_input.text().strip(),
        }

    def has_unsaved_changes(self) -> bool:
        return self._snapshot_current_state() != getattr(self, "_saved_snapshot", {})

    def load_settings(self):
        try:
            if os.path.exists(get_config_path()):
                with open(get_config_path(), "r", encoding="utf-8") as f:
                    data = json.load(f)
                accounts = data.get("accounts", [])
                taipei_acc = next(
                    (acc for acc in accounts if acc.get("login_type") == "taipei_eda"),
                    None,
                ) or next((acc for acc in accounts if looks_like_legacy_taipei_account(acc)), None)
                if taipei_acc:
                    self.name_input.setText(taipei_acc.get("name", ""))
                    self.acc_input.setText(taipei_acc.get("account", ""))
                    self.pwd_input.setText(taipei_acc.get("password", ""))

                egov_acc = next(
                    (
                        acc for acc in accounts
                        if acc is not taipei_acc and acc.get("login_type") in ("ecpa", "egov")
                    ),
                    None,
                )
                if egov_acc:
                    self.egov_name_input.setText(egov_acc.get("name", ""))
                    self.egov_acc_input.setText(egov_acc.get("account", ""))
                    self.egov_pwd_input.setText(egov_acc.get("password", ""))
                    ltype = egov_acc.get("login_type", "ecpa")
                    idx = self.egov_type_combo.findData(ltype)
                    if idx != -1:
                        self.egov_type_combo.setCurrentIndex(idx)
                settings = data.get("settings", {})
                self.headless_cb.setChecked(settings.get("headless", False))
                self.cloud_sync_cb.setChecked(settings.get("cloud_sync_enabled", False))
                self.ai_key_input.setText(settings.get("ai_api_key", ""))
        except Exception:
            pass
        self._saved_snapshot = self._snapshot_current_state()

    def save_settings(self, silent: bool = False) -> bool:
        try:
            if os.path.exists(get_config_path()):
                with open(get_config_path(), "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"accounts": [], "settings": {}}

            taipei_account = self.acc_input.text().strip()
            taipei_password = self.pwd_input.text()
            egov_account = self.egov_acc_input.text().strip()
            egov_password = self.egov_pwd_input.text()

            if bool(taipei_account) != bool(taipei_password):
                get_ui_msgbox().warning(self, "設定未完成", "臺北E大帳號與密碼必須同時填寫。")
                return False
            if bool(egov_account) != bool(egov_password):
                get_ui_msgbox().warning(self, "設定未完成", "e等公務員帳號與密碼必須同時填寫。")
                return False

            accounts = []
            if taipei_account:
                accounts.append({
                    "name": self.name_input.text().strip() or "臺北E大",
                    "login_type": "taipei_eda",
                    "account": taipei_account,
                    "password": taipei_password,
                })
            if egov_account:
                accounts.append({
                    "name": self.egov_name_input.text().strip() or "e等公務員",
                    "login_type": self.egov_type_combo.currentData() or "ecpa",
                    "account": egov_account,
                    "password": egov_password,
                })
            if not accounts:
                if not silent:
                    get_ui_msgbox().warning(self, "設定未完成", "請至少設定一個平台的帳號與密碼。")
                return False
            data["accounts"] = accounts

            settings = data.get("settings", {})
            settings["headless"] = self.headless_cb.isChecked()
            settings["cloud_sync_enabled"] = self.cloud_sync_cb.isChecked()
            ai_key = self.ai_key_input.text().strip()
            if ai_key:
                settings["ai_api_key"] = ai_key
                settings["ai_provider"] = "Gemini"
                if "ai_keys" not in settings:
                    settings["ai_keys"] = {}
                settings["ai_keys"]["Gemini"] = ai_key
            data["settings"] = settings

            write_json_atomically(get_config_path(), data)
            self._saved_snapshot = self._snapshot_current_state()

            if hasattr(self, "on_settings_saved") and callable(self.on_settings_saved):
                self.on_settings_saved()

            if not silent:
                get_ui_msgbox().information(self, "成功", "✅ 帳號與系統設定已成功儲存並套用！")
            return True
        except Exception as e:
            if not silent:
                get_ui_msgbox().critical(self, "錯誤", f"❌ 儲存失敗：{e}")
            return False

    def _open_url_native(self, url: str):
        """使用系統原生機制開啟網頁"""
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

