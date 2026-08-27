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
# 粒子轉場效果
# =========================
class ParticleEffect(QWidget):
    """前往宇宙的粒子轉場效果"""

    finished = Signal()  # ⭐ 動畫完成信號

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0.9);")
        self.particles = []
        self.elapsed_time = 0
        self.duration = 800  # 0.8秒

    def showEvent(self, event):
        self.create_particles()
        super().showEvent(event)

        # 定時器更新動畫
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_particles)
        self.timer.start(16)  # ~60fps

    def create_particles(self):
        """創建隨機粒子"""
        num_particles = 150
        center_x = self.width() // 2
        center_y = self.height() // 2

        for _ in range(num_particles):
            # 隨機角度和速度
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(2, 8)

            # 起點在屏幕邊緣
            distance = random.uniform(300, 600)
            start_x = center_x + distance * math.cos(angle)
            start_y = center_y + distance * math.sin(angle)

            # 粒子大小和透明度
            size = random.uniform(2, 6)
            color = random.choice(
                [
                    QColor(100, 200, 255),  # 藍色
                    QColor(150, 220, 255),  # 淡藍
                    QColor(200, 240, 255),  # 淡白藍
                    QColor(255, 255, 255),  # 白色
                ]
            )

            self.particles.append(
                {
                    "x": start_x,
                    "y": start_y,
                    "vx": -math.cos(angle) * speed,
                    "vy": -math.sin(angle) * speed,
                    "size": size,
                    "color": color,
                    "opacity": 1.0,
                }
            )

    def update_particles(self):
        """更新粒子位置和動畫"""
        self.elapsed_time += 16
        progress = min(self.elapsed_time / self.duration, 1.0)

        center_x = self.width() // 2
        center_y = self.height() // 2

        for particle in self.particles:
            # 移動粒子
            particle["x"] += particle["vx"]
            particle["y"] += particle["vy"]

            # 淡出效果
            particle["opacity"] = 1.0 - progress

        self.update()  # 重繪

        # 動畫完成
        if progress >= 1.0:
            self.timer.stop()
            self.finished.emit()

    def paintEvent(self, event):
        """繪製粒子"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        for particle in self.particles:
            color = particle["color"]
            color.setAlpha(int(255 * particle["opacity"]))

            painter.setBrush(color)
            painter.setPen(Qt.NoPen)

            x = particle["x"]
            y = particle["y"]
            size = particle["size"]

            painter.drawEllipse(
                int(x - size / 2), int(y - size / 2), int(size), int(size)
            )

        painter.end()

    def resizeEvent(self, event):
        """視窗大小改變時重新創建粒子"""
        if not self.particles:
            self.create_particles()
        super().resizeEvent(event)


# =========================
# 共用樣式（簡約大氣）
# =========================
GLOBAL_QSS = """
QWidget {
    background-color: transparent;
    color: #111827;
}
#card {
    background-color: rgba(255, 255, 255, 0.1);  /* 半透明 */
    border-radius: 20px;

    border: 1px solid rgba(255, 255, 255, 0.2);  /* 淡白邊 */

    padding: 16px;
}
QPushButton {
    background-color: rgba(255,255,255,0.8);
    color: #111827;
    border-radius: 16px;
    padding: 16px;

    font-size: 16px;
    text-align: left;

    border: none;
}

/* ⭐ hover：不變色，只做浮動感 */
QPushButton:hover {
    background-color: #fef3c7;

    border: 1px solid rgba(0,0,0,0.15);
}

/* 點擊 */
QPushButton:pressed {
    background-color: #fef3c7;

    border: 1px solid rgba(0,0,0,0.25);

    padding-top: 18px;
    padding-bottom: 14px;  /* 反向 → 壓下去 */
}

QPushButton#ghost {
    background-color: transparent;
    border: 1px solid #E5E7EB;
    color: #6B7280;
    border-radius: 8px;
    padding: 6px 12px;
}
QPushButton#ghost:hover {
    border: 1px solid #D1D5DB;
    color: #111827;
}

