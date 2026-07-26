import json
import os
import sys
import re
import threading
import random
import math
from datetime import datetime

# 確保 PyInstaller frozen 模式下 _MEIPASS 在 sys.path 最前面
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    if sys._MEIPASS not in sys.path:
        sys.path.insert(0, sys._MEIPASS)

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
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
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
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
)
from utils.helpers import get_logger
from usage_tracker import UsageHeartbeat


BASE_DIR = os.path.dirname(__file__)

logger = get_logger()


def icon(name):
    return QIcon(resource_path(f"icons/{name}"))


def resource_path(relative_path):
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def version_tuple(version):
    nums = re.findall(r"\d+", str(version or ""))
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def is_newer_version(latest, current):
    return version_tuple(latest) > version_tuple(current)


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
        path = "config.json"

        if not os.path.exists(path):
            # 初始空設定
            data = {"accounts": [], "settings": {}}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return data

        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {"accounts": [], "settings": {}}
            return json.loads(content)

    def _save_config(self) -> bool:
        """統一的設定儲存方法，含錯誤處理"""
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
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
        self.config["settings"] = settings_data
        self._save_config()

        ai_key = settings_data.get("ai_api_key", "").strip()
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
                            r = _req.get(f"{base_url}/models", headers=headers, timeout=8, verify=False)
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
                                    timeout=10, verify=False,
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
                            timeout=10, verify=False,
                        )
                        if r.status_code == 200:
                            ok, msg = True, "✅ API Key 驗證成功"
                        elif r.status_code == 401:
                            ok, msg = False, "❌ API Key 無效（401）"
                        else:
                            ok, msg = False, f"❌ 驗證失敗（HTTP {r.status_code}）"
                    else:
                        r = _req.get(f"{base_url}/models", headers=headers, timeout=8, verify=False)
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
    # (latest_version, changelog, download_url, file_size_bytes)
    notify = Signal(str, str, str, int)
    up_to_date = Signal()           # 已是最新版

    def emit(self, version, changelog, url, size=0):
        self.notify.emit(version, changelog, url, size)


class UsageSignal(QObject):
    online = Signal(int)


class _DownloadProgressSignal(QObject):
    """下載進度訊號 (downloaded_bytes, total_bytes)"""
    progress = Signal(int, int)
    finished = Signal(str)   # 下載完成，帶完成檔案路徑
    failed = Signal(str)     # 失敗，帶錯誤訊息


