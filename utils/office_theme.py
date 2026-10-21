"""2D 遊戲 Q 版工作台主題（晴空糖果風：粗墨線外框、厚底按鈕、深色冒險日誌）。

維護介面視覺與元件樣式，不介入自動化與業務模型。
所有文字色彩組合皆維持 WCAG AA 4.5:1 以上（見 tests/test_office_theme.py）。
"""
from html import escape
import os
import sys

from PySide6.QtWidgets import QPushButton, QFrame, QLabel, QLineEdit, QCheckBox, QComboBox, QScrollArea
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from utils.log_feed import CATEGORIES


def _office_asset(name):
    """回傳 QSS 可用的主題素材路徑（正斜線），支援原始碼與 PyInstaller 執行環境。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "icons", "office", name).replace("\\", "/")


# ── 0. 色票（單一來源） ─────────────────────────────────────
INK = "#26304A"            # 卡通墨線：外框、標題文字
INK_DEEP = "#171E31"       # 厚底陰影
SKY_TOP = "#8FD3F4"        # 背景天空漸層
SKY_BOTTOM = "#D4EFFA"
CARD = "#FFFFFF"
CREAM = "#FFF8E6"
BUTTER = "#FFE38A"         # 次要按鈕、徽章
SUN = "#FFC93C"            # 選中分頁、焦點
ICE = "#E8F4FC"            # 未選中分頁、輸入框底
MINT = "#3DBE5A"

# 任務板列底色：一般、斑馬、進行中、需注意
ROW_COLORS = {
    "even": "#FFFFFF",
    "odd": "#F1F7FC",
    "active": "#E2F6E6",
    "alert": "#FDECEC",
}

# 冒險日誌（深色夜空底）
LOG_BG = "#1E2440"
LOG_TEXT = "#EEF1FF"
LOG_TIME = "#93A4D6"
LOG_DETAIL = "#9AA5CC"
LOG_LEVEL_COLORS = {"ERROR": "#FF8F8F", "CRITICAL": "#FF8F8F", "WARNING": "#FFD166"}
LOG_SUCCESS = "#8DF0A8"
LOG_HEADER = "#FFE38A"
LOG_MILESTONE = "#7FE0FF"
LOG_CARD_BG = "#2F3A6B"
LOG_CHIP_COLORS = {
    "login": "#FFD166",
    "course": "#7FD8F0",
    "study": "#8EE3A5",
    "quiz": "#FFB4A2",
    "survey": "#D2B8FF",
    "bank": "#F7E08F",
    "system": "#C9D1E8",
}


# ── 1. 卡匣式分頁 ─────────────────────────────────────────
TABS_QSS = f"""
QTabWidget::pane {{
    background: {CARD};
    border: 2px solid {INK};
    border-radius: 14px;
    top: -2px;
}}
QTabBar::tab {{
    background: {ICE};
    color: {INK};
    border: 2px solid {INK};
    border-bottom: 2px solid {INK};
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
    padding: 6px 16px;
    margin-right: 4px;
    font-size: 13px;
    font-weight: 800;
}}
QTabBar::tab:selected {{
    background: {SUN};
    color: {INK};
    border-bottom: 2px solid {SUN};
}}
QTabBar::tab:hover:!selected {{
    background: #FFF1C2;
}}
QTabBar::tab:focus {{
    border: 2px solid #2563EB;
}}
"""


# ── 2. Q 彈厚底遊戲按鈕 ─────────────────────────────────────
def button_qss(role="normal"):
    """
    卡通厚底按鈕：統一墨線外框＋5px 底部陰影，按下時陰影收合產生下壓感。
    roles: 'start' (綠), 'stop' (紅), 'browser' (藍), 'normal' (奶油黃)
    """
    colors = {
        # 面色、滑過色、文字色；白字面色皆 ≥ 4.5:1（start 5.0、stop 5.3、browser 5.2）
        "start":   ("#1B7F47", "#146B3B", "#FFFFFF"),
        "stop":    ("#C8323F", "#A92A35", "#FFFFFF"),
        "browser": ("#2563EB", "#1D4ED8", "#FFFFFF"),
        "normal":  (BUTTER, "#FFD75E", INK),
    }
    bg, hover, fg = colors.get(role, colors["normal"])
    return f"""
    QPushButton {{
        background: {bg};
        color: {fg};
        border: 2px solid {INK};
        border-bottom: 5px solid {INK_DEEP};
        border-radius: 12px;
        padding: 4px 12px;
        font-size: 12px;
        font-weight: 800;
    }}
    QPushButton:hover {{
        background: {hover};
    }}
    QPushButton:pressed {{
        border-bottom: 2px solid {INK_DEEP};
        padding-top: 7px;
    }}
    QPushButton:disabled {{
        background: #DCE3EA;
        color: #4F5B6B;
        border: 2px solid #9AA6B5;
        border-bottom: 3px solid #9AA6B5;
    }}
    QPushButton:focus {{
        border-color: #E09B00;
    }}
    """


# ── 3. 任務告示板表格 ──────────────────────────────────────
_SCROLLBAR_QSS = f"""
QScrollBar:vertical {{
    background: {ICE};
    width: 12px;
    border: 1px solid #B9CFE0;
    border-radius: 6px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #8AB4D8;
    border: 1px solid {INK};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: #6E9FCB;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {ICE};
    height: 12px;
    border: 1px solid #B9CFE0;
    border-radius: 6px;
    margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: #8AB4D8;
    border: 1px solid {INK};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
"""

TABLE_QSS = f"""
QTableWidget {{
    background-color: {CARD};
    color: {INK};
    border: 2px solid {INK};
    border-radius: 10px;
    gridline-color: #D5E3EF;
    font-size: 12px;
    font-weight: 500;
    selection-background-color: #CFE4F9;
    selection-color: #0B253E;
}}
QHeaderView::section {{
    background: {INK};
    color: {BUTTER};
    font-size: 12px;
    font-weight: 800;
    padding: 6px 6px;
    border: none;
    border-right: 1px solid #3A4666;
}}
QTableCornerButton::section {{
    background: {INK};
    border: none;
}}
""" + _SCROLLBAR_QSS


# ── 4. 冒險日誌（深色夜空底，事件色彩見 render_log_entry） ─────────
LOG_VIEW_QSS = f"""
QTextEdit {{
    background-color: {LOG_BG};
    color: {LOG_TEXT};
    selection-background-color: #4C6FFF;
    selection-color: #FFFFFF;
    border: 2px solid {INK};
    border-radius: 12px;
    font-family: 'Microsoft JhengHei UI', 'Segoe UI', sans-serif;
    font-size: 12px;
    padding: 8px 10px;
}}
QScrollBar:vertical {{
    background: #283055;
    width: 12px;
    border: none;
    border-radius: 6px;
}}
QScrollBar::handle:vertical {{
    background: #56629A;
    border-radius: 6px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: #7180C2;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""

LOG_CHIP_QSS = f"""
QPushButton#logFilterChip {{
    background: {ICE};
    color: {INK};
    border: 2px solid {INK};
    border-radius: 13px;
    padding: 3px 12px;
    font-size: 12px;
    font-weight: 800;
}}
QPushButton#logFilterChip:hover {{
    background: #FFF1C2;
}}
QPushButton#logFilterChip:checked {{
    background: {SUN};
}}
QPushButton#logIssueBadge {{
    background: #FDECEC;
    color: #9E2F2A;
    border: 2px solid #9E2F2A;
    border-radius: 13px;
    padding: 3px 10px;
    font-size: 12px;
    font-weight: 800;
}}
"""

LIVE_CARD_QSS = f"""
QFrame#liveCard {{
    background: {LOG_CARD_BG};
    border: 2px solid {INK};
    border-bottom: 5px solid {INK_DEEP};
    border-radius: 12px;
}}
QLabel#liveIcon {{
    background: {SUN};
    color: {INK};
    border: 2px solid {INK};
    border-radius: 15px;
    min-width: 26px; max-width: 26px;
    min-height: 26px; max-height: 26px;
    font-size: 14px;
    qproperty-alignment: AlignCenter;
}}
QLabel#liveCourse {{
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 800;
    background: transparent;
    border: none;
}}
QLabel#liveDetail {{
    color: #C9D3F5;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
    border: none;
}}
QProgressBar#liveProgress {{
    background: #1B2140;
    color: #FFFFFF;
    border: 2px solid {INK_DEEP};
    border-radius: 9px;
    text-align: center;
    font-size: 11px;
    font-weight: 800;
}}
QProgressBar#liveProgress::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F8A3E, stop:1 #176E31);
    border-radius: 7px;
}}
"""


def render_log_entry(entry):
    """把 LogEntry 轉成 QTextEdit 可顯示的 HTML（單一段落）。"""
    label, icon = CATEGORIES.get(entry.category, ("系統", "⚙"))
    chip_bg = LOG_CHIP_COLORS.get(entry.category, LOG_CHIP_COLORS["system"])
    text = escape(entry.text)
    time_html = f'<span style="color:{LOG_TIME}; font-family:Consolas,monospace;">{escape(entry.time)}</span>'
    chip = f'<span style="background-color:{chip_bg}; color:{LOG_BG}; font-weight:800;">&nbsp;{icon} {label}&nbsp;</span>'
    repeat = f' <span style="color:{LOG_HEADER}; font-weight:800;">×{entry.repeat}</span>' if entry.repeat > 1 else ""

    if entry.kind == "header":
        body = f'<span style="color:{LOG_HEADER}; font-size:13px; font-weight:800;">◆ {text}</span>'
        return f'<p style="margin-top:8px;">{time_html}&nbsp; {chip}&nbsp; {body}{repeat}</p>'
    if entry.kind == "card":
        color = LOG_LEVEL_COLORS.get(entry.level, "#FFFFFF")
        body = f'<span style="background-color:{LOG_CARD_BG}; color:{color}; font-weight:700;">&nbsp;{text}&nbsp;</span>'
        return f'<p>{time_html}&nbsp; {chip}&nbsp; {body}{repeat}</p>'
    if entry.kind == "detail":
        body = f'<span style="color:{LOG_DETAIL}; font-size:11px;">　· {text}</span>'
        return f'<p>{time_html}&nbsp; {body}{repeat}</p>'

    if entry.level in LOG_LEVEL_COLORS:
        color, weight = LOG_LEVEL_COLORS[entry.level], 800
    elif entry.kind == "milestone":
        color, weight = LOG_MILESTONE, 700
    elif entry.is_success:
        color, weight = LOG_SUCCESS, 700
    else:
        color, weight = LOG_TEXT, 500
    body = f'<span style="color:{color}; font-weight:{weight};">{text}</span>'
    return f'<p>{time_html}&nbsp; {chip}&nbsp; {body}{repeat}</p>'


# ── 5. 進度條（血條風） ─────────────────────────────────────
PROGRESS_BAR_QSS = f"""
QProgressBar {{
    background-color: {ICE};
    color: {INK};
    border: 2px solid {INK};
    border-radius: 10px;
    text-align: center;
    font-weight: 900;
    font-size: 11px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8BE88A, stop:1 {MINT});
    border-radius: 7px;
}}
"""

# ── 6. 下拉選單 ──────────────────────────────────────────
COMBO_BOX_QSS = f"""
QComboBox {{
    background: {CARD};
    color: {INK};
    border: 2px solid {INK};
    border-radius: 10px;
    padding: 4px 8px;
    font-size: 12px;
    font-weight: 700;
    min-height: 22px;
}}
QComboBox:hover {{
    background: #FFFDF2;
}}
QComboBox:focus {{
    border: 2px solid #2563EB;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 2px solid {INK};
    background: {BUTTER};
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}}
QComboBox::down-arrow {{
    image: url(__COMBO_ARROW__);
    width: 10px;
    height: 7px;
}}
QComboBox::down-arrow:on {{
    top: 1px;
}}
QComboBox QAbstractItemView {{
    background: {CARD};
    color: {INK};
    border: 2px solid {INK};
    selection-background-color: {SUN};
    selection-color: {INK};
    font-weight: 600;
}}
"""

# ── 7. 輸入框 ────────────────────────────────────────────
LINE_EDIT_QSS = f"""
QLineEdit {{
    background: {CARD};
    color: {INK};
    border: 2px solid {INK};
    border-radius: 10px;
    padding: 5px 8px;
    font-size: 13px;
    font-weight: 600;
    min-height: 22px;
}}
QLineEdit:focus {{
    border: 2px solid #2563EB;
    background: #FFFDF2;
}}
"""

# ── 8. 複選框 ────────────────────────────────────────────
CHECK_BOX_QSS = f"""
QCheckBox {{
    color: {INK};
    font-size: 13px;
    font-weight: 700;
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    background: {CARD};
    border: 2px solid {INK};
    border-radius: 6px;
}}
QCheckBox::indicator:hover {{
    background: #FFF1C2;
}}
QCheckBox::indicator:checked {{
    background: #1B7F47;
    border: 2px solid {INK};
    image: url(__CHECK_MARK__);
}}
"""

# 勾選標記與下拉箭頭使用 SVG 素材，讓「已勾選／可展開」狀態不只靠顏色辨識。
COMBO_BOX_QSS = COMBO_BOX_QSS.replace("__COMBO_ARROW__", _office_asset("combo-arrow.svg"))
CHECK_BOX_QSS = CHECK_BOX_QSS.replace("__CHECK_MARK__", _office_asset("check.svg"))

# ── 9. 滾動區域 ──────────────────────────────────────────
SCROLL_AREA_QSS = """
QScrollArea {
    background: transparent;
    border: none;
}
""" + _SCROLLBAR_QSS

CARD_QSS = f"""
    background: {CARD};
    border: 2px solid {INK};
    border-bottom: 5px solid {INK_DEEP};
    border-radius: 16px;
"""


def assistant_label(path, parent=None):
    """建立 Q 版角色助理頭像（圓形徽章框）。"""
    label = QLabel(parent)
    label.setObjectName("officeAssistant")
    label.setFixedSize(64, 64)
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet(f"background: {BUTTER}; border: 2px solid {INK}; border-radius: 32px; padding: 2px;")
    pixmap = QPixmap(path)
    if not pixmap.isNull():
        label.setPixmap(pixmap.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    label.setAccessibleName("辦公室研習助理裝飾插畫")
    return label


def apply_office_theme(page):
    """將 2D 遊戲 Q 版主題套用至主視窗與子元件。"""
    # 1. 最外層視窗背景（晴空漸層）
    page.setObjectName("officePage")
    page.setAttribute(Qt.WA_StyledBackground, True)
    page.setStyleSheet(
        f"#officePage {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {SKY_TOP}, stop:1 {SKY_BOTTOM}); }}"
    )

    # 2. 頂部大分頁
    page.tabs.setStyleSheet(TABS_QSS)

    # 3. 頂部標題面板
    header = page.findChild(QFrame, "officeHeader")
    if header:
        header.setStyleSheet(f"QFrame#officeHeader {{ {CARD_QSS} }}")
    if hasattr(page, "title_lbl"):
        page.title_lbl.setStyleSheet(f"color: {INK}; font-weight: 900; font-size: 20px; background: transparent; border: none;")

    # 4. 初次使用橫幅
    banner = page.findChild(QFrame, "onboardingBanner")
    if banner:
        banner.setStyleSheet(f"""
            QFrame#onboardingBanner {{
                background: #FFF4C7;
                border: 2px solid {INK};
                border-bottom: 4px solid {INK_DEEP};
                border-radius: 12px;
                padding: 4px 10px;
            }}
            QLabel {{
                color: {INK};
                font-weight: 700;
                background: transparent;
                border: none;
            }}
        """ + button_qss("browser"))

    # 5. 雙平台面板
    for panel in (page.taipei_panel, page.egov_panel):
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setObjectName("officePlatform")
        panel.setStyleSheet(f"#officePlatform {{ background: {CREAM}; border-radius: 12px; }}")
        panel.workspace_tabs.setStyleSheet(TABS_QSS)

        ctrl_card = panel.findChild(QFrame, "ctrlRibbonCard")
        if ctrl_card:
            ctrl_card.setStyleSheet(f"QFrame#ctrlRibbonCard {{ {CARD_QSS} padding: 4px 10px; }}")

        panel.start_btn.setStyleSheet(button_qss("start"))
        panel.stop_btn.setStyleSheet(button_qss("stop"))
        panel.toggle_browser_btn.setStyleSheet(button_qss("browser"))
        panel.exam_mode_combo.setStyleSheet(COMBO_BOX_QSS)
        panel.progress_bar.setStyleSheet(PROGRESS_BAR_QSS)

        panel.info_lbl.setStyleSheet(f"color: {INK}; font-weight: 900; font-size: 15px; background: transparent; border: none;")
        panel.execution_status_lbl.setStyleSheet(f"color: {INK}; font-size: 12px; font-weight: 700; background: transparent; border: none;")
        panel.total_progress_lbl.setStyleSheet(f"""
            color: {INK}; font-size: 12px; font-weight: 800;
            background: {BUTTER}; border: 2px solid {INK}; border-radius: 11px; padding: 2px 10px;
        """)
        panel.stats_lbl.setStyleSheet(f"color: {INK}; font-size: 12px; font-weight: 700; border: none; background: transparent;")

        if hasattr(panel, "empty_state_lbl"):
            panel.empty_state_lbl.setStyleSheet(f"""
                QLabel {{
                    background: {CREAM};
                    color: {INK};
                    border: 2px dashed {INK};
                    border-radius: 12px;
                    padding: 10px 14px;
                    font-size: 12px;
                    font-weight: 700;
                }}
            """)

        panel.course_table.setStyleSheet(TABLE_QSS)

        # 冒險日誌：篩選膠囊、即時卡片與事件流
        panel.log_view.setStyleSheet(LOG_VIEW_QSS)
        if hasattr(panel, "live_card"):
            panel.live_card.setStyleSheet(LIVE_CARD_QSS)
        for btn in panel.workspace_tabs.findChildren(QPushButton):
            if btn.objectName() in ("logFilterChip", "logIssueBadge"):
                btn.setStyleSheet(LOG_CHIP_QSS)
            else:
                btn.setStyleSheet(button_qss("normal"))

    # 6. 頂部通用控制按鈕與標題
    page.start_all_btn.setStyleSheet(button_qss("start"))
    page.stop_all_btn.setStyleSheet(button_qss("stop"))
    page.check_update_btn.setStyleSheet(button_qss("normal"))
    page.ver_badge.setStyleSheet(f"""
        background: {SUN};
        color: {INK};
        border: 2px solid {INK};
        border-radius: 10px;
        padding: 2px 9px;
        font-weight: 900;
    """)

    # 7. 系統設定面板
    for frame in page.settings_panel.findChildren(QFrame):
        if frame.property("class") == "settingSectionCard":
            frame.setStyleSheet(f"""
                QFrame.settingSectionCard {{
                    {CARD_QSS}
                    padding: 12px 14px;
                }}
                QFrame.settingSectionCard QLabel {{
                    background: transparent;
                    border: none;
                    color: {INK};
                    font-weight: 700;
                }}
            """)
    for line_edit in page.settings_panel.findChildren(QLineEdit):
        line_edit.setStyleSheet(LINE_EDIT_QSS)
    for combo in page.settings_panel.findChildren(QComboBox):
        combo.setStyleSheet(COMBO_BOX_QSS)
    for cb in page.settings_panel.findChildren(QCheckBox):
        cb.setStyleSheet(CHECK_BOX_QSS)
    for btn in page.settings_panel.findChildren(QPushButton):
        btn.setStyleSheet(button_qss("normal"))
    for scroll in page.settings_panel.findChildren(QScrollArea):
        scroll.setStyleSheet(SCROLL_AREA_QSS)
    for lbl in page.settings_panel.findChildren(QLabel):
        if "帳號管理與系統設定" in lbl.text():
            lbl.setStyleSheet(f"color: {INK}; font-weight: 900; font-size: 16px; background: transparent;")