QComboBox {
    background-color: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 8px 10px;
    color: #111827;
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
    # ===== 陰影1（貼近，柔）
    shadow1 = QGraphicsDropShadowEffect(btn)
    shadow1.setBlurRadius(25)
    shadow1.setOffset(0, 6)
    shadow1.setColor(QColor(0, 0, 0, 30))

    # ===== 陰影2（遠距，懸浮感）
    shadow2 = QGraphicsDropShadowEffect(btn)
    shadow2.setBlurRadius(60)
    shadow2.setOffset(0, 20)
    shadow2.setColor(QColor(0, 0, 0, 20))

    # ⚠️ Qt 只能套一個 effect → 用 shadow1 當主體
    btn.shadow = shadow1
    btn.setGraphicsEffect(shadow1)

    def enterEvent(event):
        # 👉 浮起來
        btn.move(btn.x(), btn.y() - 4)

        # 👉 陰影拉開（模擬高度）
        btn.shadow.setBlurRadius(45)
        btn.shadow.setOffset(0, 18)
        btn.shadow.setColor(QColor(0, 0, 0, 80))

    def leaveEvent(event):
        # 👉 回來
        btn.move(btn.x(), btn.y() + 4)

        # 👉 回到貼近狀態
        btn.shadow.setBlurRadius(25)
        btn.shadow.setOffset(0, 6)
        btn.shadow.setColor(QColor(0, 0, 0, 30))

    btn.enterEvent = enterEvent
    btn.leaveEvent = leaveEvent


# =========================
# 入口頁
# =========================
class EntryPage(QWidget):
    _ai_verify_signal = Signal(bool, str)

    def __init__(self, on_start):
        super().__init__()
        self._ai_verify_signal.connect(self._on_ai_verify_done)

        self.is_updating = False

        self.on_start = on_start

        self.bg_label = QLabel(self)
        self.bg_label.setPixmap(QPixmap(resource_path("login.png")))
        self.bg_label.setScaledContents(True)
        self.bg_label.lower()  # ⭐ 放到最底層

        # ⭐ 手機螢幕位置（先用這組，之後可微調）
        self.screen_x = 421
        self.screen_y = 132
        self.screen_w = 263
        self.screen_h = 473

        self.account_container = QFrame(self)
        self.account_container.setObjectName("card")
        self.account_container.setGeometry(
            self.screen_x, self.screen_y, self.screen_w, self.screen_h
        )

        # ⭐ 模擬手機內 UI（圓角 + 微透明）
        self.account_container.setStyleSheet("""
            background-color: rgba(255,255,255,0.06);
            border-radius: 24px;
        """)

        # ⭐ 手機內 layout（這是關鍵）
        account_outer_layout = QVBoxLayout(self.account_container)
        account_outer_layout.setContentsMargins(0, 0, 0, 0)
        account_outer_layout.setSpacing(0)

        self.account_scroll = QScrollArea(self.account_container)
        self.account_scroll.setWidgetResizable(True)
        self.account_scroll.setFrameShape(QFrame.NoFrame)
        self.account_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.account_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.account_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 4px;
                margin: 70px 0px 34px 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.22);
                border-radius: 2px;
                min-height: 36px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255,255,255,0.38);
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        self.account_scroll_content = QWidget()
        self.account_scroll_content.setStyleSheet("background: transparent;")
        self.inner_layout = QVBoxLayout(self.account_scroll_content)
        self.inner_layout.setContentsMargins(20, 8, 18, 20)
        self.inner_layout.setSpacing(30)
        self.inner_layout.setAlignment(Qt.AlignTop)
        self.account_scroll.setWidget(self.account_scroll_content)
        account_outer_layout.addWidget(self.account_scroll)
        # 加標題（像 App）
        title = QLabel("行政效能領航員")
        title.setStyleSheet("""
            font-family: "Noto Sans TC Rounded";
            color: rgba(0,0,0,0.6);
            font-size: 16px;
            font-weight: 600;
            margin-left: 24px;
            margin-top: -4px;
            letter-spacing: 1px;
        """)

        self.inner_layout.addWidget(title)

        # 做「卡片式按鈕」（核心）
        self.combo = QComboBox()
        self.combo.addItem("         請選擇人員")  # ⭐ Step1：預設提示
        font = QFont()
        if font.pointSize() <= 0:
            font.setPointSize(10)  # 🔥 固定字體大小
        self.combo.setFont(font)
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.setMinimumHeight(46)

        self.combo.setStyleSheet("""
        QComboBox {
            background-color: rgba(255,255,255,0.18);
            border-radius: 16px;
            border: 1px solid rgba(255,255,255,0.25);
            padding: 11px 14px;
            font-size: 14px;
            color: #111827;
        }

        QComboBox:hover {
            background-color: rgba(255,255,255,0.35);
        }

        QComboBox::drop-down {
            border: none;
            background: transparent;
            width: 36px;
        }

        QComboBox::down-arrow {
            image: url(icons/down-arrow.png);
            width: 20px;
            height: 20px;
        }

        /* 下拉選單 */
        QComboBox QAbstractItemView {
            background-color: rgba(255,255,255,0.95);
            border-radius: 10px;
            padding: 6px;
            selection-background-color: rgba(0,0,0,0.08);
        }
        """)
        self.combo.activated.connect(self._on_combo_activated)

        self.btn_add = QPushButton("   新增帳號")
        self.btn_edit = QPushButton("   編輯帳號")
        self.btn_delete = QPushButton("   刪除帳號")
        self.btn_setting = QPushButton("   設定執行方式")

        self.btn_add.setIcon(icon("add.png"))
        self.btn_edit.setIcon(icon("edit.png"))
        self.btn_delete.setIcon(icon("delete.png"))
        self.btn_setting.setIcon(icon("settings.png"))

        self.inner_layout.addWidget(self.combo)

        for btn in [self.btn_add, self.btn_edit, self.btn_delete, self.btn_setting]:
            btn.setMinimumHeight(52)
            btn.setFont(font)
            btn.setIconSize(QSize(24, 24))
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            add_hover_effect(btn)
            btn.setLayoutDirection(Qt.LeftToRight)
            btn.setStyleSheet("""
                background-color: rgba(255,255,255,0.25);
                border-radius: 16px;
                border: 1px solid rgba(255,255,255,0.25);
                padding: 10px 12px;
                font-size: 14px;
                text-align: left;
            """)
            self.inner_layout.addWidget(btn)

        self.btn_add.clicked.connect(self.add_account)
        self.btn_edit.clicked.connect(self.edit_account)
        self.btn_delete.clicked.connect(self.delete_account)
        self.btn_setting.clicked.connect(self.edit_settings)

        # ===== 操作按鈕 =====

        self.config = self.load_config()
        self.accounts = self.config.get("accounts", [])

        self.is_updating = True

        self.combo.blockSignals(True)
        self.refresh_combo()
        self.combo.setCurrentIndex(0)

        self.combo.blockSignals(False)

        # ===== 遮罩（放在 panel 前）=====

        self.overlay = QWidget(self)
        self.overlay.setStyleSheet("""
            background-color: rgba(0,0,0,0.25);
        """)
        self.overlay.hide()

        # ⭐ 改成自定義點擊事件
        def on_overlay_clicked(event):
            # 隱藏 panel 和 confirm_box
            if hasattr(self, "panel"):
                if self.panel.isVisible():
                    self.panel.hide()
                # ⭐ 確認框也隱藏
                if (
                    hasattr(self.panel, "confirm_box")
                    and self.panel.confirm_box.isVisible()
                ):
                    self.panel.confirm_box.hide()
            self.overlay.hide()

        self.overlay.mousePressEvent = on_overlay_clicked

        # 版本號（左下角）
        from app import AdminEfficiencyPilot as _AEP
        self._version_text = _AEP.VERSION
        self._online_count = None
        self._version_label = QLabel(self._version_text, self)
        self._version_label.setStyleSheet(
            "color: rgba(255,255,255,0.48); font-size: 11px; background: transparent;"
        )
        self._version_label.adjustSize()
        self._version_label.raise_()

        # 更新圖示（右下角）
        self._update_btn = QPushButton(self)
        self._update_btn.setFixedSize(52, 52)
        self._update_btn.setToolTip("檢查更新")
        self._update_btn.setCursor(Qt.PointingHandCursor)
        import os as _os, sys as _sys
        if getattr(_sys, "frozen", False):
            _base = _sys._MEIPASS
        else:
            _base = _os.path.dirname(_os.path.abspath(__file__))
        _icon_path = _os.path.join(_base, "icons", "settings.png")
        if _os.path.exists(_icon_path):
            self._update_btn.setIcon(QIcon(_icon_path))
            self._update_btn.setIconSize(QSize(34, 34))
        self._update_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 26px;
            }
            QPushButton:hover {
                background: rgba(0,0,0,0.12);
            }
        """)
        self._update_btn.clicked.connect(lambda: self._on_update_btn_clicked())
        self._update_btn.raise_()
        self._has_update = False
        self._latest_update_info = None  # (latest, changelog, url)
        # 初始定位
        QTimer.singleShot(0, lambda: self._update_btn.move(self.width() - self._update_btn.width() - 20, 6))

    def set_online_count(self, count):
        try:
            count = int(count)
            self._online_count = max(0, count)
            self._version_label.setText(f"{self._version_text} · 在線 {self._online_count} 人")
        except Exception:
            self._online_count = None
            self._version_label.setText(self._version_text)
        self._version_label.adjustSize()
        self.resizeEvent(None)

    def _on_update_btn_clicked(self):
        """手動點更新圖示：有新版直接跳視窗，沒有則重新觸發 MainWindow 檢查"""
        mw = self.window()
        if hasattr(mw, "_handle_update_btn"):
            mw._handle_update_btn()

    def _on_combo_activated(self):
        # ⭐ 選擇後立即隱藏下拉選單
        self.combo.hidePopup()
        # ⭐ 檢查是否有 panel 開啟
        if hasattr(self, "panel") and self.panel.isVisible():
            return  # 如果有 panel，不執行
        # 延遲執行 handle_start，避免卡頓
        QTimer.singleShot(100, self.handle_start)

    def add_account(self):
        panel = AddAccountPanel(self)
        panel.btn_ok.clicked.connect(self.save_account)
        panel.btn_cancel.clicked.connect(self.close_panel)
        self._show_panel(panel)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        h = self.height()
        self.bg_label.setGeometry(0, 0, w, h)

        # 動態按原 900x600 設計基準計算比例，確保毛玻璃手機框與背景手機螢幕永遠完美貼合
        rx = w / 900.0
        ry = h / 600.0
        sx = int(421 * rx)
        sy = int(132 * ry)
        sw = int(263 * rx)
        sh = int(473 * ry)

        self.account_container.setGeometry(sx, sy, sw, sh)

        if hasattr(self, "_version_label"):
            lw = self._version_label.width()
            lh = self._version_label.height()
            self._version_label.move(8, h - lh - 6)
        if hasattr(self, "_update_btn"):
            bw = self._update_btn.width()
            self._update_btn.move(w - bw - 20, 6)

    def delete_account(self):
        if not self.accounts:
            return

        panel = DeleteAccountPanel(self)
        panel.selector.clear()
        for acc in self.accounts:
            login_display = {"egov": "我的E政府", "taipei_eda": "臺北E大"}.get(acc.get("login_type"), "eCPA")
            panel.selector.addItem(f"{acc['name']}（{login_display}）")

        panel.btn_ok.clicked.connect(self.show_delete_confirm)
        panel.btn_cancel.clicked.connect(self.close_panel)
        self._show_panel(panel)

    def show_delete_confirm(self):
        selected = self.panel.selector.currentText()
        self.panel.confirm_label.setText(f"確定刪除 {selected}？")

        # ⭐ 設定確認框位置（panel 下方，貼近）
        panel_pos = self.panel.pos()
        confirm_x = panel_pos.x()
        confirm_y = panel_pos.y() + self.panel.height() + 8
        start_y = confirm_y + 40

        self.panel.confirm_box.move(confirm_x, start_y)
        self.panel.confirm_box.show()
        self.panel.confirm_box.raise_()

        # ⭐ 動畫滑入（從下方滑上來）
        confirm_anim = QPropertyAnimation(self.panel.confirm_box, b"pos")
        confirm_anim.setDuration(300)
        confirm_anim.setStartValue(QPoint(confirm_x, start_y))
        confirm_anim.setEndValue(QPoint(confirm_x, confirm_y))
        confirm_anim.start()

        # ⭐ 改成這樣，檢查是否已連接後再斷開
        try:
            self.panel.confirm_yes.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass

        try:
            self.panel.confirm_no.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass

        # 綁新事件
        self.panel.confirm_yes.clicked.connect(self.confirm_delete)
        self.panel.confirm_no.clicked.connect(lambda: self.panel.confirm_box.hide())

    def confirm_delete(self):
        idx = self.panel.selector.currentIndex()
        if idx < 0:
            return

        self.accounts.pop(idx)
        self.config["accounts"] = self.accounts

        self._save_config()

        self.refresh_combo()

        # ⭐ 修正：完全隱藏，清空 combo 選擇
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)

        self.panel.hide()
        self.panel.confirm_box.hide()
        self.overlay.hide()

    def handle_start(self):
        idx = self.combo.currentIndex()

        if idx == 0:
            return  # ⭐ 選到提示不做事

        # ⭐ 如果有 panel 開啟，則不執行
        if hasattr(self, "panel") and self.panel.isVisible():
            return

        account = self.accounts[idx - 1]  # ⭐ index 對齊
        self.on_start(account)

    def refresh_combo(self):
        self.combo.clear()

        self.combo.addItem("         請選擇人員")  # ⭐ 一定要加

        for acc in self.accounts:
            # ⭐ 轉換登入方式的顯示文字
            login_display = {"egov": "我的E政府", "taipei_eda": "臺北E大"}.get(acc.get("login_type"), "eCPA")
            self.combo.addItem(f"{acc['name']}（{login_display}）")

        self.combo.setCurrentIndex(0)

    def render_accounts(self, accounts):
        # ❌ 不要再動 layout
        pass

    def load_config(self):
        path = CONFIG_PATH

        if not os.path.exists(path):
            # 初始空設定
            data = {"accounts": [], "settings": {}}
            write_json_atomically(path, data)
            return data

        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {"accounts": [], "settings": {}}
            return json.loads(content)

    def _save_config(self) -> bool:
        """統一的設定儲存方法，含錯誤處理"""
        try:
            write_json_atomically(CONFIG_PATH, self.config)
            return True
        except (OSError, IOError) as e:
            logger.error(f"設定儲存失敗: {e}")
            return False

    def _show_panel(self, panel) -> None:
        """通用：顯示遮罩並以動畫滑入側邊欄"""
        self.panel = panel
        self.overlay.setGeometry(0, 0, self.width(), self.height())
        self.overlay.show()
        self.overlay.raise_()

        self.panel.move(self.width(), 100)
        self.panel.show()
        self.panel.raise_()

        self.anim = QPropertyAnimation(self.panel, b"pos")
        self.anim.setDuration(300)
        self.anim.setStartValue(QPoint(self.width(), 100))
        self.anim.setEndValue(QPoint(self.width() - 360, 100))
        self.anim.start()

    def save_account(self):
        new_data = self.panel.get_data()

        # 簡單檢查
        if not new_data["name"] or not new_data["account"] or not new_data["password"]:
            return

        self.accounts.append(new_data)
        self.config["accounts"] = self.accounts

        self._save_config()

        self.is_updating = True

        self.combo.blockSignals(True)
        self.refresh_combo()
        self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)

        self.is_updating = False

        self.panel.hide()  # ⭐ 關閉側邊欄
        self.overlay.hide()

    def edit_account(self):
        if not self.accounts:
            return

        panel = AddAccountPanel(self, data=self.accounts[0] if self.accounts else None)
        panel.btn_ok.clicked.connect(self.save_edit)
        panel.btn_cancel.clicked.connect(self.close_panel)
        self._show_panel(panel)

    def save_edit(self):
        new_data = self.panel.get_data()

        if not new_data["name"] or not new_data["account"] or not new_data["password"]:
            return

        # 👉 先簡單：改第一筆
        idx = self.panel.selector.currentIndex()
        self.accounts[idx] = new_data
        self.config["accounts"] = self.accounts

        self._save_config()

        self.refresh_combo()
        self.panel.hide()
        self.overlay.hide()

    def edit_settings(self):
        panel = SettingsPanel(self, data=self.config)
        panel.btn_ok.clicked.connect(self.save_settings)
        panel.btn_cancel.clicked.connect(self.close_panel)
        self._show_panel(panel)

    def save_settings(self):
        settings_data = self.panel.get_data()
        ai_key = settings_data.get("ai_api_key", "").strip()
        if ai_key:
            try:
                settings_data["ai_base_url"] = validate_ai_base_url(
                    settings_data.get("ai_provider", "OpenAI"),
                    settings_data.get("ai_base_url", ""),
                )
            except ValueError as exc:
                self.panel.show_ai_result(False, f"❌ {exc}")
                return

        self.config["settings"] = settings_data
        self._save_config()

        if ai_key:
            self.panel.show_ai_verifying()
            import threading, requests as _req
            def _verify():
                provider = settings_data.get("ai_provider", "OpenAI")
                base_url = settings_data.get("ai_base_url", "https://api.openai.com/v1").rstrip("/")
                model    = settings_data.get("ai_model", "gpt-4o-mini")
                ok, msg  = False, ""

                # Claude 用 x-api-key header，其他用 Bearer
                if provider == "Claude":
                    headers = {
                        "x-api-key":         ai_key,
                        "anthropic-version":  "2023-06-01",
                        "Content-Type":       "application/json",
                    }
                else:
                    headers = {"Authorization": f"Bearer {ai_key}"}

                try:
                    if provider == "自訂":
                        # 第一段：試打 /models
                        try:
                            r = _req.get(f"{base_url}/models", headers=headers, timeout=8)
                            if r.status_code == 200:
                                ok, msg = True, "✅ API Key 驗證成功"
                            elif r.status_code == 401:
                                ok, msg = False, "❌ API Key 無效（401）"
                            else:
                                # 第二段：試打 chat/completions
                                r2 = _req.post(
                                    f"{base_url}/chat/completions",
                                    headers={**headers, "Content-Type": "application/json"},
                                    json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                                    timeout=10,
                                )
                                if r2.status_code == 200:
                                    ok, msg = True, "✅ 連線成功（已儲存）"
                                elif r2.status_code == 401:
                                    ok, msg = False, "❌ API Key 無效（401）"
                                else:
                                    ok, msg = True, f"⚠️ 無法自動驗證，已儲存（HTTP {r2.status_code}）"
                        except Exception:
                            ok, msg = True, "⚠️ 無法自動驗證，已儲存"
                    elif provider == "Claude":
                        # Claude 用 chat/completions 測試
                        r = _req.post(
                            f"{base_url}/messages",
                            headers=headers,
                            json={"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
                            timeout=10,
                        )
                        if r.status_code == 200:
                            ok, msg = True, "✅ API Key 驗證成功"
                        elif r.status_code == 401:
                            ok, msg = False, "❌ API Key 無效（401）"
                        else:
                            ok, msg = False, f"❌ 驗證失敗（HTTP {r.status_code}）"
                    else:
                        r = _req.get(f"{base_url}/models", headers=headers, timeout=8)
                        if r.status_code == 200:
                            ok, msg = True, "✅ API Key 驗證成功"
                        elif r.status_code == 401:
                            ok, msg = False, "❌ API Key 無效（401）"
                        else:
                            ok, msg = False, f"❌ 驗證失敗（HTTP {r.status_code}）"
                except Exception as e:
                    ok, msg = False, f"❌ 無法連線：{e}"
                self._ai_verify_signal.emit(ok, msg)
            threading.Thread(target=_verify, daemon=True).start()
        else:
            self.panel.hide()
            self.overlay.hide()

    def close_panel(self):
        self.panel.hide()
        self.overlay.hide()

    def _on_ai_verify_done(self, ok: bool, msg: str):
        """AI key 驗證結果回到主執行緒"""
        if hasattr(self, "panel"):
            self.panel.show_ai_result(ok, msg)
            if ok:
                QTimer.singleShot(1500, lambda: (self.panel.hide(), self.overlay.hide()))


class AddAccountPanel(QFrame):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)

        # ===== 基本尺寸 =====
        self.setFixedSize(300, 400)

        # ===== 外觀（卡片）=====
        self.setStyleSheet("""
        QFrame {
            background-color: rgba(255,255,255,0.96);
            border-radius: 16px;
        }

        QLabel {
            color: #111827;
            font-size: 14px;
            background: transparent;
        }

        QLineEdit {
            background-color: transparent;
            border: none;
            border-bottom: 1px solid #D1D5DB;
            padding: 6px 2px;
        }

        QComboBox {
            background-color: transparent;
            border: none;
            border-bottom: 1px solid #D1D5DB;
            padding: 6px 2px;
            color: #111827;
        }

        QComboBox QAbstractItemView {
            background-color: #ffffff;
            color: #111827;
            selection-background-color: #EFF6FF;
            selection-color: #1D4ED8;
            border: 1px solid #D1D5DB;
            border-radius: 8px;
            padding: 4px;
        }

        QPushButton {
            background-color: #F3F4F6;
            border-radius: 12px;
            padding: 10px;
        }

        QPushButton:hover {
            background-color: #E5E7EB;
        }
        """)

        # ===== 陰影（右側浮出感）=====
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(-12, 0)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

        # ===== Layout =====
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ===== 標題 =====
        title = QLabel("新增帳號")

        # ⭐ 如果有 data → 代表是編輯
        if data:
            title.setText("編輯帳號")
        title.setAlignment(Qt.AlignCenter)  # ⭐ 置中
        title.setStyleSheet("""
            font-size:18px;
            font-weight:600;
            color:#111827;
            margin-bottom: 10px;
        """)
        layout.addWidget(title)
        # ===== 帳號選擇（編輯用）=====
        self.selector = QComboBox()
        self.selector.hide()  # 預設隱藏
        layout.addWidget(self.selector)

        layout.addSpacing(8)

        # ===== 表單 =====
        form = QFormLayout()
        form.setSpacing(10)

        self.name = QLineEdit()
        self.login_type = QComboBox()
        self.login_type.addItem("eCPA", "eCPA")
        self.login_type.addItem("我的E政府", "egov")
        self.login_type.addItem("臺北E大", "taipei_eda")
        self.account = QLineEdit()
        # ===== 密碼 + 眼睛 =====
        pw_container = QWidget()
        pw_layout = QHBoxLayout()
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.setSpacing(0)  # ⭐ 改成 0，移除間距

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)

        self.eye_btn = QPushButton("👁")
        self.eye_btn.setFixedSize(28, 28)  # ⭐ 改小一點
        self.eye_btn.setStyleSheet("""
            background: transparent;
            border: none;
            padding: 0px;
            margin: 0px;
        """)

        pw_layout.addWidget(self.password)
        pw_layout.addWidget(
            self.eye_btn, 0, Qt.AlignRight | Qt.AlignVCenter
        )  # ⭐ 靠右對齐

        pw_container.setLayout(pw_layout)  # ⭐ 最後再設定 layout
        form.addRow("名稱", self.name)
        form.addRow("登入方式", self.login_type)
        form.addRow("帳號", self.account)
        form.addRow("密碼", pw_container)  # ⭐ 加入容器到 form

        self.password.setEchoMode(QLineEdit.Password)

        layout.addLayout(form)

        # ===== 按鈕區 =====
        btn_row = QHBoxLayout()

        self.btn_ok = QPushButton("確定")
        self.btn_cancel = QPushButton("取消")
        self.btn_ok.setStyleSheet("""
            background-color: #2563EB;
            color: white;
            border-radius: 12px;
            padding: 10px 16px;
            font-size: 15px;
        """)

        self.btn_cancel.setStyleSheet("""
            background-color: rgba(0,0,0,0.05);
            border-radius: 12px;
            padding: 10px 16px;
            font-size: 15px;
        """)

        btn_row.addStretch()  # ⭐ 左空

        btn_row.addWidget(self.btn_ok)
        btn_row.addSpacing(12)
        btn_row.addWidget(self.btn_cancel)

        btn_row.addStretch()  # ⭐ 右空

        layout.addLayout(btn_row)

        # ===== 預設資料（編輯用）=====
        if data:
            # ⭐ 改標題
            title.setText("編輯帳號")

            # ⭐ 顯示下拉
            self.selector.show()

            # ⭐ 從 parent 拿帳號
            parent = self.parent()
            if parent and hasattr(parent, "accounts"):
                self.selector.clear()

                for acc in parent.accounts:
                    # 顯示格式：姓名（登入方式）
                    login_display = {
                        "egov": "我的E政府",
                        "taipei_eda": "臺北E大",
                    }.get(acc.get("login_type"), "eCPA")
                    self.selector.addItem(f"{acc['name']}（{login_display}）", acc)

            # ⭐ 預設選第一個
            if self.selector.count() > 0:
                self.selector.setCurrentIndex(0)
                self.load_data(self.selector.itemData(0))

            # ⭐ 切換帳號 → 更新表單
            self.selector.currentIndexChanged.connect(self.on_select_changed)

            # ===== 事件（先簡單關閉）=====
            self.btn_cancel.clicked.connect(self.hide)

        def toggle_password():
            if self.password.echoMode() == QLineEdit.Password:
                self.password.setEchoMode(QLineEdit.Normal)
                self.eye_btn.setText("🙈")  # ⭐ 關閉狀態
            else:
                self.password.setEchoMode(QLineEdit.Password)
                self.eye_btn.setText("👁")  # ⭐ 開啟狀態

        self.eye_btn.clicked.connect(toggle_password)
        self.eye_btn.setText("🙈")

    def get_data(self):
        return {
            "name":       self.name.text().strip(),
            "login_type": self.login_type.currentData(),
            "account":    self.account.text().strip(),
            "password":   self.password.text(),
        }

    def show_ai_verifying(self):
        self.btn_ok.setEnabled(False)
        self.ai_status.setStyleSheet("font-size: 12px; color: #888; background: transparent;")
        self.ai_status.setText("⏳ 驗證 API Key 中...")
        self.ai_status.show()

    def show_ai_result(self, ok: bool, msg: str):
        self.btn_ok.setEnabled(True)
        color = "#16a34a" if ok else "#dc2626"
        self.ai_status.setStyleSheet(f"font-size: 12px; color: {color}; background: transparent;")
        self.ai_status.setText(msg)
        self.ai_status.show()

    def load_data(self, data):
        self.name.setText(data.get("name", ""))

        value = data.get("login_type", "eCPA")
        index = self.login_type.findData(value)
        if index >= 0:
            self.login_type.setCurrentIndex(index)

        self.account.setText(data.get("account", ""))
        self.password.setText(data.get("password", ""))

    def on_select_changed(self, idx):
        data = self.selector.itemData(idx)
        if data:
            self.load_data(data)


class DeleteAccountPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

        # ===== 基本尺寸 =====
        self.setFixedSize(300, 200)

        # ===== 外觀（卡片）=====
        self.setStyleSheet("""
        QFrame {
            background-color: rgba(255,255,255,0.96);
            border-radius: 16px;
        }

        QLabel {
            color: #111827;
            font-size: 14px;
            background: transparent;
        }

        QComboBox {
            background-color: transparent;
            border: none;
            border-bottom: 1px solid #D1D5DB;
            padding: 6px 2px;
        }

        QPushButton {
            background-color: #F3F4F6;
            border-radius: 12px;
            padding: 10px;
        }

        QPushButton:hover {
            background-color: #E5E7EB;
        }
        """)

        # ===== 陰影（右側浮出感）=====
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(-12, 0)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

        # ===== Layout =====
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ===== 標題 =====
        title = QLabel("刪除帳號")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            font-size:18px;
            font-weight:600;
            color:#111827;
            margin-bottom: 10px;
        """)
        layout.addWidget(title)

        # ===== 帳號選擇 =====
        self.selector = QComboBox()
        layout.addWidget(self.selector)

        # ===== 按鈕區 =====
        btn_row = QHBoxLayout()

        self.btn_ok = QPushButton("刪除")
        self.btn_cancel = QPushButton("取消")

        self.btn_ok.setMinimumHeight(40)  # ⭐ 改成跟刪除 Panel 一樣
        self.btn_cancel.setMinimumHeight(40)  # ⭐ 改成跟刪除 Panel 一樣

        self.btn_ok.setStyleSheet("""
            background-color: #EF4444;
            color: white;
            border-radius: 12px;
            padding: 10px 16px;
        """)

        self.btn_cancel.setStyleSheet("""
            background-color: rgba(0,0,0,0.05);
            border-radius: 12px;
            padding: 10px 16px;
        """)

        btn_row.addStretch()
        btn_row.addWidget(self.btn_ok)
        btn_row.addSpacing(12)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch()

        layout.addLayout(btn_row)

        # ⭐ 確認框（獨立建立，設為 parent（EntryPage）的子元件）
        self.confirm_box = QFrame(parent)
        self.confirm_box.setFixedSize(
            self.width(), 120
        )  # ⭐ 改成 300x120（寬度同 panel）
        self.confirm_box.setStyleSheet("""
            QFrame {
                background-color: rgba(255,255,255,0.96);
                border-radius: 16px;
            }
            QPushButton {
                background-color: #F3F4F6;
                border-radius: 10px;
                padding: 8px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #E5E7EB;
            }
        """)

        # 陰影
        confirm_shadow = QGraphicsDropShadowEffect(self.confirm_box)
        confirm_shadow.setBlurRadius(40)
        confirm_shadow.setOffset(-12, 0)
        confirm_shadow.setColor(QColor(0, 0, 0, 80))
        self.confirm_box.setGraphicsEffect(confirm_shadow)

        confirm_layout = QVBoxLayout(self.confirm_box)
        confirm_layout.setContentsMargins(20, 15, 20, 15)
        confirm_layout.setSpacing(12)
        confirm_layout.setAlignment(Qt.AlignCenter)  # ⭐ 加這行

        self.confirm_label = QLabel("確定刪除？")
        self.confirm_label.setAlignment(Qt.AlignCenter)
        self.confirm_label.setStyleSheet("""
            color:#111827;
            font-size:14px;
            padding: 10px 12px;
            font-weight: 600;
            background-color: rgba(0,0,0,0.04);
            border-radius: 10px;
        """)

        confirm_btn_layout = QHBoxLayout()

        self.confirm_yes = QPushButton("確定")
        self.confirm_no = QPushButton("取消")

        self.confirm_yes.setMinimumHeight(46)  # ⭐ 改成跟刪除 Panel 一樣
        self.confirm_no.setMinimumHeight(46)  # ⭐ 改成跟刪除 Panel 一樣

        self.confirm_yes.setStyleSheet("""
            background-color: #2563EB;
            color: white;
            border-radius: 12px;
            padding: 10px 16px;
            font-size: 14px;
        """)

        self.confirm_no.setStyleSheet("""
            background-color: rgba(0,0,0,0.05);
            border-radius: 12px;
            padding: 10px 16px;
            font-size: 14px;
        """)

        # ⭐ 直接套用上面刪除 Panel 的邏輯
        confirm_btn_layout.addStretch()
        confirm_btn_layout.addWidget(self.confirm_yes)
        confirm_btn_layout.addSpacing(12)
        confirm_btn_layout.addWidget(self.confirm_no)
        confirm_btn_layout.addStretch()

        confirm_layout.addWidget(self.confirm_label)
        confirm_layout.addLayout(confirm_btn_layout)

        self.confirm_box.hide()