class UpdateDialog(QDialog):
    """兩階段更新對話框：階段一顯示版本資訊，階段二顯示下載進度與重啟"""

    def __init__(self, parent, latest: str, changelog: str, url: str, size: int):
        super().__init__(parent)
        self.latest = latest
        self.changelog = changelog
        self.url = url
        self.size = size
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
            change_body = QLabel(self.changelog)
            change_body.setStyleSheet("""
                font-size: 11px; color: #555f6e;
                padding: 8px 12px; background: #eaf4fb;
                border-left: 3px solid #4fc3f7; border-radius: 4px;
            """)
            change_body.setWordWrap(True)
            content.addWidget(change_body)

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

        btn_download = QPushButton("下載更新")
        btn_download.setFixedHeight(36)
        btn_download.setStyleSheet("""
            QPushButton {
                background: #0288d1; color: #fff; font-weight: bold;
                border-radius: 6px; padding: 0 22px; font-size: 13px;
                border: none;
            }
            QPushButton:hover { background: #0277bd; }
        """)
        btn_download.clicked.connect(self._start_download)

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
        # 確認執行環境為打包版（frozen）
        if not getattr(sys, "frozen", False):
            QMessageBox.warning(
                self, "無法自動更新",
                "目前是從原始碼執行（非打包版 exe），自動更新僅支援打包後的 .exe 版本。\n"
                "請至 GitHub Releases 取得最新原始碼。"
            )
            return

        self._build_stage_two(done=False)

        # 暫存檔案路徑
        tmp_dir = tempfile.gettempdir()
        self.downloaded_path = os.path.join(tmp_dir, f"行政效能領航員_{self.latest}_new.exe")

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

        FALLBACK_URL = "https://drive.google.com/drive/folders/1Fm6CwmV2AsoWaUOGV0V5hZbgP_GJrU8g?usp=sharing"

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
            "請點擊下方按鈕前往下載頁面，找到最新版的 <b>.exe</b> 檔下載後，"
            "替換掉目前資料夾中的舊版本即可完成更新。"
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
        btn_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.url or FALLBACK_URL)))
        btn_open.clicked.connect(fail_dlg.accept)

        b_row.addStretch()
        b_row.addWidget(btn_close)
        b_row.addWidget(btn_open)
        body.addLayout(b_row)

        f_outer.addLayout(body)
        fail_dlg.exec()
        self.reject()

    # ---------- 安裝（替換 exe 並重啟）----------
    def _install_and_restart(self):
        import os, tempfile, subprocess
        if not self.downloaded_path or not os.path.exists(self.downloaded_path):
            self._on_failed("找不到已下載的更新檔（可能被防毒軟體刪除）")
            return

        # 移除 Zone.Identifier（網路下載標記），避免 Defender 攔截 DLL 載入
        # 在 ps1 執行前就處理，確保無論 ps1 版本新舊都有效
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Unblock-File -LiteralPath '{self.downloaded_path}'"],
                timeout=5, capture_output=True
            )
        except Exception:
            pass

        current_exe = sys.executable  # 目前運行中的 exe 完整路徑
        new_exe = self.downloaded_path
        exe_dir = os.path.dirname(current_exe)
        # 統一目標檔名（去掉版本號），未來升級永遠用同一個檔名，
        # 捷徑/工作列釘選/開機自啟動才不會因檔名改變而失效
        target_exe = os.path.join(exe_dir, "行政效能領航員.exe")

        # 用 PowerShell 寫 updater 腳本（PowerShell 原生支援 UTF-16，中文路徑無編碼問題；
        # 過去用 bat 會因 cp950/UTF-8 編碼衝突導致中文路徑全變亂碼，所有命令失敗）
        ps1_path = os.path.join(tempfile.gettempdir(), "auto_update.ps1")
        # 路徑單引號跳脫：PowerShell 單引號字串中，單引號需寫成兩個單引號
        cur_q = current_exe.replace("'", "''")
        new_q = new_exe.replace("'", "''")
        dir_q = exe_dir.replace("'", "''")
        tgt_q = target_exe.replace("'", "''")
        ps1_content = f"""$ErrorActionPreference = 'Continue'
$logPath = '{dir_q}\\update_debug.log'
function Log($msg) {{ Add-Content -LiteralPath $logPath -Value ("[ps1 " + (Get-Date -Format 'HH:mm:ss') + "] " + $msg) -Encoding UTF8 }}
Log "ps1 started, pid=$PID"
Start-Sleep -Milliseconds 800
$exe = '{cur_q}'
$new = '{new_q}'
$dir = '{dir_q}'
$tgt = '{tgt_q}'
Log "exe=$exe"
Log "new=$new"
Log "tgt=$tgt"
# 1. 主動 kill 殘留的舊程序
Get-Process | Where-Object {{ $_.Path -eq $exe }} | ForEach-Object {{ Log "killing pid=$($_.Id)"; Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }}
Start-Sleep -Milliseconds 300
# 2. 重試刪除舊 exe（最多 10 次）
for ($i = 0; $i -lt 10; $i++) {{
    try {{ Remove-Item -LiteralPath $exe -Force -ErrorAction Stop; Log "deleted old exe at try $i"; break }}
    catch {{ Log "delete try $i failed: $_"; Start-Sleep -Seconds 1 }}
}}
# 2b. 若目標檔名與舊 exe 不同（升級時改名情境），也嘗試刪除目標位置的舊檔
if ($tgt -ne $exe) {{
    try {{ if (Test-Path -LiteralPath $tgt) {{ Remove-Item -LiteralPath $tgt -Force -ErrorAction Stop; Log "deleted existing target" }} }}
    catch {{ Log "delete target failed: $_" }}
}}
# 3. 移動新 exe 到目標位置（永遠用「行政效能領航員.exe」這個檔名）
try {{
    Move-Item -LiteralPath $new -Destination $tgt -Force -ErrorAction Stop
    Log "moved new exe -> $tgt"
}} catch {{
    Log "move failed: $_"
    exit 1
}}
# 3b. 移除 Zone.Identifier（網路下載標記），避免 Defender 攔截 DLL 載入
Unblock-File -LiteralPath $tgt -ErrorAction SilentlyContinue
Log "unblocked exe"
# 4. 用排程工作啟動新版（系統信任的使用者互動，Defender 不會攔截 DLL）
Start-Sleep -Seconds 2
try {{
    $exeDir = Split-Path -Parent $tgt
    $action  = New-ScheduledTaskAction -Execute $tgt -WorkingDirectory $exeDir
    $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddSeconds(3))
    $settings = New-ScheduledTaskSettingsSet -DeleteExpiredTaskAfter (New-TimeSpan -Seconds 60)
    Register-ScheduledTask -TaskName "AEP_AutoLaunch" -Action $action -Trigger $trigger -Settings $settings -Force -RunLevel Limited -ErrorAction Stop | Out-Null
    Log "scheduled task registered, launching in 3s"
}} catch {{
    Log "task failed: $_, fallback ShellExecute"
    try {{
        $shell = New-Object -ComObject Shell.Application
        $shell.ShellExecute($tgt, '', (Split-Path -Parent $tgt), 'open', 1)
    }} catch {{
        Log "ShellExecute also failed: $_"
    }}
}}
# 5. 刪自己
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
Log "ps1 done"
"""
        try:
            # PowerShell 必須用 UTF-8 with BOM 寫，否則 PowerShell 5.1 預設用
            # 系統 ANSI (cp950) 解碼，中文路徑會變亂碼導致 Move/Start 全失敗
            with open(ps1_path, "w", encoding="utf-8-sig") as f:
                f.write(ps1_content)
        except Exception as e:
            self._on_failed(f"無法建立更新腳本：{e}")
            return

        # 用 DETACHED_PROCESS 啟動 powershell，再立刻退出本程式
        import subprocess, base64
        try:
            # 寫安裝 log 供事後排查
            try:
                log_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else "."
                with open(os.path.join(log_dir, "update_debug.log"), "a", encoding="utf-8") as lf:
                    lf.write(f"install: ps1={ps1_path}\n")
                    lf.write(f"install: current_exe={current_exe}\n")
                    lf.write(f"install: new_exe={new_exe}\n")
                    lf.write(f"install: new_exe exists={os.path.exists(new_exe)}\n")
            except Exception:
                pass

            # 用 -EncodedCommand (base64 UTF-16LE) 直接把 ps1 內容塞給 PowerShell，
            # 完全繞過「讀檔編碼」問題。PowerShell 收到 -EncodedCommand 後會用
            # UTF-16LE 解碼，中文 100% 保留。
            encoded = base64.b64encode(ps1_content.encode("utf-16-le")).decode("ascii")

            # 不用 DETACHED_PROCESS（會干擾 PowerShell 啟動），
            # 改用 STARTUPINFO 隱藏視窗 + CREATE_NEW_PROCESS_GROUP 讓子程序獨立
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE

            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
                creationflags=0x00000200,  # CREATE_NEW_PROCESS_GROUP
                startupinfo=si,
                close_fds=True,
            )
            try:
                with open(os.path.join(log_dir, "update_debug.log"), "a", encoding="utf-8") as lf:
                    lf.write(f"install: ps proc pid={proc.pid} (encoded cmd, len={len(encoded)})\n")
            except Exception:
                pass
        except Exception as e:
            self._on_failed(f"無法啟動更新程序：{e}")
            return

        # 關閉對話框並退出主程式 — 給 PyInstaller 機會清理自己的 _MEI 目錄，
        # 避免新 exe 啟動時與舊 _MEI 殘留衝突導致「Failed to load Python DLL」
        import time
        self.accept()
        QApplication.processEvents()
        time.sleep(0.2)
        QApplication.quit()
        # 用 sys.exit 而非 os._exit，讓 PyInstaller atexit handler 有機會清 _MEI
        sys.exit(0)


