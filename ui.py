import json
import os
import sys
import re
import threading
import random
import math
import traceback
from datetime import datetime

# 確保 PyInstaller frozen 模式下 _MEIPASS 在 sys.path 最前面
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    if sys._MEIPASS not in sys.path:
        sys.path.insert(0, sys._MEIPASS)

# 確保腳本所在目錄納入 sys.path（防範 embedded Python 環境下找不到同目錄模組）
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from app import AdminEfficiencyPilot
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import (
    Qt,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QSize,
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
from utils.helpers import (
    get_logger,
    format_quiz_prompt,
    parse_ai_quiz_answers,
    INTERACTIVE_QUIZ_TIMEOUT_SECONDS,
)
from utils.security import validate_ai_base_url, verify_file_sha256
from utils.config_io import write_json_atomically
from utils.app_paths import (
    app_dir,
    install_root,
    is_portable_layout,
    log_path,
    prepare_user_data,
    update_cache_path,
    user_data_path,
)
from utils.portable_update import stage_portable_zip
from usage_tracker import UsageHeartbeat
from utils.office_theme import INK as THEME_INK, ROW_COLORS, apply_office_theme, assistant_label, button_qss, render_log_entry
from utils.log_feed import FILTERS as LOG_FILTERS, LogFeed, matches_filter as log_matches_filter


from ui_parts import (
    AccountSettingsTabPanel,
    BASE_DIR,
    DEFAULT_CONFIG_PATH,
    GLOBAL_QSS,
    GLOBAL_QUIZ_DIALOG_LOCK,
    InteractiveQuizDialog,
    LOG_MAX_ENTRIES,
    PlatformTabPanel,
    SafeMarkdownBrowser,
    UpdateDialog,
    UpdateSignal,
    UsageSignal,
    _DownloadProgressSignal,
    add_hover_effect,
    icon,
    is_newer_version,
    load_config_data,
    looks_like_legacy_taipei_account,
    parse_release_update,
    resource_path,
    save_config_data,
    style_btn,
    version_tuple,
)

CONFIG_PATH = DEFAULT_CONFIG_PATH
logger = get_logger()


class ImmersivePage(QWidget):

    def __init__(self, on_stop):
        super().__init__()
        self.on_stop = on_stop
        self.on_start_platform = None
        self.on_stop_platform = None
        self.on_toggle_browser = None
        self.on_start_all = None
        self.on_check_update = None

        # 莫蘭迪暖灰主背景
        self.setStyleSheet("background-color: #F2F0EC;")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # 頂部控制列
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        title_lbl = QLabel("🎮 行政效能領航員")
        self.title_lbl = title_lbl
        title_lbl.setStyleSheet("color: #2F3B43; font-weight: 700; font-size: 18px; background: transparent; border: none;")

        from app import AdminEfficiencyPilot as _AEP
        self.ver_badge = QLabel(_AEP.VERSION)
        self.ver_badge.setStyleSheet("""
            background-color: #E4E0DA; color: #4F6B75; font-size: 12px; font-weight: bold;
            padding: 3px 8px; border-radius: 6px; border: 1px solid #C9C5BE;
        """)

        self.start_all_btn = QPushButton("🚀 同時執行兩平台")
        self.start_all_btn.setStyleSheet("""
            QPushButton {
                background: #617E87; color: #FFFFFF; border-radius: 8px;
                padding: 9px 18px; font-weight: bold; font-size: 14px; border: none;
            }
            QPushButton:hover { background: #506B74; }
        """)
        self.start_all_btn.clicked.connect(self._handle_start_all)

        self.stop_all_btn = QPushButton("🛑 停止所有平台")
        self.stop_all_btn.setStyleSheet("""
            QPushButton {
                background: #A96F6B; color: #FFFFFF; border-radius: 8px;
                padding: 9px 18px; font-weight: bold; font-size: 14px; border: none;
            }
            QPushButton:hover { background: #925D59; }
        """)
        self.stop_all_btn.clicked.connect(self.on_stop)

        self.check_update_btn = QPushButton("🔄 檢查更新")
        self.check_update_btn.setStyleSheet("""
            QPushButton {
                background: #FAF9F6; color: #2F3B43; border-radius: 8px;
                padding: 9px 16px; font-weight: bold; font-size: 14px; border: 1px solid #C9C5BE;
            }
            QPushButton:hover { background: #E9E5DF; }
        """)
        self.check_update_btn.clicked.connect(self._on_check_update_clicked)

        top_bar.addWidget(title_lbl)
        top_bar.addWidget(self.ver_badge)
        top_bar.addStretch()
        top_bar.addWidget(self.start_all_btn)
        top_bar.addWidget(self.stop_all_btn)
        top_bar.addWidget(self.check_update_btn)
        # 原生工具列保留單列資訊密度，由 Qt Layout 分配寬度。
        header_card = QFrame()
        header_card.setObjectName("officeHeader")
        header_card.setStyleSheet("#officeHeader { background: #FFF2DA; border: 2px solid #BD9871; border-radius: 10px; }")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.addLayout(top_bar)
        root.addWidget(header_card)

        # 💡 初次使用引導橫幅（當尚未配置任何帳號時友善提醒）
        self.onboarding_banner = QFrame()
        self.onboarding_banner.setObjectName("onboardingBanner")
        self.onboarding_banner.setStyleSheet("""
            QFrame#onboardingBanner {
                background: #FFF8E1;
                border: 1px solid #FFE082;
                border-radius: 8px;
                padding: 10px 16px;
            }
            QLabel {
                background: transparent;
                color: #795548;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton {
                background: #617E87;
                color: #FFFFFF;
                border-radius: 6px;
                padding: 5px 14px;
                font-size: 12px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { background: #506B74; }
        """)
        banner_layout = QHBoxLayout(self.onboarding_banner)
        banner_layout.setContentsMargins(4, 4, 4, 4)
        banner_icon = QLabel("💡")
        banner_icon.setStyleSheet("font-size: 16px;")
        banner_text = QLabel("歡迎使用！目前尚未設定任何研習平台帳號，請先至「⚙️ 帳號與系統設定」填寫帳密以開始自動化學習。")
        banner_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        banner_text.setWordWrap(True)
        banner_text.setMinimumWidth(0)
        banner_btn = QPushButton("立即前往設定")
        banner_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        banner_layout.addWidget(banner_icon)
        banner_layout.addWidget(banner_text)
        banner_layout.addStretch()
        banner_layout.addWidget(banner_btn)
        self.onboarding_banner.hide()
        root.addWidget(self.onboarding_banner)

        # 多頁籤面板 (QTabWidget - Win11 經典風格)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #D6D3CC;
                border-radius: 12px;
                background: #FAF9F6;
            }
            QTabBar::tab {
                background: #E4E0DA;
                color: #4B5962;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 10px 25px;
                font-weight: 700;
                font-size: 14px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #5F798E;
                color: #FFFFFF;
            }
            QTabBar::tab:hover:!selected {
                background: #D4D0C9;
                color: #2F3B43;
            }
        """)

        self.taipei_panel = PlatformTabPanel("taipei_eda", "臺北E大", self._on_tab_start, self._on_tab_stop, self._on_tab_toggle_browser)
        self.egov_panel = PlatformTabPanel("ecpa", "e等公務員 (eCPA/eGov)", self._on_tab_start, self._on_tab_stop, self._on_tab_toggle_browser)
        self.settings_panel = AccountSettingsTabPanel()
        self.settings_panel.on_settings_saved = self.load_accounts_into_tabs

        self.tabs.addTab(self.taipei_panel, "🏫 臺北E大")
        self.tabs.addTab(self.egov_panel, "🏛️ e等公務員")
        self.tabs.addTab(self.settings_panel, "⚙️ 帳號與系統設定")
        root.addWidget(self.tabs)

        self.load_accounts_into_tabs()
        apply_office_theme(self)

    def load_accounts_into_tabs(self):
        """讀取 config.json 自動動態將使用者名稱與帳號帶入各頁籤標題中"""
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                accounts = data.get("accounts", [])
                
                # 臺北E大帳號
                taipei_acc = next((a for a in accounts if a.get("login_type") == "taipei_eda"), None)
                if taipei_acc:
                    self.taipei_panel.update_account_info(taipei_acc.get("name", ""), taipei_acc.get("account", ""))
                else:
                    self.taipei_panel.update_account_info("未設定帳號", "")

                # e等公務員帳號
                egov_acc = next((a for a in accounts if a.get("login_type") in ("ecpa", "egov")), None)
                if egov_acc:
                    self.egov_panel.update_account_info(egov_acc.get("name", ""), egov_acc.get("account", ""))
                else:
                    self.egov_panel.update_account_info("未設定帳號", "")

                # 若兩個平台皆未設定帳號，顯示引導橫幅；否則隱藏
                has_any_account = bool(taipei_acc or egov_acc)
                if hasattr(self, "onboarding_banner"):
                    self.onboarding_banner.setVisible(not has_any_account)
        except Exception:
            pass

        self.w = 1000
        self.h = 650

    def _handle_start_all(self):
        if self.on_start_all:
            self.on_start_all()

    def _on_tab_start(self, key):
        if self.on_start_platform:
            self.on_start_platform(key)

    def _on_tab_stop(self, key):
        if self.on_stop_platform:
            self.on_stop_platform(key)

    def _on_tab_toggle_browser(self, key, visible):
        if self.on_toggle_browser:
            self.on_toggle_browser(key, visible)

    def _on_check_update_clicked(self):
        if hasattr(self, "on_check_update") and callable(self.on_check_update):
            self.on_check_update()

    def start(self, account_name: str):
        self.load_accounts_into_tabs()

    def _init_position(self):
        pass


# =========================
# 主視窗（頁面切換）
# =========================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        from app import AdminEfficiencyPilot as _AEP
        self.setWindowTitle(f"行政效能領航員 {_AEP.VERSION}")
        self.setStyleSheet("background-color: #F2F0EC;")

        self.immersive = ImmersivePage(self._stop_all_platforms)

        # 綁定頁籤與按鈕事件
        self.immersive.on_start_platform = self._start_single_platform
        self.immersive.on_stop_platform = self._stop_single_platform
        self.immersive.on_toggle_browser = self._toggle_platform_browser
        self.immersive.on_start_all = self._start_all_platforms
        self.immersive.on_check_update = self._handle_manual_check_update

        self.setMinimumSize(760, 440)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1120, available.width()), min(720, available.height()))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.immersive)

        # 預設展示多頁籤控制中心
        self.immersive.start("預設使用者")

        self.taipei_pilot = None
        self.taipei_thread = None
        self.egov_pilot = None
        self.egov_thread = None
        self.cleanup_thread = None

        self._has_update = False
        self._latest_update_info = None

        self.usage_signal = UsageSignal()
        self.usage = UsageHeartbeat(AdminEfficiencyPilot.VERSION, self._on_usage_stats)
        self.usage.start()

        # 啟動時背景檢查更新
        self._run_startup_update_check()

        # 手動檢查更新訊號綁定
        self._manual_update_signal = UpdateSignal()
        self._manual_update_signal.notify.connect(self._on_manual_update_available)
        self._manual_update_signal.up_to_date.connect(self._on_manual_up_to_date)
        self._manual_update_signal.failed.connect(self._on_manual_update_failed)

        # 📌 初始化 Windows 右下角系統列 (System Tray) 常駐圖示
        self._setup_tray_icon()

    def _setup_tray_icon(self):
        """初始化 Windows 右下角系統列 (System Tray) 圖示與右鍵選單"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        icon = self.windowIcon()
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.SP_ComputerIcon)

        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("行政效能領航員 - 控制中心")

        # 托盤右鍵選單
        tray_menu = QMenu(self)
        
        show_action = tray_menu.addAction("📖 顯示控制中心")
        show_action.triggered.connect(self.show_normal_window)

        start_all_action = tray_menu.addAction("🚀 同時執行兩平台")
        start_all_action.triggered.connect(self._start_all_platforms)

        stop_all_action = tray_menu.addAction("🛑 停止所有平台")
        stop_all_action.triggered.connect(self._stop_all_platforms)

        check_update_action = tray_menu.addAction("🔄 檢查更新")
        check_update_action.triggered.connect(self._handle_manual_check_update)

        tray_menu.addSeparator()

        quit_action = tray_menu.addAction("🚪 完全退出程式")
        quit_action.triggered.connect(self.quit_app)

        self.tray_icon.setContextMenu(tray_menu)
        # 單擊或雙擊托盤圖示切換顯示/隱藏
        self.tray_icon.activated.connect(self._on_tray_icon_activated)
        self.tray_icon.show()

        self._tray_notice_shown = False

    def _on_tray_icon_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_normal_window()

    def show_normal_window(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        """按下右上角 X 時，自動無痕縮小至系統列而非直接關閉"""
        if hasattr(self, "tray_icon") and self.tray_icon.isVisible():
            self.hide()
            event.ignore()
            if not getattr(self, "_tray_notice_shown", False):
                self.tray_icon.showMessage(
                    "行政效能領航員",
                    "程式已縮小至右下角系統列，背景看課繼續運行。\n點擊或雙擊托盤圖示可重新顯示控制中心！",
                    QSystemTrayIcon.Information,
                    3000
                )
                self._tray_notice_shown = True
        else:
            self.quit_app()

    def changeEvent(self, event):
        """最小化視窗時維持於 Windows 工作列，僅在點擊右上角 X (closeEvent) 時隱藏至系統列。"""
        super().changeEvent(event)

    def quit_app(self):
        """完全退出程式並釋放所有資源"""
        self._stop_all_platforms()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        QApplication.quit()

    def _start_single_platform(self, key):
        # 🛡️ 若使用者在設定分頁修改了帳密或 API Key 卻忘記按儲存，啟動前自動驗證並儲存套用
        if hasattr(self.immersive, "settings_panel") and self.immersive.settings_panel.has_unsaved_changes():
            if not self.immersive.settings_panel.save_settings(silent=True):
                return

        config_from_entry = load_config_data()
        accounts = config_from_entry.get("accounts", [])
        
        # 尋找匹配平臺的帳號（對應 ecpa 時兼顧 egov 與 ecpa）
        if key in ("ecpa", "egov"):
            acc_data = next((a for a in accounts if a.get("login_type") in ("ecpa", "egov")), None)
        else:
            acc_data = next((a for a in accounts if a.get("login_type") == key), None)

        if not acc_data:
            logger.warning(f"⚠️ 找不到平台 {key} 的對應帳號設定")
            platform_name = "臺北E大" if key == "taipei_eda" else "e等公務員"
            QMessageBox.warning(
                self,
                "尚未設定帳號",
                f"找不到{platform_name}的專用帳號。\n請先到『帳號與系統設定』完成設定。",
            )
            return

        full_config = acc_data.copy()
        full_config.update(config_from_entry.get("settings", {}))
        # 🔒 即時讀取 UI 最新『背景執行』與『雲端同步』勾選狀態
        full_config["headless"] = self.immersive.settings_panel.headless_cb.isChecked()
        full_config["cloud_sync_enabled"] = self.immersive.settings_panel.cloud_sync_cb.isChecked()
        panel = self.immersive.taipei_panel if key == "taipei_eda" else self.immersive.egov_panel
        exam_mode = panel.exam_mode_combo.currentData() or "sqlite"
        full_config["skip_exam_for_session"] = (exam_mode == "skip")
        full_config["interactive_quiz_for_session"] = (exam_mode == "interactive")
        if exam_mode == "gemini_direct":
            full_config["ai_auto_solve"] = True
            logger.info("本次執行已啟用「4. Gemini API 批次直連 ⭐」模式（自動背景極速作答）。")
        elif exam_mode == "skip":
            logger.info("本次執行已啟用「3. 跳過測驗模式（先填問卷）」模式。")
        elif exam_mode == "interactive":
            logger.info("本次執行已啟用「2. 人機協同助理彈窗模式（彈窗回貼／一鍵作答）」模式。")
        else:
            full_config["ai_auto_solve"] = False
            logger.info("本次執行採用「1. SQLite 題庫秒殺模式（本機題庫優先）」模式。")


        if key == "taipei_eda":
            # 檢查並自動清理已死掉的舊 Thread
            if self.taipei_thread and not self.taipei_thread.is_alive():
                self.taipei_thread = None
                self.taipei_pilot = None

            if self.taipei_thread and self.taipei_thread.is_alive():
                logger.warning("⚠️ 臺北E大流程已在運行中")
                return
            full_config["login_type"] = "taipei_eda"
            self.taipei_pilot = AdminEfficiencyPilot(
                config_override=full_config,
                log_callback=self.immersive.taipei_panel.append_text,
                progress_callback=self.immersive.taipei_panel.update_progress,
                quiz_interactive_callback=self.immersive.taipei_panel.prompt_quiz_interactive,
                course_state_callback=self.immersive.taipei_panel.emit_course_state,
            )
            self.taipei_pilot.running = True
            self.taipei_thread = threading.Thread(target=self.taipei_pilot.run, daemon=True)
            self.taipei_thread.start()
            panel.set_running_state(True, "● 執行中：正在啟動臺北E大流程")
            logger.info("🚀 臺北E大流程已啟動")

        else:  # ecpa / egov
            # 檢查並自動清理已死掉的舊 Thread
            if self.egov_thread and not self.egov_thread.is_alive():
                self.egov_thread = None
                self.egov_pilot = None

            if self.egov_thread and self.egov_thread.is_alive():
                logger.warning("⚠️ e等公務員流程已在運行中")
                return
            self.egov_pilot = AdminEfficiencyPilot(
                config_override=full_config,
                log_callback=self.immersive.egov_panel.append_text,
                progress_callback=self.immersive.egov_panel.update_progress,
                quiz_interactive_callback=self.immersive.egov_panel.prompt_quiz_interactive,
                course_state_callback=self.immersive.egov_panel.emit_course_state,
            )
            self.egov_pilot.running = True
            self.egov_thread = threading.Thread(target=self.egov_pilot.run, daemon=True)
            self.egov_thread.start()
            panel.set_running_state(True, "● 執行中：正在啟動 e等公務員流程")
            logger.info(f"🚀 e等公務員流程已啟動 (登入模式: {full_config.get('login_type')})")

    def _stop_single_platform(self, key):
        if key == "taipei_eda":
            if self.taipei_pilot:
                self.taipei_pilot.running = False
                try:
                    self.taipei_pilot._cleanup()
                except Exception:
                    pass
            self.taipei_pilot = None
            self.taipei_thread = None
            self.immersive.taipei_panel.set_running_state(False, "● 已停止臺北E大流程")
            logger.info("🛑 已停止臺北E大流程")
        else:
            if self.egov_pilot:
                self.egov_pilot.running = False
                try:
                    self.egov_pilot._cleanup()
                except Exception:
                    pass
            self.egov_pilot = None
            self.egov_thread = None
            self.immersive.egov_panel.set_running_state(False, "● 已停止 e等公務員流程")
            logger.info("🛑 已停止e等公務員流程")

    def _toggle_platform_browser(self, key, visible):
        if key == "taipei_eda":
            from taipei_eda_course import toggle_taipei_driver_visibility
            toggle_taipei_driver_visibility(visible)
            if self.taipei_pilot:
                self.taipei_pilot.toggle_chrome_visibility(visible)
        else:
            if self.egov_pilot:
                self.egov_pilot.toggle_chrome_visibility(visible)

    def _start_all_platforms(self):
        logger.info("🚀 正在啟動全自動一鍵雙開...")
        self._start_single_platform("taipei_eda")
        self._start_single_platform("ecpa")

    def _stop_all_platforms(self):
        logger.info("🛑 正在停止所有平台的自動化流程...")
        self._stop_single_platform("taipei_eda")
        self._stop_single_platform("ecpa")

    def go_immersive(self, account_data):
        self.resize(1000, 650)
        self.stack.setCurrentWidget(self.immersive)
        self.immersive.start(account_data.get("name", "使用者"))
        # 依目前選擇的帳號自動啟動該平臺
        login_type = account_data.get("login_type", "ecpa")
        self._start_single_platform(login_type)

    def _on_usage_stats(self, stats):
        online = stats.get("online") or stats.get("online_count")
        if online is None:
            return
        try:
            self.usage_signal.online.emit(int(online))
        except Exception:
            pass

    def _run_startup_update_check(self):
        """背景檢查 GitHub Release，支援 ETag 與 Portable asset digest。"""
        from app import AdminEfficiencyPilot
        import threading, requests as _req

        RELEASE_API = "https://api.github.com/repos/lianghao02/auto-learning-bot/releases/latest"
        current_version = AdminEfficiencyPilot.VERSION

        self._update_signal = UpdateSignal()
        self._update_signal.notify.connect(self._on_update_available)
        self._update_signal.up_to_date.connect(self._on_up_to_date)
        _update_signal = self._update_signal

        _log_path = str(log_path("update_debug.log"))

        def _dbg(msg):
            try:
                if os.path.exists(_log_path) and os.path.getsize(_log_path) > 1024 * 1024:
                    os.replace(_log_path, f"{_log_path}.1")
                with open(_log_path, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass

        def _check():
            _dbg("update check thread started")
            try:
                cache_file = update_cache_path()
                cache = {}
                try:
                    if cache_file.is_file():
                        cache = json.loads(cache_file.read_text(encoding="utf-8"))
                except Exception:
                    cache = {}
                headers = {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                if cache.get("etag"):
                    headers["If-None-Match"] = str(cache["etag"])
                resp = _req.get(RELEASE_API, timeout=8, headers=headers)
                _dbg(f"release_status={resp.status_code}")
                if resp.status_code == 304:
                    data = cache.get("release") or {}
                elif resp.status_code == 200:
                    data = resp.json()
                    write_json_atomically(
                        cache_file,
                        {"etag": resp.headers.get("ETag", ""), "release": data},
                    )
                else:
                    _dbg(f"GitHub Release API HTTP {resp.status_code}: {resp.text[:200]}")
                    return

                update_info = parse_release_update(data, current_version)
                if update_info:
                    latest, changelog, download_url, file_size, digest = update_info
                    _dbg(f"latest={latest!r} current={current_version!r} size={file_size}")
                    if not digest:
                        _dbg("Portable asset 缺少有效 SHA-256 digest，僅允許手動下載")
                    _dbg("emitting update signal")
                    _update_signal.emit(latest, changelog, download_url, file_size, digest)
                else:
                    _dbg("already latest")
                    _update_signal.up_to_date.emit()
            except Exception as e:
                _dbg(f"例外：{e}")

        threading.Thread(target=_check, daemon=True).start()

    def _reset_check_update_btn(self):
        btn = getattr(self.immersive, "check_update_btn", None)
        if btn:
            btn.setText("🔄 檢查更新")
            btn.setEnabled(True)

    def _on_manual_update_available(self, latest, changelog, url, size, digest):
        self._reset_check_update_btn()
        self._has_update = True
        self._latest_update_info = (latest, changelog, url, size, digest)
        UpdateDialog(self, latest, changelog, url, size, digest).exec()

    def _on_manual_up_to_date(self):
        self._reset_check_update_btn()
        self._has_update = False
        self._latest_update_info = None
        self._show_version_dialog()

    def _on_manual_update_failed(self, err_msg):
        self._reset_check_update_btn()
        QMessageBox.warning(self, "檢查更新", f"連線至 GitHub 檢查更新失敗：\n{err_msg}")

    def _handle_manual_check_update(self):
        """手動點擊「檢查更新」：即時連線 GitHub API 檢查並透過 Qt Signal 安全回傳主線程"""
        from app import AdminEfficiencyPilot as _AEP
        import threading, requests as _req

        RELEASE_API = "https://api.github.com/repos/lianghao02/auto-learning-bot/releases/latest"
        current_version = _AEP.VERSION

        btn = getattr(self.immersive, "check_update_btn", None)
        if btn:
            btn.setText("⏳ 檢查中...")
            btn.setEnabled(False)

        def _worker():
            try:
                cache_file = update_cache_path()
                cache = {}
                try:
                    if cache_file.is_file():
                        cache = json.loads(cache_file.read_text(encoding="utf-8"))
                except Exception:
                    cache = {}
                headers = {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "AdminEfficiencyPilot-UpdateChecker",
                }
                if cache.get("etag"):
                    headers["If-None-Match"] = str(cache["etag"])
                resp = _req.get(RELEASE_API, timeout=6, headers=headers)
                if resp.status_code == 304:
                    data = cache.get("release") or {}
                elif resp.status_code == 200:
                    data = resp.json()
                    write_json_atomically(
                        cache_file,
                        {"etag": resp.headers.get("ETag", ""), "release": data},
                    )
                else:
                    self._manual_update_signal.failed.emit(f"HTTP {resp.status_code}")
                    return

                update_info = parse_release_update(data, current_version)
                if update_info:
                    latest, changelog, download_url, file_size, digest = update_info
                    self._manual_update_signal.notify.emit(latest, changelog, download_url, file_size, digest)
                else:
                    self._manual_update_signal.up_to_date.emit()
            except Exception as e:
                self._manual_update_signal.failed.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_update_btn(self):
        """手動點更新圖示：一定跳視窗顯示版本資訊"""
        if self._has_update and self._latest_update_info:
            info = self._latest_update_info
            if len(info) == 5:
                latest, changelog, url, size, digest = info
            elif len(info) == 4:
                latest, changelog, url, size = info
                digest = ""
            else:
                latest, changelog, url = info
                size = 0
                digest = ""
            self._on_update_available(latest, changelog, url, size, digest)
        else:
            self._show_version_dialog()

    def _show_version_dialog(self):
        """顯示目前版本視窗（尚未有新版資訊）"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QFrame
        from app import AdminEfficiencyPilot as _AEP
        cur_ver = _AEP.VERSION

        dialog = QDialog(self)
        dialog.setWindowTitle("版本資訊")
        dialog.setFixedWidth(360)
        dialog.setStyleSheet("QDialog { background: #f5f7fa; } QLabel { color: #2c3e50; background: transparent; }")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel()
        header.setFixedHeight(6)
        header.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4fc3f7,stop:1 #0288d1);")
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(28, 22, 28, 24)
        body.setSpacing(12)

        title = QLabel("版本資訊")
        title.setStyleSheet("font-size: 17px; font-weight: bold; color: #0277bd;")
        body.addWidget(title)

        cur_label = QLabel(f"目前版本：{cur_ver}")
        cur_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50;")
        body.addWidget(cur_label)

        if self._has_update and self._latest_update_info:
            latest_label = QLabel(f"線上最新版本：{self._latest_update_info[0]}")
            latest_label.setStyleSheet("font-size: 13px; color: #d35400; font-weight: bold;")
        else:
            latest_label = QLabel("更新狀態：✅ 目前已是最新版本！")
            latest_label.setStyleSheet("font-size: 13px; color: #27ae60; font-weight: bold;")
        body.addWidget(latest_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #dce1e7;")
        body.addWidget(sep)

        close_btn = QPushButton("關閉")
        close_btn.setMinimumHeight(40)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #e0e0e0; color: #2c3e50;
                border: none; border-radius: 6px; font-size: 13px;
                padding: 8px 0;
                text-align: center;
            }
            QPushButton:hover { background: #bdbdbd; }
        """)
        close_btn.clicked.connect(dialog.accept)
        body.addWidget(close_btn)

        layout.addLayout(body)

        from PySide6.QtWidgets import QApplication
        def _center():
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.x() + (screen.width() - dialog.width()) // 2
            y = screen.y() + (screen.height() - dialog.height()) // 2
            dialog.move(x, y)
        QTimer.singleShot(0, _center)

        dialog.exec()

    def _on_up_to_date(self):
        """已是最新版"""
        self._has_update = False

    def _on_update_available(
        self,
        latest: str,
        changelog: str,
        url: str,
        size: int = 0,
        digest: str = "",
    ):
        """顯示安全更新對話框"""
        self._has_update = True
        self._latest_update_info = (latest, changelog, url, size, digest)
        UpdateDialog(self, latest, changelog, url, size, digest).exec()

    def _request_stop_current_pilot(self):
        if hasattr(self, "taipei_pilot") and self.taipei_pilot:
            self.taipei_pilot.running = False
            try:
                self.taipei_pilot._cleanup()
            except Exception:
                pass
        if hasattr(self, "egov_pilot") and self.egov_pilot:
            self.egov_pilot.running = False
            try:
                self.egov_pilot._cleanup()
            except Exception:
                pass

    def _cleanup_pilot_async(self):
        """在後臺安全清理所有 pilot 資源，不阻塞 UI"""
        try:
            if hasattr(self, "taipei_thread") and self.taipei_thread and self.taipei_thread.is_alive():
                self.taipei_thread.join(timeout=3)
            if hasattr(self, "egov_thread") and self.egov_thread and self.egov_thread.is_alive():
                self.egov_thread.join(timeout=3)

            if hasattr(self, "taipei_pilot") and self.taipei_pilot:
                self.taipei_pilot._cleanup()
            if hasattr(self, "egov_pilot") and self.egov_pilot:
                self.egov_pilot._cleanup()
        except Exception:
            pass

# =========================
# Run
# =========================
if __name__ == "__main__":
    try:
        # 強制把工作目錄切到 exe / 腳本所在資料夾，
        # 避免從捷徑或 updater.bat 啟動時 cwd 跑到 System32 導致 config.json 寫入權限錯誤
        try:
            os.chdir(app_dir())
            prepare_user_data()
        except Exception:
            pass

        app = QApplication(sys.argv)
        app.setStyleSheet(GLOBAL_QSS)

        w = MainWindow()
        w.show()

        # 程式正常啟動並顯示主介面後，自動隱藏 CMD / Console 控制台視窗
        if os.name == "nt" and "--debug" not in sys.argv and os.environ.get("DEBUG") != "1":
            try:
                import ctypes
                _hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if _hwnd:
                    ctypes.windll.user32.ShowWindow(_hwnd, 0)  # 0 = SW_HIDE
            except Exception:
                pass

        sys.exit(app.exec())
    except Exception as exc:
        err_msg = f"【程式啟動失敗】\n\n發生未預期的例外錯誤：\n{traceback.format_exc()}"
        try:
            with open(log_path("startup_error.log"), "w", encoding="utf-8") as f:
                f.write(err_msg)
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, err_msg, "啟動失敗 - 行政效能領航員", 0x10)
        except Exception:
            print(err_msg, file=sys.stderr)
        sys.exit(1)