class SettingsPanel(QFrame):
    # 各服務預設值：(base_url, default_model, 申請連結)
    AI_PRESETS = {
        "OpenAI": ("https://api.openai.com/v1",                               "gpt-4o-mini",             "https://platform.openai.com/api-keys"),
        "Gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash-lite",   "https://aistudio.google.com/app/apikey"),
        "Claude": ("https://api.anthropic.com/v1",                            "claude-haiku-4-5",        "https://console.anthropic.com/settings/keys"),
        "Groq":   ("https://api.groq.com/openai/v1",                          "llama-3.1-8b-instant",    "https://console.groq.com/keys"),
        "自訂":   ("", "", ""),
    }

    def __init__(self, parent=None, data=None):
        super().__init__(parent)

        # ===== 基本尺寸 =====
        self.setFixedSize(320, 480)

        # ===== 外觀（卡片）=====
        self.setStyleSheet("""
        QFrame {
            background-color: #ffffff;
            border-radius: 16px;
        }

        QLabel {
            color: #374151;
            font-size: 13px;
            background: transparent;
        }

        QLineEdit {
            background: transparent;
            border: none;
            border-bottom: 1px solid #E5E7EB;
            padding: 5px 2px;
            color: #111827;
            font-size: 13px;
        }
        QLineEdit:focus { border-bottom: 1px solid #2563EB; }

        QComboBox {
            background: transparent;
            border: none;
            border-bottom: 1px solid #E5E7EB;
            padding: 5px 2px;
            color: #111827;
            font-size: 13px;
        }
        QComboBox QAbstractItemView {
            background: white;
            color: #111827;
            selection-background-color: #EFF6FF;
            selection-color: #1D4ED8;
            border: 1px solid #E5E7EB;
            outline: none;
        }

        QPushButton {
            background-color: #F3F4F6;
            border-radius: 10px;
            padding: 8px 16px;
            font-size: 13px;
            color: #374151;
        }
        QPushButton:hover { background-color: #E5E7EB; }
        """)

        # ===== 陰影（右側浮出感）=====
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(-12, 0)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.setGraphicsEffect(shadow)

        # ===== 主內容 Layout =====
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(0)

        # ===== 標題 =====
        title = QLabel("執行設定")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size:17px; font-weight:700; color:#111827; margin-bottom:16px;"
        )
        layout.addWidget(title)

        # ===== 輔助：section 小標 =====
        def _section(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "font-size:13px; font-weight:700; color:#374151;"
                "letter-spacing:0.3px; margin-top:10px; margin-bottom:2px;"
            )
            layout.addWidget(lbl)

        # ===== 輔助：一列（標籤 + 欄位 [+ 額外]）=====
        def _row(label_text, widget, extra=None):
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(64)
            lbl.setStyleSheet("font-size:13px; color:#6B7280;")
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            if extra:
                row.addWidget(extra)
            layout.addLayout(row)
            layout.addSpacing(10)

        # ===== 執行設定 =====
        _section("執行設定")

        self.headless = QComboBox()
        self.headless.addItem("背景執行", True)
        self.headless.addItem("顯示視窗", False)
        _row("模式", self.headless)

        self.residence = QLineEdit()
        self.residence.setPlaceholderText("預設 75")
        _row("停留秒數", self.residence)

        self.target = QLineEdit()
        self.target.setPlaceholderText("預設 1.05")
        _row("完成率", self.target)

        # ===== 分隔線 =====
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#F3F4F6; margin:4px 0;")
        layout.addWidget(sep)

        # ===== AI 補答設定 =====
        _section("AI 補答設定")

        self.ai_provider = QComboBox()
        for name in self.AI_PRESETS:
            self.ai_provider.addItem(name)

        self.ai_link = QLabel()
        self.ai_link.setOpenExternalLinks(True)
        self.ai_link.setFixedWidth(20)
        self.ai_link.setStyleSheet("font-size:15px; background:transparent;")
        _row("服務", self.ai_provider, self.ai_link)

        self.ai_base_url = QLineEdit()
        self.ai_base_url.setPlaceholderText("API Base URL")
        _row("Base URL", self.ai_base_url)

        self.ai_model = QLineEdit()
        self.ai_model.setPlaceholderText("模型名稱")
        _row("模型", self.ai_model)

        self.ai_key = QLineEdit()
        self.ai_key.setPlaceholderText("貼上 API Key")
        self.ai_key.setEchoMode(QLineEdit.Password)

        eye_btn = QPushButton("🙈")
        eye_btn.setFixedSize(26, 26)
        eye_btn.setStyleSheet(
            "QPushButton { background:transparent; border:none; font-size:14px; padding:0; }"
            "QPushButton:hover { background:transparent; }"
        )
        def _toggle_key_visibility():
            if self.ai_key.echoMode() == QLineEdit.Password:
                self.ai_key.setEchoMode(QLineEdit.Normal)
                eye_btn.setText("👁")
            else:
                self.ai_key.setEchoMode(QLineEdit.Password)
                eye_btn.setText("🙈")
        eye_btn.clicked.connect(_toggle_key_visibility)
        _row("API Key", self.ai_key, eye_btn)

        # ===== AI 驗證狀態 =====
        self.ai_status = QLabel("")
        self.ai_status.setAlignment(Qt.AlignCenter)
        self.ai_status.setWordWrap(True)
        self.ai_status.setStyleSheet("font-size:12px; color:#555; background:transparent;")
        self.ai_status.hide()
        layout.addWidget(self.ai_status)

        layout.addSpacing(12)
        btn_row = QHBoxLayout()
        self.btn_cancel = QPushButton("取消")
        self.btn_ok = QPushButton("確定")
        self.btn_ok.setStyleSheet("""
            QPushButton { background:#2563EB; color:white; border-radius:10px;
                          padding:8px 16px; font-size:13px; font-weight:600; }
            QPushButton:hover { background:#1D4ED8; }
        """)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_cancel)
        btn_row.addSpacing(8)
        btn_row.addWidget(self.btn_ok)
        layout.addLayout(btn_row)

        # ===== 選服務時自動填入 =====
        self._loading_settings = False
        self._ai_keys = {}

        def _on_provider_changed(idx):
            name = self.ai_provider.currentText()
            url, model, link = self.AI_PRESETS[name]
            self.ai_base_url.setReadOnly(name != "自訂")
            self.ai_model.setReadOnly(name != "自訂" and model != "")
            self.ai_key.setText(self._ai_keys.get(name, ""))
            if name == "Gemini":
                from PySide6.QtGui import QFontMetrics
                fm = QFontMetrics(self.ai_base_url.font())
                available = self.ai_base_url.width() - 12
                self.ai_base_url.setText(fm.elidedText(url, Qt.ElideRight, available))
            else:
                self.ai_base_url.setText(url)
            self.ai_model.setText(model)
            if link:
                self.ai_link.setText(
                    f'<a href="{link}" style="color:#2563EB;text-decoration:none;">🔗</a>'
                )
                self.ai_link.show()
            else:
                self.ai_link.hide()

        self.ai_provider.currentIndexChanged.connect(_on_provider_changed)
        _on_provider_changed(0)

        # ===== 預設值 =====
        if data:
            settings = data.get("settings", {})

            headless_value = settings.get("headless", True)
            self.headless.setCurrentIndex(0 if headless_value else 1)

            self.residence.setText(str(settings.get("residence_time", 75)))
            self.target.setText(str(settings.get("target_percentage", 1.05)))

            # 還原各服務 key（相容舊格式）
            self._ai_keys = settings.get("ai_keys", {})
            if not self._ai_keys and settings.get("ai_api_key"):
                saved_p = settings.get("ai_provider", "OpenAI")
                self._ai_keys = {saved_p: settings["ai_api_key"]}

            self._loading_settings = True
            saved_provider = settings.get("ai_provider", "OpenAI")
            idx = self.ai_provider.findText(saved_provider)
            if idx >= 0:
                self.ai_provider.setCurrentIndex(idx)
            _on_provider_changed(self.ai_provider.currentIndex())
            self._loading_settings = False

            if saved_provider == "自訂":
                self.ai_base_url.setText(settings.get("ai_base_url", ""))
                self.ai_model.setText(settings.get("ai_model", ""))

    def get_data(self):
        provider = self.ai_provider.currentText()
        url, model, _ = self.AI_PRESETS[provider]
        # 非自訂服務一律用預設完整 URL，避免存入截斷的顯示文字
        actual_url = self.ai_base_url.text().strip() if provider == "自訂" else url
        actual_model = self.ai_model.text().strip() if provider == "自訂" else model
        # 將目前 key 寫回 _ai_keys dict
        current_key = self.ai_key.text().strip()
        if current_key:
            self._ai_keys[provider] = current_key
        return {
            "headless":           self.headless.currentData(),
            "residence_time":     int(self.residence.text() or 75),
            "target_percentage":  float(self.target.text() or 1.05),
            "ai_provider":        provider,
            "ai_base_url":        actual_url,
            "ai_model":           actual_model,
            "ai_api_key":         current_key,   # 相容舊格式
            "ai_keys":            dict(self._ai_keys),  # 各服務 key
        }

    def show_ai_verifying(self):
        self.btn_ok.setEnabled(False)
        self.ai_status.setStyleSheet("font-size: 12px; color: #888; background: transparent;")
        self.ai_status.setText("⏳ 驗證 API Key 中...")
        self.ai_status.show()

    def show_ai_result(self, ok: bool, msg: str):
        self.btn_ok.setEnabled(True)
        color = "#16a34a" if ok else "#dc2626"
        self.ai_status.setStyleSheet(f"font-size: 12px; color: {color}; background: transparent;")
        self.ai_status.setText(msg)
        self.ai_status.show()


