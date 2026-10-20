"""2D 遊戲 Q 版工作台主題（高對比度木質與羊皮紙風格）。

維護介面視覺與元件樣式，不介入自動化與業務模型。
"""
from PySide6.QtWidgets import QPushButton, QFrame, QLabel, QTableWidget, QTextEdit, QProgressBar, QComboBox, QLineEdit, QCheckBox, QScrollArea
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
import os
import sys


def _office_asset(name):
    """回傳 QSS 可用的主題素材路徑（正斜線），支援原始碼與 PyInstaller 執行環境。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "icons", "office", name).replace("\\", "/")

# ── 1. 2D 遊戲卡匣／書籤式分頁樣式 ──────────────────────────────
TABS_QSS = """
QTabWidget::pane {
    background: #FFFDF8;
    border: 2px solid #5C3D24;
    border-radius: 10px;
    top: -2px;
}
QTabBar::tab {
    background: #E8D6BC;
    color: #382415;
    border: 2px solid #7D5737;
    border-bottom: 2px solid #5C3D24;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 6px 14px;
    margin-right: 4px;
    font-size: 13px;
    font-weight: 700;
}
QTabBar::tab:!selected {
    background: #E8D6BC;
    color: #382415;
}
QTabBar::tab:selected {
    background: #3B7449;
    color: #FFFFFF;
    border: 2px solid #5C3D24;
    border-bottom: 2px solid #3B7449;
}
QTabBar::tab:hover:!selected {
    background: #F4E7D4;
    color: #1A0F06;
}
QTabBar::tab:focus {
    border: 2px solid #2563EB;
}
"""

# ── 2. Q 彈厚底遊戲按鈕樣式 ──────────────────────────────────
def button_qss(role="normal"):
    """
    產生具備微立體厚下巴（Chunky Bevel）與按壓回饋的 2D Q 版遊戲按鈕 QSS。
    roles: 'start' (綠), 'stop' (紅), 'browser' (藍), 'normal' (米金)
    """
    colors = {
        # 白字按鈕面色皆 ≥ 4.5:1（start 5.0、stop 5.3、browser 5.2）；滑過改深色，避免變淺後對比不足。
        "start":   ("#1B7F47", "#16703E", "#FFFFFF", "#145C34", "#0F4527"),
        "stop":    ("#C8323F", "#B02A36", "#FFFFFF", "#8C1C2A", "#6E1520"),
        "browser": ("#2563EB", "#1D4ED8", "#FFFFFF", "#1A44B8", "#14348C"),
        "normal":  ("#FCE8C3", "#FFF0D4", "#2E1C0F", "#8E623B", "#6C492A"),
    }
    bg, hover, fg, edge, shadow = colors.get(role, colors["normal"])
    return f"""
    QPushButton {{
        background: {bg};
        color: {fg};
        border: 2px solid {edge};
        border-bottom: 4px solid {shadow};
        border-radius: 8px;
        padding: 4px 10px;
        font-size: 12px;
        font-weight: 700;
    }}
    QPushButton:hover {{
        background: {hover};
    }}
    QPushButton:pressed {{
        border-bottom: 2px solid {shadow};
        padding-top: 6px;
    }}
    QPushButton:disabled {{
        background: #DDD4C6;
        color: #5E5548;
        border: 2px solid #B4AA9C;
        border-bottom: 2px solid #B4AA9C;
    }}
    QPushButton:focus {{
        border-color: #F2B705;
    }}
    """

# ── 3. 2D 任務看板表格樣式 (高對比羊皮紙 + 木刻銘牌) ─────────────
TABLE_QSS = """
QTableWidget {
    background-color: #FFFDF8;
    color: #24150B;
    border: 2px solid #5C3D24;
    border-radius: 8px;
    gridline-color: #DFCBB0;
    font-size: 12px;
    font-weight: 500;
    selection-background-color: #CFE4F9;
    selection-color: #0B253E;
}
QHeaderView::section {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #EAD7BA, stop:1 #DCBD93);
    color: #2A1709;
    font-size: 12px;
    font-weight: 800;
    padding: 5px 6px;
    border: 1px solid #9D764A;
    border-bottom: 2px solid #5C3D24;
}
QScrollBar:vertical {
    background: #EFE3D0;
    width: 12px;
    border: 1px solid #C4B094;
    border-radius: 6px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #A07952;
    border: 1px solid #5C3D24;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #BD946A;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: #EFE3D0;
    height: 12px;
    border: 1px solid #C4B094;
    border-radius: 6px;
    margin: 0px;
}
QScrollBar::handle:horizontal {
    background: #A07952;
    border: 1px solid #5C3D24;
    border-radius: 5px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: #BD946A;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
"""

# ── 4. 冒險日誌樣式 (羊皮紙高對比文字) ──────────────────────────
LOG_VIEW_QSS = """
QTextEdit {
    background-color: #FAF5E8;
    color: #21150C;
    selection-background-color: #2563EB;
    selection-color: #FFFFFF;
    border: 2px solid #5C3D24;
    border-radius: 8px;
    font-family: 'Cascadia Mono', 'Consolas', 'Microsoft JhengHei UI', monospace;
    font-size: 12px;
    font-weight: 600;
    padding: 8px 10px;
    line-height: 1.4;
}
QScrollBar:vertical {
    background: #EFE3D0;
    width: 12px;
    border: 1px solid #C4B094;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #A07952;
    border: 1px solid #5C3D24;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #BD946A;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""

# ── 5. EXP 經驗值進度條樣式 ────────────────────────────────────
PROGRESS_BAR_QSS = """
QProgressBar {
    background-color: #E5D5BD;
    color: #1A0F06;
    border: 2px solid #5C3D24;
    border-radius: 8px;
    text-align: center;
    font-weight: 800;
    font-size: 11px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #74D645, stop:1 #43A047);
    border-radius: 5px;
}
"""

# ── 6. 下拉選單樣式 ──────────────────────────────────────────
COMBO_BOX_QSS = """
QComboBox {
    background: #FFFDF8;
    color: #26160B;
    border: 2px solid #7E5B3E;
    border-radius: 7px;
    padding: 4px 8px;
    font-size: 12px;
    font-weight: 600;
    min-height: 22px;
}
QComboBox:hover {
    border-color: #5C3D24;
    background: #FFFFFF;
}
QComboBox:focus {
    border: 2px solid #2563EB;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid #BA9B7F;
    background: #F3E4CD;
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
}
QComboBox::down-arrow {
    image: url(__COMBO_ARROW__);
    width: 10px;
    height: 7px;
}
QComboBox::down-arrow:on {
    top: 1px;
}
QComboBox QAbstractItemView {
    background: #FFFDF8;
    color: #26160B;
    border: 2px solid #5C3D24;
    selection-background-color: #CFE4F9;
    selection-color: #0B253E;
    font-weight: 600;
}
"""

# ── 7. 輸入框樣式 ────────────────────────────────────────────
LINE_EDIT_QSS = """
QLineEdit {
    background: #FFFDF8;
    color: #26160B;
    border: 2px solid #7E5B3E;
    border-radius: 7px;
    padding: 5px 8px;
    font-size: 13px;
    font-weight: 600;
    min-height: 22px;
}
QLineEdit:focus {
    border: 2px solid #2563EB;
    background: #FFFFFF;
}
"""

# ── 8. 複選框樣式 ────────────────────────────────────────────
CHECK_BOX_QSS = """
QCheckBox {
    color: #241409;
    font-size: 13px;
    font-weight: 700;
    spacing: 8px;
    background: transparent;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    background: #FFFDF8;
    border: 2px solid #5C3D24;
    border-radius: 5px;
}
QCheckBox::indicator:hover {
    background: #FFFFFF;
    border-color: #3B7449;
}
QCheckBox::indicator:checked {
    background: #3B7449;
    border: 2px solid #23522E;
    image: url(__CHECK_MARK__);
}
"""

# 勾選標記與下拉箭頭使用 SVG 素材，讓「已勾選」與「可展開」狀態不只靠顏色辨識。
COMBO_BOX_QSS = COMBO_BOX_QSS.replace("__COMBO_ARROW__", _office_asset("combo-arrow.svg"))
CHECK_BOX_QSS = CHECK_BOX_QSS.replace("__CHECK_MARK__", _office_asset("check.svg"))

# ── 9. 滾動區域 QSS ──────────────────────────────────────────
SCROLL_AREA_QSS = """
QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: #EFE3D0;
    width: 12px;
    border: 1px solid #C4B094;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #A07952;
    border: 1px solid #5C3D24;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #BD946A;
}
"""


def assistant_label(path, parent=None):
    """建立 Q 版角色助理裝飾圖示。"""
    label = QLabel(parent)
    label.setObjectName("officeAssistant")
    label.setFixedSize(66, 58)
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet("background: transparent; border: none; padding: 0;")
    pixmap = QPixmap(path)
    if not pixmap.isNull():
        label.setPixmap(pixmap.scaled(66, 58, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    label.setAccessibleName("辦公室研習助理裝飾插畫")
    return label


def apply_office_theme(page):
    """將 2D 遊戲 Q 版高對比度主題套用至主視窗與子元件。"""
    # 1. 最外層視窗背景（暖木書桌色調）
    page.setObjectName("officePage")
    page.setAttribute(Qt.WA_StyledBackground, True)
    page.setStyleSheet("#officePage { background: #DFCAAE; }")

    # 2. 頂部大分頁與工作台內部分頁
    page.tabs.setStyleSheet(TABS_QSS)

    # 3. 頂部標題面板 (銘牌立體木框)
    header = page.findChild(QFrame, "officeHeader")
    if header:
        header.setStyleSheet("""
            QFrame#officeHeader {
                background: #FFFBF2;
                border: 2px solid #5C3D24;
                border-bottom: 4px solid #432A17;
                border-radius: 12px;
            }
        """)

    # 4. 初次使用橫幅
    banner = page.findChild(QFrame, "onboardingBanner")
    if banner:
        banner.setStyleSheet("""
            QFrame#onboardingBanner {
                background: #FFF8E1;
                border: 2px solid #E0A800;
                border-bottom: 3px solid #B28500;
                border-radius: 10px;
                padding: 4px 10px;
            }
            QLabel {
                color: #4E342E;
                font-weight: 700;
                background: transparent;
                border: none;
            }
        """)

    # 5. 雙平台面板樣式深度客製
    for panel in (page.taipei_panel, page.egov_panel):
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setObjectName("officePlatform")
        panel.setStyleSheet("#officePlatform { background: #FFFDF8; border-radius: 8px; }")

        # 內層分頁
        panel.workspace_tabs.setStyleSheet(TABS_QSS)

        # 操作卡片 (立體 2D 邊框)
        ctrl_card = panel.findChild(QFrame, "ctrlRibbonCard")
        if ctrl_card:
            ctrl_card.setStyleSheet("""
                QFrame#ctrlRibbonCard {
                    background: #FFFBF2;
                    border: 2px solid #5C3D24;
                    border-bottom: 4px solid #432A17;
                    border-radius: 12px;
                    padding: 4px 10px;
                }
            """)

        # 頂部控制按鈕
        panel.start_btn.setStyleSheet(button_qss("start"))
        panel.stop_btn.setStyleSheet(button_qss("stop"))
        panel.toggle_browser_btn.setStyleSheet(button_qss("browser"))

        # 下拉選單與進度條
        panel.exam_mode_combo.setStyleSheet(COMBO_BOX_QSS)
        panel.progress_bar.setStyleSheet(PROGRESS_BAR_QSS)

        # 標籤文字顏色加深，保證高對比清晰度
        panel.info_lbl.setStyleSheet("color: #241409; font-weight: 800; font-size: 14px; background: transparent; border: none;")
        panel.execution_status_lbl.setStyleSheet("color: #4A3322; font-size: 12px; font-weight: 700; background: transparent; border: none;")
        panel.total_progress_lbl.setStyleSheet("color: #382415; font-size: 12px; font-weight: 700; border: none; background: transparent;")
        panel.stats_lbl.setStyleSheet("color: #241409; font-size: 12px; font-weight: 700; border: none; background: transparent;")

        # 空狀態標籤 (任務板尚未開展)
        if hasattr(panel, "empty_state_lbl"):
            panel.empty_state_lbl.setStyleSheet("""
                QLabel {
                    background: #FFFDF8;
                    color: #5C3D24;
                    border: 2px dashed #9E7955;
                    border-radius: 8px;
                    padding: 10px 14px;
                    font-size: 12px;
                    font-weight: 700;
                }
            """)

        # 任務告示板表格
        panel.course_table.setStyleSheet(TABLE_QSS)

        # 冒險日誌 (Debug Log)
        panel.log_view.setStyleSheet(LOG_VIEW_QSS)

        # 工作台內部其他標籤與按鈕 (複製日誌、開啟資料夾、清空畫面等)
        for lbl in panel.workspace_tabs.findChildren(QLabel):
            if "即時除錯日誌" in lbl.text():
                lbl.setStyleSheet("color: #382415; font-size: 12px; font-weight: 700; background: transparent;")
        for btn in panel.workspace_tabs.findChildren(QPushButton):
            btn.setStyleSheet(button_qss("normal"))

    # 6. 頂部通用控制按鈕與標題
    page.start_all_btn.setStyleSheet(button_qss("start"))
    page.stop_all_btn.setStyleSheet(button_qss("stop"))
    page.check_update_btn.setStyleSheet(button_qss("normal"))
    page.ver_badge.setStyleSheet("""
        background: #5C3D24;
        color: #FFFDF8;
        border: 1px solid #3E2718;
        border-radius: 6px;
        padding: 3px 8px;
        font-weight: 800;
    """)

    # 7. 系統設定面板深度客製
    for frame in page.settings_panel.findChildren(QFrame):
        if frame.property("class") == "settingSectionCard":
            frame.setStyleSheet("""
                QFrame.settingSectionCard {
                    background: #FFFBF2;
                    border: 2px solid #5C3D24;
                    border-bottom: 4px solid #432A17;
                    border-radius: 12px;
                    padding: 12px 14px;
                }
                QFrame.settingSectionCard QLabel {
                    background: transparent;
                    border: none;
                    color: #241409;
                    font-weight: 700;
                }
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
            lbl.setStyleSheet("color: #241409; font-weight: 800; font-size: 16px; background: transparent;")