# =========================
# 主執行頁面
# =========================
from PySide6.QtWidgets import QTabWidget

class PlatformTabPanel(QWidget):
    log_signal = Signal(str)

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

        # Windows 11 經典進度與統計卡片
        progress_card = QFrame()
        progress_card.setStyleSheet("""
            QFrame {
                background: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                padding: 6px 12px;
            }
            QLabel {
                color: #1F2937; font-size: 13px; font-weight: bold; background: transparent;
            }
        """)
        prog_layout = QHBoxLayout(progress_card)
        prog_layout.setContentsMargins(8, 4, 8, 4)

        self.stats_lbl = QLabel("📊 研習時數與課程進度：準備就緒")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #E5E7EB;
                border: 1px solid #D1D5DB;
                border-radius: 8px;
                text-align: center;
                color: #1F2937;
                font-weight: bold;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0067C0, stop:1 #10B981);
                border-radius: 7px;
            }
        """)

        prog_layout.addWidget(self.stats_lbl)
        prog_layout.addStretch()
        prog_layout.addWidget(self.progress_bar)
        layout.addWidget(progress_card)

        # 操作列
        btn_bar = QHBoxLayout()
        self.info_lbl = QLabel(f"{platform_title}控制台")
        self.info_lbl.setStyleSheet("color: #111827; font-weight: bold; font-size: 14px; background: transparent;")

        self.start_btn = QPushButton("▶️ 開始執行")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: #10B981; color: #FFFFFF; border-radius: 8px;
                padding: 8px 18px; font-weight: bold; font-size: 13px; border: none;
            }
            QPushButton:hover { background: #059669; }
        """)
        self.start_btn.clicked.connect(self._handle_start)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background: #EF4444; color: #FFFFFF; border-radius: 8px;
                padding: 8px 18px; font-weight: bold; font-size: 13px; border: none;
            }
            QPushButton:hover { background: #DC2626; }
        """)
        self.stop_btn.clicked.connect(self._handle_stop)

        self.toggle_browser_btn = QPushButton("👁️ 顯示瀏覽器")
        self.toggle_browser_btn.setStyleSheet("""
            QPushButton {
                background: #3B82F6; color: #FFFFFF; border-radius: 8px;
                padding: 8px 18px; font-weight: bold; font-size: 13px; border: none;
            }
            QPushButton:hover { background: #2563EB; }
        """)
        self.toggle_browser_btn.clicked.connect(self._handle_toggle_browser)

        btn_bar.addWidget(self.info_lbl)
        btn_bar.addStretch()
        btn_bar.addWidget(self.start_btn)
        btn_bar.addWidget(self.stop_btn)
        btn_bar.addWidget(self.toggle_browser_btn)
        layout.addLayout(btn_bar)

        # Log 視窗
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(300)
        self.log_view.setStyleSheet("""
            QTextEdit {
                background: rgba(36, 41, 51, 0.7);
                border: 1px solid rgba(216, 222, 233, 0.15);
                border-radius: 10px;
                color: #ECEFF4;
                font-size: 13px;
                padding: 8px;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
            }
            QScrollBar::handle:vertical {
                background: rgba(216, 222, 233, 0.3);
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.log_view)

        self.log_signal.connect(self._append_text_safe)

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
        if self.on_start:
            self.on_start(self.platform_key)

    def _handle_stop(self):
        if self.on_stop:
            self.on_stop(self.platform_key)

    def _handle_toggle_browser(self):
        self.browser_visible = not self.browser_visible
        if self.browser_visible:
            self.toggle_browser_btn.setText("🙈 隱藏瀏覽器")
            self.toggle_browser_btn.setStyleSheet("""
                QPushButton {
                    background: #6B7280; color: white; border-radius: 8px;
                    padding: 8px 16px; font-weight: bold; font-size: 13px; border: none;
                }
                QPushButton:hover { background: #4B5563; }
            """)
        else:
            self.toggle_browser_btn.setText("👁️ 顯示瀏覽器")
            self.toggle_browser_btn.setStyleSheet("""
                QPushButton {
                    background: #3B82F6; color: white; border-radius: 8px;
                    padding: 8px 16px; font-weight: bold; font-size: 13px; border: none;
                }
                QPushButton:hover { background: #2563EB; }
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
                self.stats_lbl.setText(f"📊 當前單元時數：{time_str} ({pct_float:.1f}%)")

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
            "INFO": "#0284C7",
            "WARNING": "#D97706",
            "WARN": "#D97706",
            "ERROR": "#DC2626",
            "CRITICAL": "#EA580C",
            "DEBUG": "#6B7280",
        }
        level_color = level_colors.get(level_part, "#6B7280")

        html = (
            f'<span style="color:#6B7280;">{esc(time_part)}</span> '
            f'<span style="color:{level_color}; font-weight:bold;">[{esc(level_part)}]</span> '
            f'<span style="color:#111827;">{esc(msg_part)}</span>'
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
        lbl.setStyleSheet("color: #111827; font-weight: bold; font-size: 16px; background: transparent;")
        layout.addWidget(lbl)

        form_card = QFrame()
        form_card.setStyleSheet("""
            QFrame {
                background: #FFFFFF;
                border: 1px solid #E5E5E5;
                border-radius: 12px;
                padding: 20px;
            }
            QLabel {
                color: #374151;
                font-weight: bold;
                font-size: 13px;
                background: transparent;
                min-height: 28px;
                padding: 2px 0px;
            }
        """)
        form_layout = QFormLayout(form_card)
        form_layout.setSpacing(14)
        form_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        input_style = """
            QLineEdit, QComboBox {
                background: #F9FAFB;
                color: #1F2937;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                min-height: 20px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 2px solid #0067C0;
                background: #FFFFFF;
            }
        """

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("請輸入顯示名稱 (例如：E大或E等)")
        self.name_input.setStyleSheet(input_style)

        self.type_combo = QComboBox()
        self.type_combo.addItem("臺北E大 (taipei_eda)", "taipei_eda")
        self.type_combo.addItem("e等公務員 / eCPA (ecpa)", "ecpa")
        self.type_combo.addItem("我的E政府 (egov)", "egov")
        self.type_combo.setStyleSheet(input_style)

        self.acc_input = QLineEdit()
        self.acc_input.setPlaceholderText("請輸入登入帳號 (身分證字號或帳號)")
        self.acc_input.setStyleSheet(input_style)

        self.pwd_input = QLineEdit()
        self.pwd_input.setEchoMode(QLineEdit.Password)
        self.pwd_input.setPlaceholderText("請輸入登入密碼")
        self.pwd_input.setStyleSheet(input_style)

        self.headless_cb = QCheckBox("背景執行 (Headless 隱藏瀏覽器視窗)")
        self.headless_cb.setStyleSheet("""
            QCheckBox {
                color: #1F2937;
                font-weight: bold;
                font-size: 13px;
                background: transparent;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #9CA3AF;
                border-radius: 4px;
                background-color: #FFFFFF;
            }
            QCheckBox::indicator:hover {
                border-color: #0067C0;
            }
            QCheckBox::indicator:checked {
                background-color: #0067C0;
                border-color: #0067C0;
            }
        """)

        self.ai_key_input = QLineEdit()
        self.ai_key_input.setPlaceholderText("可選：填入 Gemini API Key 以開啟 AI 自動考試作答功能")
        self.ai_key_input.setStyleSheet(input_style)

        form_layout.addRow(QLabel("顯示名稱:"), self.name_input)
        form_layout.addRow(QLabel("預設登入平台:"), self.type_combo)
        form_layout.addRow(QLabel("登入帳號:"), self.acc_input)
        form_layout.addRow(QLabel("登入密碼:"), self.pwd_input)
        form_layout.addRow(QLabel("執行模式:"), self.headless_cb)
        form_layout.addRow(QLabel("Gemini API Key:"), self.ai_key_input)

        layout.addWidget(form_card)

        btn_bar = QHBoxLayout()
        self.save_btn = QPushButton("💾 儲存並套用設定")
        self.save_btn.setStyleSheet("""
            QPushButton {
                background: #0067C0; color: #FFFFFF; border-radius: 8px;
                padding: 10px 24px; font-weight: bold; font-size: 14px; border: none;
            }
            QPushButton:hover { background: #005A9E; }
        """)
        self.save_btn.clicked.connect(self.save_settings)
        btn_bar.addStretch()
        btn_bar.addWidget(self.save_btn)
        layout.addLayout(btn_bar)

        self.load_settings()

    def load_settings(self):
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                accounts = data.get("accounts", [])
                if accounts:
                    acc = accounts[0]
                    self.name_input.setText(acc.get("name", ""))
                    self.acc_input.setText(acc.get("account", ""))
                    self.pwd_input.setText(acc.get("password", ""))
                    ltype = acc.get("login_type", "taipei_eda")
                    idx = self.type_combo.findData(ltype)
                    if idx != -1:
                        self.type_combo.setCurrentIndex(idx)
                settings = data.get("settings", {})
                self.headless_cb.setChecked(settings.get("headless", False))
                self.ai_key_input.setText(settings.get("ai_api_key", ""))
        except Exception:
            pass

    def save_settings(self):
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"accounts": [], "settings": {}}

            acc_data = {
                "name": self.name_input.text().strip() or "預設帳號",
                "login_type": self.type_combo.currentData() or "taipei_eda",
                "account": self.acc_input.text().strip(),
                "password": self.pwd_input.text().strip()
            }
            
            accounts = data.get("accounts", [])
            if accounts:
                accounts[0] = acc_data
            else:
                accounts = [acc_data]
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

            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

            if hasattr(self, "on_settings_saved") and callable(self.on_settings_saved):
                self.on_settings_saved()

            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "成功", "✅ 帳號與系統設定已成功儲存並套用！")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "錯誤", f"❌ 儲存失敗：{e}")


class ImmersivePage(QWidget):
    def __init__(self, on_stop):
        super().__init__()
        self.on_stop = on_stop
        self.on_start_platform = None
        self.on_stop_platform = None
        self.on_toggle_browser = None
        self.on_start_all = None

        # Windows 11 經典 Mica 輕量化主背景
        self.setStyleSheet("background-color: #F3F3F3;")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 頂部控制列
        top_bar = QHBoxLayout()
        title_lbl = QLabel("行政效能領航員 - 控制中心")
        title_lbl.setStyleSheet("color: #1C1C1E; font-weight: bold; font-size: 17px; background: transparent;")

        self.start_all_btn = QPushButton("🚀 一鍵全自動雙開")
        self.start_all_btn.setStyleSheet("""
            QPushButton {
                background: #0067C0; color: #FFFFFF; border-radius: 8px;
                padding: 8px 18px; font-weight: bold; font-size: 13px; border: none;
            }
            QPushButton:hover { background: #005A9E; }
        """)
        self.start_all_btn.clicked.connect(self._handle_start_all)

        self.stop_all_btn = QPushButton("🛑 停止全部")
        self.stop_all_btn.setStyleSheet("""
            QPushButton {
                background: #D13438; color: #FFFFFF; border-radius: 8px;
                padding: 8px 18px; font-weight: bold; font-size: 13px; border: none;
            }
            QPushButton:hover { background: #A80000; }
        """)
        self.stop_all_btn.clicked.connect(self.on_stop)

        self.account_mgr_btn = QPushButton("⚙️ 帳號與系統設定")
        self.account_mgr_btn.setStyleSheet("""
            QPushButton {
                background: #FFFFFF; color: #1C1C1E; border-radius: 8px;
                padding: 8px 16px; font-weight: bold; font-size: 13px; border: 1px solid #D1D1D1;
            }
            QPushButton:hover { background: #F3F4F6; }
        """)
        self.account_mgr_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(2))

        top_bar.addWidget(title_lbl)
        top_bar.addStretch()
        top_bar.addWidget(self.start_all_btn)
        top_bar.addWidget(self.stop_all_btn)
        top_bar.addWidget(self.account_mgr_btn)
        root.addLayout(top_bar)

        # 多頁籤面板 (QTabWidget - Win11 經典風格)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #E5E5E5;
                border-radius: 12px;
                background: #FFFFFF;
            }
            QTabBar::tab {
                background: #E5E7EB;
                color: #4B5563;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 10px 24px;
                font-weight: bold;
                font-size: 14px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #0067C0;
                color: #FFFFFF;
            }
            QTabBar::tab:hover:!selected {
                background: #D1D5DB;
                color: #1F2937;
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
            if os.path.exists("config.json"):
                with open("config.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                accounts = data.get("accounts", [])
                
                # 臺北E大帳號
                taipei_acc = next((a for a in accounts if a.get("login_type") == "taipei_eda"), None)
                if not taipei_acc and accounts:
                    taipei_acc = accounts[0]
                if taipei_acc:
                    self.taipei_panel.update_account_info(taipei_acc.get("name", ""), taipei_acc.get("account", ""))
                else:
                    self.taipei_panel.update_account_info("未設定帳號", "")

                # e等公務員帳號
                egov_acc = next((a for a in accounts if a.get("login_type") in ("ecpa", "egov")), None)
                if not egov_acc and accounts:
                    egov_acc = accounts[0]
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

    def start(self, account_name: str):
        self.taipei_panel.info_lbl.setText(f"臺北E大控制台（帳號：{account_name}）")
        self.egov_panel.info_lbl.setText(f"e等公務員控制台（帳號：{account_name}）")

    def _init_position(self):
        pass


# =========================
# 主視窗（頁面切換）
# =========================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("行政效能領航員")
        self.setStyleSheet("background-color: #F3F3F3;")

        self.stack = QStackedLayout(self)

        self.entry = EntryPage(self.go_immersive)
        self.immersive = ImmersivePage(self._stop_all_platforms)

        # 綁定頁籤與按鈕事件
        self.immersive.on_start_platform = self._start_single_platform
        self.immersive.on_stop_platform = self._stop_single_platform
        self.immersive.on_toggle_browser = self._toggle_platform_browser
        self.immersive.on_start_all = self._start_all_platforms

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

    def _start_single_platform(self, key):
        config_from_entry = self.entry.load_config()
        accounts = config_from_entry.get("accounts", [])
        
        # 尋找匹配平臺的帳號（對應 ecpa 時兼顧 egov 與 ecpa）
        if key in ("ecpa", "egov"):
            acc_data = next((a for a in accounts if a.get("login_type") in ("ecpa", "egov")), None)
        else:
            acc_data = next((a for a in accounts if a.get("login_type") == key), None)

        if not acc_data and accounts:
            acc_data = accounts[0]

        if not acc_data:
            logger.warning(f"⚠️ 找不到平台 {key} 的對應帳號設定")
            return

        full_config = acc_data.copy()
        full_config.update(config_from_entry.get("settings", {}))
        # 🔒 實時讀取 UI 最新『背景執行』勾選狀態，避免設定未寫入檔案導致網頁視窗彈出！
        full_config["headless"] = self.immersive.settings_panel.headless_cb.isChecked()

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
                progress_callback=self.immersive.taipei_panel.update_progress
            )
            self.taipei_pilot.running = True
            self.taipei_thread = threading.Thread(target=self.taipei_pilot.run, daemon=True)
            self.taipei_thread.start()
            logger.info("🚀 臺北E大流程已啟動")

        else:  # ecpa / egov
            # 檢查並自動清理已死掉的舊 Thread
            if self.egov_thread and not self.egov_thread.is_alive():
                self.egov_thread = None
                self.egov_pilot = None

            if self.egov_thread and self.egov_thread.is_alive():
                logger.warning("⚠️ e等公務員流程已在運行中")
                return
            # 優先保留原帳號的 login_type (例如 egov)，若為 taipei_eda 或未指定，預設給予 egov
            if full_config.get("login_type") in ("taipei_eda", None, ""):
                full_config["login_type"] = "egov"
            self.egov_pilot = AdminEfficiencyPilot(
                config_override=full_config,
                log_callback=self.immersive.egov_panel.append_text,
                progress_callback=self.immersive.egov_panel.update_progress
            )
            self.egov_pilot.running = True
            self.egov_thread = threading.Thread(target=self.egov_pilot.run, daemon=True)
            self.egov_thread.start()
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
        """程式啟動時，背景 thread 檢查 GitHub Releases，有新版則跳提示"""
        from app import AdminEfficiencyPilot
        import threading, requests as _req

        VERSION_URL = "https://raw.githubusercontent.com/waynelord0628-beep/auto-learning-bot/main/version.txt"
        RELEASE_API = "https://api.github.com/repos/waynelord0628-beep/auto-learning-bot/releases/latest"
        FALLBACK_URL = "https://drive.google.com/drive/folders/1Fm6CwmV2AsoWaUOGV0V5hZbgP_GJrU8g?usp=sharing"
        current_version = AdminEfficiencyPilot.VERSION

        self._update_signal = UpdateSignal()
        self._update_signal.notify.connect(self._on_update_available)
        self._update_signal.up_to_date.connect(self._on_up_to_date)
        _update_signal = self._update_signal

        import sys as _sys, os as _os
        _log_path = _os.path.join(_os.path.dirname(_sys.executable if getattr(_sys, "frozen", False) else _os.path.abspath(__file__)), "update_debug.log")

        def _dbg(msg):
            try:
                with open(_log_path, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass

        def _check():
            _dbg("update check thread started")
            try:
                version_resp = _req.get(VERSION_URL, timeout=8)
                _dbg(f"version_status={version_resp.status_code}")
                if version_resp.status_code != 200:
                    _dbg(f"version.txt HTTP {version_resp.status_code}: {version_resp.text[:200]}")
                    return
                latest = version_resp.text.strip()
                changelog = ""
                assets = []
                resp = _req.get(RELEASE_API, timeout=8, headers={"Accept": "application/vnd.github+json"})
                _dbg(f"release_status={resp.status_code}")
                if resp.status_code == 200:
                    data = resp.json()
                    changelog = (data.get("body") or "").strip()
                    assets = data.get("assets", []) or []
                # V2.1.6 起優先導向 GitHub Release exe，沒有 asset 才 fallback 雲端。
                exe_asset = next(
                    (a for a in assets if (a.get("name") or "").lower().endswith(".exe")),
                    None,
                )
                file_size = int(exe_asset.get("size", 0)) if exe_asset else 0
                download_url = (exe_asset.get("browser_download_url") if exe_asset else "") or FALLBACK_URL

                if not latest or not latest.upper().startswith("V"):
                    _dbg(f"version.txt 格式不符：{latest!r}")
                    return
                _dbg(f"latest={latest!r} current={current_version!r} size={file_size}")
                if is_newer_version(latest, current_version):
                    _dbg("emitting update signal")
                    _update_signal.emit(latest, changelog, download_url, file_size)
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

    def _handle_update_btn(self):
        """手動點更新圖示：一定跳視窗顯示版本資訊"""
        entry = self.entry
        if entry._has_update and entry._latest_update_info:
            # 有新版 → 跳更新視窗
            info = entry._latest_update_info
            # 相容舊格式 (3 元素) 與新格式 (4 元素)
            if len(info) == 4:
                latest, changelog, url, size = info
            else:
                latest, changelog, url = info
                size = 0
            self._on_update_available(latest, changelog, url, size)
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
        cur_label.setStyleSheet("font-size: 13px;")
        body.addWidget(cur_label)

        entry = self.entry
        if entry._has_update and entry._latest_update_info:
            latest_label = QLabel(f"最新版本：{entry._latest_update_info[0]}")
        else:
            latest_label = QLabel("最新版本：目前已是最新版")
        latest_label.setStyleSheet("font-size: 13px; color: #27ae60;")
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

    def _on_update_available(self, latest: str, changelog: str, url: str, size: int = 0):
        """在主執行緒顯示更新提示視窗（雲端下載版：直接引導使用者前往雲端手動下載）"""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        FALLBACK_URL = "https://drive.google.com/drive/folders/1Fm6CwmV2AsoWaUOGV0V5hZbgP_GJrU8g?usp=sharing"
        download_url = url or FALLBACK_URL

        # 儲存更新資訊，讓按鈕可以重複觸發
        self.entry._has_update = True
        self.entry._latest_update_info = (latest, changelog, url, size)
        btn = getattr(self.entry, "_update_btn", None)
        if btn:
            btn.setToolTip(f"有新版本 {latest}！點此查看")
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    border-radius: 26px;
                }
                QPushButton:hover {
                    background: rgba(0,0,0,0.12);
                }
            """)

        # ── 輕量提示框：引導使用者前往雲端手動下載 ──
        dlg = QDialog(self)
        dlg.setWindowTitle("有新版本可用")
        dlg.setFixedWidth(460)
        dlg.setStyleSheet("QDialog { background: #f5f7fa; } QLabel { color: #2c3e50; background: transparent; }")

        outer = QVBoxLayout(dlg)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        # 藍色頂部色帶
        hdr = QLabel()
        hdr.setFixedHeight(6)
        hdr.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #1976d2,stop:1 #42a5f5);")
        outer.addWidget(hdr)

        body = QVBoxLayout()
        body.setSpacing(12)
        body.setContentsMargins(28, 22, 28, 20)

        # 標題列
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        ico = QLabel("🔔")
        ico.setFixedSize(42, 42)
        ico.setStyleSheet("background: #e3f2fd; border-radius: 8px; font-size: 22px; qproperty-alignment: AlignCenter;")
        title_row.addWidget(ico)

        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        ttl = QLabel(f"發現新版本 <b>{latest}</b>")
        ttl.setTextFormat(Qt.RichText)
        ttl.setStyleSheet("font-size: 16px; font-weight: bold; color: #1565c0;")
        tbox.addWidget(ttl)
        title_row.addLayout(tbox, 1)
        body.addLayout(title_row)

        # 說明文字
        guide = QLabel(
            "請點擊下方按鈕前往雲端下載最新版的 <b>.exe</b> 檔，"
            "下載後直接替換掉目前的舊版本即可完成更新。"
        )
        guide.setTextFormat(Qt.RichText)
        guide.setWordWrap(True)
        guide.setStyleSheet(
            "font-size: 12px; color: #555f6e; padding: 10px 12px;"
            "background: #ffffff; border: 1px solid #e1e7ed; border-radius: 6px;"
        )
        body.addWidget(guide)

        # 更新日誌（有的話顯示）
        if changelog:
            log_lbl = QLabel(changelog[:300] + ("…" if len(changelog) > 300 else ""))
            log_lbl.setWordWrap(True)
            log_lbl.setStyleSheet(
                "font-size: 11px; color: #7f8c8d; padding: 8px 10px;"
                "background: #f0f4f8; border: 1px solid #dce1e7; border-radius: 5px;"
            )
            body.addWidget(log_lbl)

        # 按鈕列
        b_row = QHBoxLayout()
        b_row.setSpacing(10)

        btn_close = QPushButton("稍後再說")
        btn_close.setFixedHeight(36)
        btn_close.setStyleSheet("""
            QPushButton { background: #ecf0f1; color: #7f8c8d; border-radius: 6px;
                          padding: 0 22px; font-size: 13px; border: 1px solid #dce1e7; }
            QPushButton:hover { background: #dde3e8; }
        """)
        btn_close.clicked.connect(dlg.reject)

        btn_open = QPushButton("前往雲端下載新版本")
        btn_open.setFixedHeight(36)
        btn_open.setStyleSheet("""
            QPushButton { background: #1976d2; color: #fff; font-weight: bold;
                          border-radius: 6px; padding: 0 22px; font-size: 13px; border: none; }
            QPushButton:hover { background: #1565c0; }
        """)
        btn_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(download_url)))
        btn_open.clicked.connect(dlg.accept)

        b_row.addStretch()
        b_row.addWidget(btn_close)
        b_row.addWidget(btn_open)
        body.addLayout(b_row)

        outer.addLayout(body)
        dlg.exec()

    def go_entry(self):
        """⭐ 修改版：立即返回入口，後臺清理"""
        self.resize(900, 600)
        # Step 1️⃣：立即設置停止旗標
        self._request_stop_current_pilot()

        # Step 2️⃣：立即切換 UI 回到入���頁面（重點：不等待）
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
    # 強制把工作目錄切到 exe / 腳本所在資料夾，
    # 避免從捷徑或 updater.bat 啟動時 cwd 跑到 System32 導致 config.json 寫入權限錯誤
    try:
        if getattr(sys, "frozen", False):
            _base_dir = os.path.dirname(sys.executable)
        else:
            _base_dir = os.path.dirname(os.path.abspath(__file__))
        os.chdir(_base_dir)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_QSS)

    # 清理同目錄下的舊版 exe（default.exe、含版本號的 _VX.X.X.exe）
    if getattr(sys, "frozen", False):
        import glob as _glob
        _exe_dir = os.path.dirname(sys.executable)
        _correct = os.path.basename(sys.executable)
        _patterns = [
            os.path.join(_exe_dir, "default.exe"),
            *_glob.glob(os.path.join(_exe_dir, "*_V[0-9]*.[0-9]*.[0-9]*.exe")),
            *_glob.glob(os.path.join(_exe_dir, "*FAKE*.exe")),
        ]
        for _old in _patterns:
            try:
                if os.path.exists(_old) and os.path.basename(_old) != _correct:
                    os.remove(_old)
            except Exception:
                pass
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