# =========================
# 版本更新通知 Signal
# =========================
from PySide6.QtCore import QObject

class UpdateSignal(QObject):
    # (latest_version, changelog, download_url, file_size_bytes, sha256_digest)
    notify = Signal(str, str, str, int, str)
    up_to_date = Signal()           # 已是最新版

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
        header.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4fc3f7,stop:1 #0288d1);")
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
            background: #e3f2fd;
            border-radius: 8px;
            color: #0288d1;
            font-size: 22px;
            font-weight: bold;
            qproperty-alignment: AlignCenter;
        """)
        icon_lbl.setText("⬇")
        title_row.addWidget(icon_lbl)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel(f"新版本 {self.latest} 可用")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #0277bd;")
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
                background: #0288d1; color: #fff; font-weight: bold;
                border-radius: 6px; padding: 0 22px; font-size: 13px;
                border: none;
            }
            QPushButton:hover { background: #0277bd; }
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
            QMessageBox.warning(
                self, "無法自動更新",
                "自動更新僅支援新版 Portable 目錄結構，請至 GitHub Releases 手動下載。"
            )
            return
        if not self.expected_sha256:
            QMessageBox.warning(self, "缺少完整性摘要", "此 Release 未提供 SHA-256 digest，禁止自動安裝。")
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
            self._on_failed(f"無法啟動更新程序：{e}")
            return

        self.accept()
        QApplication.processEvents()
        QApplication.quit()
        sys.exit(0)


# =========================
# 全域人機協同排隊鎖（防範雙開模態事件循環衝突與閃退）
# =========================
GLOBAL_QUIZ_DIALOG_LOCK = threading.Lock()


# =========================
# 人機協同測驗助理彈窗
# =========================
class InteractiveQuizDialog(QDialog):
    """遇到測驗時彈出的人機協同作答助理（支援一鍵複製 Prompt、答案貼上解析與逾時自動跳過）"""

    def __init__(self, course_name: str, questions_data: list, timeout_sec: int = 180, parent=None):
        super().__init__(parent)
        self.course_name = course_name
        self.questions_data = questions_data
        self.timeout_sec = timeout_sec
        self.remaining_sec = timeout_sec
        self.is_paused = False
        self.parsed_result = None

        self.setWindowTitle(f"📝 測驗作答助理 - {course_name}")
        self.resize(880, 620)
        self.setModal(True)

        self.prompt_text = format_quiz_prompt(course_name, questions_data)
        self._init_ui()

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
        self.submit_btn = QPushButton("🚀 解析並自動填入考卷")
        self.submit_btn.setStyleSheet("""
            QPushButton {
                background: #10B981; color: #FFFFFF; font-weight: bold; font-size: 14px;
                padding: 10px 24px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background: #059669; }
            QPushButton:disabled { background: #A7F3D0; color: #065F46; }
        """)
        self.submit_btn.clicked.connect(self._submit)

        self.pause_btn = QPushButton("⏸️ 暫停倒數")
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background: #F59E0B; color: #FFFFFF; font-weight: bold; font-size: 13px;
                padding: 10px 16px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background: #D97706; }
        """)
        self.pause_btn.clicked.connect(self._toggle_pause)

        self.skip_btn = QPushButton("⏭️ 立即跳過測驗")
        self.skip_btn.setStyleSheet("""
            QPushButton {
                background: #6B7280; color: #FFFFFF; font-weight: bold; font-size: 13px;
                padding: 10px 16px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background: #4B5563; }
        """)
        self.skip_btn.clicked.connect(self._skip)

        bottom_bar.addWidget(self.submit_btn)
        bottom_bar.addWidget(self.pause_btn)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.skip_btn)
        layout.addLayout(bottom_bar)

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
            skip_btn = msg_box.addButton("⏩ 跳過此測驗並繼續", QMessageBox.ActionRole)
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
                self.parsed_result = None
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
                os.startfile(url)
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
            QMessageBox.warning(self, "提示", "請先在右側回貼區貼上 AI 回覆的答案！")
            return
        parsed = parse_ai_quiz_answers(raw, self.questions_data)
        if not parsed:
            QMessageBox.warning(
                self, "解析提示", "未能從貼上的內容中辨識出題號與選項代號，請檢查格式是否包含題號（如 1. B, 2. ⭕ 等）！"
            )
            return
        self.parsed_result = parsed
        self.timer.stop()
        self.accept()

    def _skip(self):
        self.parsed_result = None
        self.timer.stop()
        self.reject()


