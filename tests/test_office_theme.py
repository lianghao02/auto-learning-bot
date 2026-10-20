"""辦公室主題的操作相容性與摘要更新測試。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from models.course_state import CourseState, CourseStatus
from ui import ImmersivePage


class OfficeThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = patch("ui.CONFIG_PATH", str(Path(self.tmp.name) / "config.json"))
        self.cfg.start()
        self.addCleanup(self.cfg.stop)
        self.stop = Mock()
        self.page = ImmersivePage(self.stop)
        self.addCleanup(self.page.close)

    def test_existing_toolbar_and_platform_callbacks(self):
        page = self.page
        page.on_start_all = Mock()
        page.on_check_update = Mock()
        page.on_start_platform = Mock()
        page.on_stop_platform = Mock()
        page.on_toggle_browser = Mock()
        page.start_all_btn.click()
        page.stop_all_btn.click()
        page.check_update_btn.click()
        page.on_start_all.assert_called_once_with()
        self.stop.assert_called_once_with()
        page.on_check_update.assert_called_once_with()
        for panel in (page.taipei_panel, page.egov_panel):
            panel.start_btn.click()
            page.on_start_platform.assert_called_with(panel.platform_key)
            panel.set_running_state(True)
            panel.stop_btn.click()
            page.on_stop_platform.assert_called_with(panel.platform_key)
            panel.toggle_browser_btn.click()
            page.on_toggle_browser.assert_called_with(panel.platform_key, True)

    def test_loaded_summary_replaces_existing_course_without_double_count(self):
        panel = self.page.taipei_panel
        def update(key, status):
            panel._handle_course_state_update(CourseState(key, "合成課程", "taipei_eda", status=status))
        update("a", CourseStatus.WAITING)
        update("b", CourseStatus.LEARNING)
        update("a", CourseStatus.COMPLETED)
        self.assertEqual(panel.course_table.rowCount(), 2)
        self.assertEqual(panel.total_progress_lbl.text(), "已載入課程：2 門｜完成 1 門（50%）")
        update("a", CourseStatus.ERROR)
        self.assertIn("完成 0 門（0%）", panel.total_progress_lbl.text())

    def test_art_and_account_display(self):
        panel = self.page.taipei_panel
        self.assertFalse(panel.assistant_art.pixmap().isNull())
        panel.update_account_info("示範使用者", "sensitive-account")
        self.assertIn("示範使用者", panel.info_lbl.text())
        self.assertNotIn("sensitive-account", panel.info_lbl.text())


def _luminance(hex_color):
    channels = [int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(fg, bg):
    high, low = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class OfficeThemeContrastTests(unittest.TestCase):
    """主題色彩須達 WCAG AA 一般文字 4.5:1，避免改色時再出現低對比。"""

    ROW_BACKGROUNDS = ("#FFFDF8", "#F7EEDC", "#EAF1EE", "#FDF2F2")

    def test_status_colors_readable_on_every_row_background(self):
        for status in CourseStatus:
            for bg in self.ROW_BACKGROUNDS:
                with self.subTest(status=status.name, bg=bg):
                    self.assertGreaterEqual(_contrast(status.color_hex, bg), 4.5)

    def test_button_text_readable_in_normal_hover_and_disabled_states(self):
        import re
        from utils.office_theme import button_qss
        for role in ("start", "stop", "browser", "normal"):
            qss = button_qss(role)
            fg = re.search(r"QPushButton \{\{?\s*background: (#\w{6});\s*color: (#\w{6})", qss)
            hover = re.search(r"QPushButton:hover \{\{?\s*background: (#\w{6})", qss)
            disabled = re.search(r"QPushButton:disabled \{\{?\s*background: (#\w{6});\s*color: (#\w{6})", qss)
            with self.subTest(role=role):
                self.assertGreaterEqual(_contrast(fg.group(2), fg.group(1)), 4.5)
                self.assertGreaterEqual(_contrast(fg.group(2), hover.group(1)), 4.5)
                self.assertGreaterEqual(_contrast(disabled.group(2), disabled.group(1)), 4.5)

    def test_checkbox_and_combo_assets_exist(self):
        import re
        from utils import office_theme
        for marker, qss in (("check.svg", office_theme.CHECK_BOX_QSS), ("combo-arrow.svg", office_theme.COMBO_BOX_QSS)):
            path = re.search(r"url\(([^)]+)\)", qss).group(1)
            with self.subTest(asset=marker):
                self.assertTrue(path.endswith(marker))
                self.assertTrue(Path(path).is_file())