# =========================
# 主執行頁面
# =========================
from PySide6.QtWidgets import QTabWidget

class PlatformTabPanel(QWidget):
    log_signal = Signal(str)
    quiz_interactive_signal = Signal(str, list, int, object)

    def __init__(self, platform_key, platform_title, on_start, on_stop, on_toggle_browser):
        super().__init__()
        self.platform_key = platform_key
        self.platform_title = platform_title
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_toggle_browser = on_toggle_browser
        self.browser_visible = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 莫蘭迪灰階進度與統計卡片
        progress_card = QFrame()
        progress_card.setObjectName("progressCard")
        progress_card.setStyleSheet("""
            QFrame#progressCard {
                background: #FAF9F6;
                border: 1px solid #D6D3CC;
                border-radius: 10px;
                padding: 6px 12px;
            }
            QFrame#progressCard QLabel {
                color: #2F3B43; font-size: 13px; font-weight: bold; background: transparent;
                border: none;
            }
        """)
        progress_content = QVBoxLayout(progress_card)
        progress_content.setContentsMargins(8, 6, 8, 6)
        progress_content.setSpacing(4)
        prog_layout = QHBoxLayout()
        prog_layout.setContentsMargins(0, 0, 0, 0)

        self.stats_lbl = QLabel("📊 研習時數與課程進度：準備就緒")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #E4E0DA;
                border: 1px solid #C9C5BE;
                border-radius: 8px;
                text-align: center;
                color: #26343C;
                font-weight: bold;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #70889B, stop:1 #7F9A88);
                border-radius: 7px;
            }
        """)

        prog_layout.addWidget(self.stats_lbl)
        prog_layout.addStretch()
        prog_layout.addWidget(self.progress_bar)
        self.execution_status_lbl = QLabel("● 待命：尚未開始本次執行")
        self.execution_status_lbl.setStyleSheet(
            "color: #66737D; font-size: 12px; font-weight: 600; background: transparent; border: none;"
        )
        progress_content.addLayout(prog_layout)
        progress_content.addWidget(self.execution_status_lbl)
        layout.addWidget(progress_card)

        # 操作列：主要動作與本次選項分開，避免視窗較窄時過度擁擠。
        btn_bar = QHBoxLayout()
        self.info_lbl = QLabel(f"{platform_title}控制台")
        self.info_lbl.setStyleSheet("color: #2F3B43; font-weight: 700; font-size: 15px; background: transparent; border: none;")

        self.exam_mode_combo = QComboBox()
        self.exam_mode_combo.addItem("自動作答（題庫優先）", "auto")
        self.exam_mode_combo.addItem("人機協同作答（彈窗回貼）", "interactive")
        self.exam_mode_combo.addItem("跳過測驗，先填問卷", "skip")
        self.exam_mode_combo.setToolTip(
            "僅套用於本次執行。自動作答會優先使用題庫；人機協同會開啟題目複製與答案回貼視窗；跳過測驗不會把課程視為完成。"
        )
        self.exam_mode_combo.setMinimumWidth(250)
        self.exam_mode_combo.setStyleSheet("""
            QComboBox {
                background: #FAF9F6; color: #2F3B43;
                border: 1px solid #B9B5AE; border-radius: 7px;
                padding: 8px 32px 8px 11px; font-size: 13px; font-weight: 600;
            }
            QComboBox:hover { border-color: #70889B; background: #F4F2EE; }
            QComboBox:disabled { background: #E4E0DA; color: #88847E; }
            QComboBox QAbstractItemView {
                background: #FAF9F6; color: #2F3B43;
                selection-background-color: #70889B; selection-color: #FFFFFF;
                border: 1px solid #B9B5AE;
            }
        """)

        self.start_btn = QPushButton("▶️ 開始此平台")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: #6F917B; color: #FFFFFF; border-radius: 8px;
                padding: 9px 18px; font-weight: bold; font-size: 14px; border: none;
            }
            QPushButton:hover { background: #5D7D69; }
        """)
        self.start_btn.clicked.connect(self._handle_start)

        self.stop_btn = QPushButton("⏹ 停止此平台")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background: #A96F6B; color: #FFFFFF; border-radius: 8px;
                padding: 9px 18px; font-weight: bold; font-size: 14px; border: none;
            }
            QPushButton:hover { background: #925D59; }
            QPushButton:disabled { background: #DDD9D3; color: #8A8782; }
        """)
        self.stop_btn.clicked.connect(self._handle_stop)
        self.stop_btn.setEnabled(False)

        self.toggle_browser_btn = QPushButton("👁️ 顯示瀏覽器")
        self.toggle_browser_btn.setStyleSheet("""
            QPushButton {
                background: #748399; color: #FFFFFF; border-radius: 8px;
                padding: 9px 18px; font-weight: bold; font-size: 14px; border: none;
            }
            QPushButton:hover { background: #657489; }
        """)
        self.toggle_browser_btn.clicked.connect(self._handle_toggle_browser)

        btn_bar.addWidget(self.info_lbl)
        btn_bar.addStretch()
        btn_bar.addWidget(self.start_btn)
        btn_bar.addWidget(self.stop_btn)
        btn_bar.addWidget(self.toggle_browser_btn)
        layout.addLayout(btn_bar)

        option_card = QFrame()
        option_card.setObjectName("examModeCard")
        option_card.setStyleSheet("""
            QFrame#examModeCard { background: #F5F2ED; border: 1px solid #D6D1C9; border-radius: 9px; }
            QFrame#examModeCard QLabel { color: #35434C; background: transparent; border: none; }
        """)
        option_layout = QVBoxLayout(option_card)
        option_layout.setContentsMargins(14, 8, 14, 8)
        option_layout.setSpacing(3)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        mode_label = QLabel("本次測驗處理方式")
        mode_label.setStyleSheet("color: #35434C; font-size: 13px; font-weight: 700; background: transparent; border: none;")
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.exam_mode_combo)
        mode_row.addStretch()
        option_layout.addLayout(mode_row)
        mode_hint = QLabel("僅影響這次執行，不會改變帳號設定")
        mode_hint.setStyleSheet("color: #6B777F; font-size: 12px; font-weight: 500; background: transparent; border: none;")
        option_layout.addWidget(mode_hint)
        layout.addWidget(option_card)

        # Log 視窗
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(300)
        self.log_view.setStyleSheet("""
            QTextEdit {
                background-color: #26333B;
                border: 1px solid #36464F;
                border-radius: 12px;
                color: #F7F4EE;
                font-family: 'Cascadia Mono', 'Microsoft JhengHei UI', 'Segoe UI', monospace;
                font-size: 13px;
                padding: 12px;
            }
            QScrollBar:vertical {
                background: #26333B;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #596A73;
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: #71848E;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        layout.addWidget(self.log_view)

        self.log_signal.connect(self._append_text_safe)
        self.quiz_interactive_signal.connect(self._handle_quiz_interactive_request)

    def _handle_quiz_interactive_request(self, course_name, questions_data, timeout_sec, holder):
        event, res_holder = holder
        try:
            # 🔒 全域排隊互斥鎖：確保雙開時同一時間僅有一個測驗助理彈窗，徹底防範 Qt 巢狀事件循環閃退
            with GLOBAL_QUIZ_DIALOG_LOCK:
                dlg = InteractiveQuizDialog(course_name, questions_data, timeout_sec, parent=self)
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
        display_acc = f" / {account.strip()}" if account and account.strip() else ""
        self.info_lbl.setText(f"{self.platform_title}控制台（使用者：{display_name}{display_acc}）")

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
        else:
            text = message or "● 待命：尚未開始本次執行"
            color = "#66737D"
        self.execution_status_lbl.setText(text)
        self.execution_status_lbl.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 700; background: transparent;"
        )

    def _handle_toggle_browser(self):
        self.browser_visible = not self.browser_visible
        if self.browser_visible:
            self.toggle_browser_btn.setText("🙈 隱藏瀏覽器")
            self.toggle_browser_btn.setStyleSheet("""
                QPushButton {
                    background: #8A8076; color: #FFFFFF; border-radius: 8px;
                    padding: 8px 16px; font-weight: bold; font-size: 13px; border: none;
                }
                QPushButton:hover { background: #746A61; }
            """)
        else:
            self.toggle_browser_btn.setText("👁️ 顯示瀏覽器")
            self.toggle_browser_btn.setStyleSheet("""
                QPushButton {
                    background: #78869A; color: #FFFFFF; border-radius: 8px;
                    padding: 8px 16px; font-weight: bold; font-size: 13px; border: none;
                }
                QPushButton:hover { background: #657489; }
            """)
        if self.on_toggle_browser:
            self.on_toggle_browser(self.platform_key, self.browser_visible)

    def append_text(self, text):
        self.log_signal.emit(text)

    def _format_taipei_log_line(self, text):
        raw = (text or "").strip()
        if not raw or re.fullmatch(r"[-=─\s]{8,}", raw) or raw.startswith("SCORM URL:") or raw.startswith("Player URL:"):
            return None
        replacements = [
            (r"^===\s*登入\s*===$", "INFO", "🔑 正在登入臺北E大..."),
            (r"^===\s*掃描課程清單\s*===$", "INFO", "📋 正在掃描課程清單..."),
            (r"^===\s*最終課程狀態\s*===$", "INFO", "📋 最終課程狀態"),
            (r"^Login OK\b.*", "INFO", "✅ 臺北E大登入成功"),
            (r"^登入失敗$", "ERROR", "❌ 臺北E大登入失敗"),
            (r"^沒有未完成課程！$", "INFO", "✅ 沒有未完成課程"),
            (r"^完成！$", "INFO", "🏆 臺北E大所有任務完成！"),
        ]
        for pattern, level, msg in replacements:
            if re.match(pattern, raw):
                return level, msg
        if "⚠️" in raw:
            return "WARNING", raw
        return "INFO", raw

    def _append_text_safe(self, text):
        text = re.sub(r"\x1b\[[0-9;]*m", "", text)
        m = re.match(r"(\d{2}:\d{2}:\d{2}) \[(.*?)\] (.*)", text)

        def esc(s):
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if m:
            time_part, level_part, msg_part = m.groups()
        else:
            formatted = self._format_taipei_log_line(text)
            if not formatted:
                return
            level_part, msg_part = formatted
            time_part = datetime.now().strftime("%H:%M:%S")

        if any(k in msg_part for k in ["所有任務圓滿達成", "所有任務完成", "流程未完整完成"]):
            self.set_running_state(False, "● 本次流程已結束，可再次開始執行")

        # 🧠 Log 智慧進度攔截器 (Auto Progress Interceptor)
        try:
            # 1. 攔截總課程門數進度：例如 "[3/10] 正在協助研習：..."
            m_course = re.search(r"\[(\d+)/(\d+)\]\s*(.*)", msg_part)
            if m_course:
                c_curr, c_tot, c_name = int(m_course.group(1)), int(m_course.group(2)), m_course.group(3).strip()
                pct = int((c_curr / c_tot) * 100) if c_tot > 0 else 0
                self.progress_bar.setValue(pct)
                self.stats_lbl.setText(f"📊 研習進度：{c_curr} / {c_tot} 門 ({pct}%) - 正在處理: {c_name[:12]}...")

            # 2. 攔截單門課程觀看時數與趴數：例如 "研習進度：00:28:55 / 02:06:00 [----] 22.9%"
            m_time = re.search(r"研習進度\s*[:：]\s*(\d{2}:\d{2}:\d{2}\s*/\s*\d{2}:\d{2}:\d{2}).*?([\d\.]+)%", msg_part)
            if m_time:
                time_str, pct_float = m_time.group(1), float(m_time.group(2))
                pct_int = min(100, max(0, int(pct_float)))
                # 實時無條件動態驅動右側進度條！
                self.progress_bar.setValue(pct_int)
                self.stats_lbl.setText(f"📊 本課程研習時數：{time_str} ({pct_float:.1f}%)")

            # 3. 攔截「進入單元...」
            m_unit = re.search(r"進入單元\s*[:：]\s*(.*)", msg_part)
            if m_unit:
                unit_name = m_unit.group(1).strip()
                cur_text = self.stats_lbl.text()
                if "研習進度" in cur_text:
                    prefix = cur_text.split(" - ")[0]
                    self.stats_lbl.setText(f"{prefix} - 單元: {unit_name[:10]}...")
        except Exception:
            pass

        level_colors = {
            "INFO": "#8DB7C6",
            "WARNING": "#D7AD75",
            "WARN": "#D7AD75",
            "ERROR": "#D8918C",
            "CRITICAL": "#D67F82",
            "DEBUG": "#B1B7BA",
        }
        level_color = level_colors.get(level_part, "#B1B7BA")

        # 動態判斷訊息內容高亮顏色
        msg_color = "#F4F1EB"
        if any(k in msg_part for k in ["✅", "🏆", "成功", "圓滿達成", "完成"]):
            msg_color = "#9CC4A8"
        elif any(k in msg_part for k in ["⚠️", "警告", "重試", "失敗", "跳過"]):
            msg_color = "#DFC184"
        elif "研習進度" in msg_part or "時數" in msg_part:
            msg_color = "#A5BDD3"

        html = (
            f'<span style="color:#D8B576; font-weight:600; font-family:\'Consolas\',monospace;">{esc(time_part)}</span> '
            f'<span style="color:{level_color}; font-weight:bold;">[{esc(level_part)}]</span> '
            f'<span style="color:{msg_color}; font-family:\'Consolas\',monospace;">{esc(msg_part)}</span>'
        )

        self.log_view.append(html)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())


class AccountSettingsTabPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        lbl = QLabel("⚙️ 帳號管理與系統設定")
        lbl.setStyleSheet("color: #2F3B43; font-weight: bold; font-size: 16px; background: transparent;")
        lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lbl.setFixedHeight(30)
        layout.addWidget(lbl)

        form_card = QFrame()
        form_card.setObjectName("accountSettingsCard")
        form_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        form_card.setStyleSheet("""
            QFrame#accountSettingsCard {
                background: #FAF9F6;
                border: 1px solid #D6D3CC;
                border-radius: 12px;
                padding: 20px;
            }
            QFrame#accountSettingsCard QLabel {
                color: #35434C;
                font-weight: bold;
                font-size: 13px;
                background: transparent;
                border: none;
                min-height: 28px;
                padding: 2px 0px;
            }
        """)
        form_layout = QFormLayout(form_card)
        form_layout.setSpacing(14)
        form_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        input_style = """
            QLineEdit, QComboBox {
                background: #F3F1ED;
                color: #2F3B43;
                border: 1px solid #BDB9B2;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                min-height: 20px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 2px solid #70889B;
                background: #FAF9F6;
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

        self.headless_cb = QCheckBox("隱藏瀏覽器視窗（背景執行）")
        self.headless_cb.setToolTip("勾選後瀏覽器不顯示在桌面；課程仍會在背景執行。")
        self.headless_cb.setStyleSheet("""
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
        """)

        self.ai_key_input = QLineEdit()
        self.ai_key_input.setEchoMode(QLineEdit.Password)
        self.ai_key_input.setPlaceholderText("選填；未填時只使用本機題庫，不會呼叫 AI")
        self.ai_key_input.setStyleSheet(input_style)

        form_layout.addRow(QLabel("臺北E大名稱:"), self.name_input)
        form_layout.addRow(QLabel("臺北E大帳號:"), self.acc_input)
        form_layout.addRow(QLabel("臺北E大密碼:"), self.pwd_input)
        form_layout.addRow(QLabel("e等顯示名稱:"), self.egov_name_input)
        form_layout.addRow(QLabel("e等登入方式:"), self.egov_type_combo)
        form_layout.addRow(QLabel("e等登入帳號:"), self.egov_acc_input)
        form_layout.addRow(QLabel("e等登入密碼:"), self.egov_pwd_input)
        form_layout.addRow(QLabel("執行模式:"), self.headless_cb)
        form_layout.addRow(QLabel("Gemini API Key（選填）:"), self.ai_key_input)

        layout.addWidget(form_card)

        btn_bar = QHBoxLayout()
        self.save_btn = QPushButton("💾 儲存並套用設定")
        self.save_btn.setStyleSheet("""
            QPushButton {
                background: #70889B; color: #FFFFFF; border-radius: 8px;
                padding: 10px 24px; font-weight: bold; font-size: 14px; border: none;
            }
            QPushButton:hover { background: #60798D; }
        """)
        self.save_btn.clicked.connect(self.save_settings)
        btn_bar.addStretch()
        btn_bar.addWidget(self.save_btn)
        layout.addLayout(btn_bar)
        # 多出的垂直空間放在底部，不把標題與表單推開。
        layout.addStretch(1)

        self.load_settings()

    def load_settings(self):
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
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
                self.ai_key_input.setText(settings.get("ai_api_key", ""))
        except Exception:
            pass

    def save_settings(self):
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"accounts": [], "settings": {}}

            taipei_account = self.acc_input.text().strip()
            taipei_password = self.pwd_input.text()
            egov_account = self.egov_acc_input.text().strip()
            egov_password = self.egov_pwd_input.text()

            if bool(taipei_account) != bool(taipei_password):
                QMessageBox.warning(self, "設定未完成", "臺北E大帳號與密碼必須同時填寫。")
                return
            if bool(egov_account) != bool(egov_password):
                QMessageBox.warning(self, "設定未完成", "e等公務員帳號與密碼必須同時填寫。")
                return

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
                QMessageBox.warning(self, "設定未完成", "請至少設定一個平台的帳號與密碼。")
                return
            data["accounts"] = accounts

            settings = data.get("settings", {})
            settings["headless"] = self.headless_cb.isChecked()
            ai_key = self.ai_key_input.text().strip()
            if ai_key:
                settings["ai_api_key"] = ai_key
                settings["ai_provider"] = "Gemini"
                if "ai_keys" not in settings:
                    settings["ai_keys"] = {}
                settings["ai_keys"]["Gemini"] = ai_key
            data["settings"] = settings

            write_json_atomically(CONFIG_PATH, data)

            if hasattr(self, "on_settings_saved") and callable(self.on_settings_saved):
                self.on_settings_saved()

            QMessageBox.information(self, "成功", "✅ 帳號與系統設定已成功儲存並套用！")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"❌ 儲存失敗：{e}")


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
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 頂部控制列
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        title_lbl = QLabel("行政效能領航員 - 控制中心")
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

        self.account_mgr_btn = QPushButton("⚙️ 帳號與系統設定")
        self.account_mgr_btn.setStyleSheet("""
            QPushButton {
                background: #FAF9F6; color: #2F3B43; border-radius: 8px;
                padding: 9px 16px; font-weight: bold; font-size: 14px; border: 1px solid #C9C5BE;
            }
            QPushButton:hover { background: #E9E5DF; }
        """)
        self.account_mgr_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(2))

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
        top_bar.addWidget(self.account_mgr_btn)
        top_bar.addWidget(self.check_update_btn)
        root.addLayout(top_bar)

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

        self.stack = QStackedLayout(self)

        self.entry = EntryPage(self.go_immersive)
        self.immersive = ImmersivePage(self._stop_all_platforms)

        # 綁定頁籤與按鈕事件
        self.immersive.on_start_platform = self._start_single_platform
        self.immersive.on_stop_platform = self._stop_single_platform
        self.immersive.on_toggle_browser = self._toggle_platform_browser
        self.immersive.on_start_all = self._start_all_platforms
        self.immersive.on_check_update = self._handle_manual_check_update

        self.resize(1000, 650)
        self.setMinimumSize(950, 620)

        self.stack.addWidget(self.immersive)

        # 預設展示多頁籤控制中心
        self.stack.setCurrentWidget(self.immersive)
        self.immersive.start("預設使用者")

        self.taipei_pilot = None
        self.taipei_thread = None
        self.egov_pilot = None
        self.egov_thread = None
        self.cleanup_thread = None

        self.usage_signal = UsageSignal()
        self.usage_signal.online.connect(self.entry.set_online_count)
        self.usage = UsageHeartbeat(AdminEfficiencyPilot.VERSION, self._on_usage_stats)
        self.usage.start()

        # 啟動時背景檢查更新
        self._run_startup_update_check()

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
        """最小化視窗時，自動隱藏視窗縮至右下角系統列"""
        if event.type() == event.Type.WindowStateChange:
            if self.isMinimized():
                if hasattr(self, "tray_icon") and self.tray_icon.isVisible():
                    QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def quit_app(self):
        """完全退出程式並釋放所有資源"""
        self._stop_all_platforms()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        QApplication.quit()

    def _start_single_platform(self, key):
        config_from_entry = self.entry.load_config()
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
        # 🔒 實時讀取 UI 最新『背景執行』勾選狀態，避免設定未寫入檔案導致網頁視窗彈出！
        full_config["headless"] = self.immersive.settings_panel.headless_cb.isChecked()
        panel = self.immersive.taipei_panel if key == "taipei_eda" else self.immersive.egov_panel
        exam_mode = panel.exam_mode_combo.currentData() or "auto"
        full_config["skip_exam_for_session"] = exam_mode == "skip"
        full_config["interactive_quiz_for_session"] = exam_mode == "interactive"
        if full_config["skip_exam_for_session"]:
            logger.info("本次執行已啟用「跳過測驗，先做問卷」模式。")
        elif full_config["interactive_quiz_for_session"]:
            logger.info("本次執行已啟用「人機協同作答（彈窗回貼）」模式。")
        else:
            logger.info("本次執行採用「自動作答（題庫優先）」模式。")

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

    def go_immersive(self, account_data):
        """轉到沈浸頁面，帶粒子效果"""
        self.show_particle_transition(account_data)

    def show_particle_transition(self, account_data):
        """直接切換到學習頁面並啟動引擎"""
        self._start_pilot_background(account_data)
        self.start_learning(account_data)

    def _cleanup_particle(self):
        """移除粒子效果層"""
        if self.particle_effect:
            self.particle_effect.hide()
            self.particle_effect.deleteLater()
            self.particle_effect = None

    def _request_stop_current_pilot(self):
        if hasattr(self, "pilot") and self.pilot:
            self.pilot.running = False
            try:
                self.pilot._cleanup()
            except Exception:
                pass

    def _start_pilot_background(self, account_data):
        """在後臺啟動 pilot 程式"""
        self._request_stop_current_pilot()

        # ⭐ 從 entry 的配置中讀取完整配置
        config_from_entry = self.entry.load_config()

        # ⭐ 找到對應的賬戶，並添加 settings
        full_config = account_data.copy()
        full_config.update(config_from_entry.get("settings", {}))
        if hasattr(self, "usage"):
            self.usage.update_context("learning", full_config.get("login_type", ""))

        # ⭐ 調試（遮蔽敏感欄位）
        _safe = {k: ("***" if "key" in k.lower() or "password" in k.lower() else v) for k, v in full_config.items()}
        logger.info(f"DEBUG: 最終配置 = {_safe}")

        self.pilot = AdminEfficiencyPilot(
            config_override=full_config, log_callback=self.immersive.append_text
        )

        # 版本更新通知
        self.pilot.update_signal = UpdateSignal()
        self.pilot.update_signal.notify.connect(self._on_update_available)
        self.pilot.running = True

        self.thread = threading.Thread(target=self.pilot.run, daemon=True)
        self.thread.start()

    def start_learning(self, account_data):
        """動畫播到一半，切換到學習頁面"""
        self.stack.setCurrentWidget(self.immersive)
        self.immersive.start(account_data["name"])
        self.setFixedSize(self.size())
        self.immersive._init_position()

    def _handle_manual_check_update(self):
        """手動點擊「檢查更新」：即時連線 GitHub API 檢查並給予明確回饋"""
        from app import AdminEfficiencyPilot as _AEP
        import threading, requests as _req

        RELEASE_API = "https://api.github.com/repos/lianghao02/auto-learning-bot/releases/latest"
        current_version = _AEP.VERSION

        btn = getattr(self.immersive, "check_update_btn", None)
        if btn:
            btn.setText("⏳ 檢查中...")
            btn.setEnabled(False)

        def _reset_btn():
            if btn:
                btn.setText("🔄 檢查更新")
                btn.setEnabled(True)

        def _worker():
            try:
                headers = {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                resp = _req.get(RELEASE_API, timeout=8, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    update_info = parse_release_update(data, current_version)
                    if update_info:
                        latest, changelog, download_url, file_size, digest = update_info
                        self.entry._has_update = True
                        self.entry._latest_update_info = (latest, changelog, download_url, file_size, digest)
                        QTimer.singleShot(
                            0,
                            lambda: UpdateDialog(
                                self, latest, changelog, download_url, file_size, digest
                            ).exec(),
                        )
                    else:
                        self.entry._has_update = False
                        self.entry._latest_update_info = None
                        QTimer.singleShot(0, lambda: self._show_version_dialog())
                else:
                    QTimer.singleShot(
                        0,
                        lambda: QMessageBox.warning(
                            self,
                            "檢查更新",
                            f"無法取得最新版本資訊（HTTP {resp.status_code}），請稍後再試。",
                        ),
                    )
            except Exception as e:
                QTimer.singleShot(
                    0,
                    lambda: QMessageBox.warning(
                        self, "檢查更新", f"連線至 GitHub 失敗：{e}\n請檢查網路連線。"
                    ),
                )
            finally:
                QTimer.singleShot(0, _reset_btn)

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_update_btn(self):
        """手動點更新圖示：一定跳視窗顯示版本資訊"""
        entry = self.entry
        if entry._has_update and entry._latest_update_info:
            # 有新版 → 跳更新視窗
            info = entry._latest_update_info
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
            # 沒有新版或尚未檢查 → 跳「目前版本」視窗
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

        entry = self.entry
        if entry._has_update and entry._latest_update_info:
            latest_label = QLabel(f"線上最新版本：{entry._latest_update_info[0]}")
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

        # 置中於螢幕
        from PySide6.QtWidgets import QApplication
        def _center():
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.x() + (screen.width() - dialog.width()) // 2
            y = screen.y() + (screen.height() - dialog.height()) // 2
            dialog.move(x, y)
        QTimer.singleShot(0, _center)

        dialog.exec()

    def _on_up_to_date(self):
        """已是最新版，更新按鈕 tooltip"""
        self.entry._has_update = False
        btn = getattr(self.entry, "_update_btn", None)
        if btn:
            btn.setToolTip("目前已是最新版")
            btn.setStyleSheet("""
                QPushButton { background: transparent; border: none; }
                QPushButton:hover { background: transparent; }
            """)

    def _on_update_available(
        self,
        latest: str,
        changelog: str,
        url: str,
        size: int = 0,
        digest: str = "",
    ):
        """顯示安全更新對話框；缺少 digest 時只提供手動下載。"""
        self.entry._has_update = True
        self.entry._latest_update_info = (latest, changelog, url, size, digest)
        btn = getattr(self.entry, "_update_btn", None)
        if btn:
            btn.setToolTip(f"有新版本 {latest}！點此查看")
        UpdateDialog(self, latest, changelog, url, size, digest).exec()

    def go_entry(self):
        """⭐ 修改版：立即返回入口，後臺清理"""
        self.resize(900, 600)
        # Step 1️⃣：立即設置停止旗標
        self._request_stop_current_pilot()

        # Step 2️⃣：立即切換 UI 回到入口頁面（重點：不等待）
        self.stack.setCurrentWidget(self.entry)

        # Step 3️⃣：重置入口頁面的 combo
        self.entry.combo.blockSignals(True)
        self.entry.combo.setCurrentIndex(0)
        self.entry.combo.blockSignals(False)

        # Step 4️⃣：在後臺執行清理（非同步，不卡 UI）
        if self.cleanup_thread is None or not self.cleanup_thread.is_alive():
            self.cleanup_thread = threading.Thread(
                target=self._cleanup_pilot_async, daemon=True
            )
            self.cleanup_thread.start()

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


    def closeEvent(self, event):
        self._request_stop_current_pilot()
        if self.cleanup_thread is None or not self.cleanup_thread.is_alive():
            self.cleanup_thread = threading.Thread(
                target=self._cleanup_pilot_async, daemon=True
            )
            self.cleanup_thread.start()
            self.cleanup_thread.join(timeout=3)
        event.accept()


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
