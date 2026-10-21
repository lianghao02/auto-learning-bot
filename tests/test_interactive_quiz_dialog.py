"""人機協同測驗視窗的基本建立測試。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from ui import InteractiveQuizDialog, PlatformTabPanel
from utils import app_paths


class InteractiveQuizDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _log_directory_button(self):
        panel = PlatformTabPanel("ecpa", "測試平臺", lambda *_: None, lambda *_: None, lambda *_: None)
        self.addCleanup(panel.close)
        buttons = [button for button in panel.findChildren(QPushButton) if button.text() == "📁 開啟日誌資料夾"]
        self.assertEqual(len(buttons), 1)
        return panel, buttons[0]

    def test_log_directory_button_creates_and_opens_the_data_logs_directory(self):
        with tempfile.TemporaryDirectory(prefix="介面日誌 中文 空白 ") as tmp:
            root = Path(tmp)
            with patch.object(app_paths, "install_root", return_value=root), patch(
                "ui.os.startfile", create=True
            ) as open_folder, patch("ui.QMessageBox.warning") as warning:
                _, button = self._log_directory_button()
                button.click()
                expected = root / "data" / "logs"
                self.assertTrue(expected.is_dir())
                open_folder.assert_called_once_with(str(expected))
                warning.assert_not_called()

    def test_log_directory_open_failure_shows_warning_without_changing_existing_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs = root / "data" / "logs"
            logs.mkdir(parents=True)
            existing = logs / "app.log"
            existing.write_text("既有日誌不可覆寫", encoding="utf-8")
            with patch.object(app_paths, "install_root", return_value=root), patch(
                "ui.os.startfile", side_effect=OSError("合成開啟錯誤"), create=True
            ) as open_folder, patch("ui.QMessageBox.warning") as warning:
                panel, button = self._log_directory_button()
                button.click()
                open_folder.assert_called_once_with(str(logs))
                warning.assert_called_once_with(panel, "開啟失敗", "無法開啟日誌資料夾：合成開啟錯誤")
                self.assertEqual(existing.read_text(encoding="utf-8"), "既有日誌不可覆寫")

    def test_dialog_can_be_created_with_question_data(self):
        dialog = InteractiveQuizDialog(
            "測試課程",
            [{"index": 1, "type": "單選", "q_text": "測試題目", "options": [{"label": "A", "text": "選項 A"}]}],
        )

        self.assertIn("測試課程", dialog.windowTitle())
        self.assertEqual(dialog.remaining_sec, 180)
        dialog.close()

    def test_exam_modes_are_combined_and_mutually_exclusive(self):
        panel = PlatformTabPanel("ecpa", "e等公務員", lambda *_: None, lambda *_: None, lambda *_: None)

        modes = [panel.exam_mode_combo.itemData(i) for i in range(panel.exam_mode_combo.count())]
        self.assertEqual(modes, ["sqlite", "interactive", "skip", "gemini_direct"])
        self.assertEqual(panel.exam_mode_combo.currentData(), "sqlite")
        self.assertFalse(hasattr(panel, "skip_exam_checkbox"))
        self.assertFalse(hasattr(panel, "interactive_quiz_checkbox"))
        panel.close()

    def test_compact_ribbon_and_control_states(self):
        panel = PlatformTabPanel("taipei_eda", "臺北E大", lambda *_: None, lambda *_: None, lambda *_: None)

        self.assertTrue(panel.start_btn.isEnabled())
        self.assertFalse(panel.stop_btn.isEnabled())
        self.assertEqual(panel.progress_bar.value(), 0)

        # 模擬啟動執行狀態
        panel.set_running_state(True)
        self.assertFalse(panel.start_btn.isEnabled())
        self.assertTrue(panel.stop_btn.isEnabled())
        self.assertFalse(panel.exam_mode_combo.isEnabled())

        # 模擬停止執行狀態
        panel.set_running_state(False)
        self.assertTrue(panel.start_btn.isEnabled())
        self.assertFalse(panel.stop_btn.isEnabled())
        self.assertTrue(panel.exam_mode_combo.isEnabled())
        panel.close()

    def test_in_row_focus_table_highlighting(self):
        from models.course_state import CourseState, CourseStatus

        panel = PlatformTabPanel("taipei_eda", "臺北E大", lambda *_: None, lambda *_: None, lambda *_: None)

        # 1. 進行中課程狀態
        s1 = CourseState(
            course_id="c1",
            course_name="公務法律實務",
            platform="taipei_eda",
            status=CourseStatus.LEARNING,
            current_time_str="00:30:00",
            required_time_str="01:00:00",
            progress_pct=50.0,
            reason="正在研習章節",
            next_step="接續播放下一段影片",
        )
        panel._handle_course_state_update(s1)

        self.assertEqual(panel.course_table.rowCount(), 1)
        item1 = panel.course_table.item(0, 0)
        self.assertTrue(item1.text().startswith("▶ "))
        self.assertTrue(item1.font().bold())
        self.assertEqual(panel.progress_bar.value(), 50)

        # 2. 已完成課程狀態
        s2 = CourseState(
            course_id="c2",
            course_name="行政公文解析",
            platform="taipei_eda",
            status=CourseStatus.COMPLETED,
            current_time_str="01:00:00",
            required_time_str="01:00:00",
            progress_pct=100.0,
            reason="時數與測驗皆已達標",
            next_step="全數修畢",
        )
        panel._handle_course_state_update(s2)

        self.assertEqual(panel.course_table.rowCount(), 2)
        item2 = panel.course_table.item(1, 0)
        self.assertFalse(item2.text().startswith("▶ "))
        self.assertFalse(item2.font().bold())

        # 3. 需人工確認 / 異常狀態色彩與背景高亮驗證
        s3 = CourseState(
            course_id="c3",
            course_name="採購法實務",
            platform="taipei_eda",
            status=CourseStatus.MANUAL_REVIEW,
            needs_manual=True,
            reason="連續不及格達上限",
            next_step="人工確認",
        )
        panel._handle_course_state_update(s3)
        badge3 = panel.course_table.item(2, 1)
        self.assertEqual(badge3.foreground().color().name().upper(), CourseStatus.MANUAL_REVIEW.color_hex.upper())
        from utils.office_theme import ROW_COLORS
        self.assertEqual(badge3.background().color().name().upper(), ROW_COLORS["alert"])
        self.assertTrue(panel.empty_state_lbl.isHidden())
        panel.close()

    def test_empty_state_banner_transitions(self):
        panel = PlatformTabPanel("taipei_eda", "臺北E大", lambda *_: None, lambda *_: None, lambda *_: None)
        self.addCleanup(panel.close)

        self.assertIn("尚無課程資料", panel.empty_state_lbl.text())
        panel.set_running_state(True)
        self.assertIn("正在登入並掃描課程清單", panel.empty_state_lbl.text())
        panel.set_running_state(False)
        self.assertIn("尚無課程資料", panel.empty_state_lbl.text())

    def test_account_settings_unsaved_changes_and_cloud_sync_toggle(self):
        from ui import AccountSettingsTabPanel
        from PySide6.QtWidgets import QLineEdit
        import quiz_bank

        with tempfile.TemporaryDirectory() as tmp:
            cfg_file = Path(tmp) / "config.json"
            with patch("ui.CONFIG_PATH", str(cfg_file)):
                settings_panel = AccountSettingsTabPanel()
                self.addCleanup(settings_panel.close)

                self.assertFalse(settings_panel.has_unsaved_changes())
                self.assertEqual(settings_panel.pwd_input.echoMode(), QLineEdit.Password)

                # 修改表單欄位後應偵測為有未儲存變更
                settings_panel.acc_input.setText("user01")
                settings_panel.pwd_input.setText("secret123")
                settings_panel.cloud_sync_cb.setChecked(False)
                self.assertTrue(settings_panel.has_unsaved_changes())

                # 靜默儲存後應寫入檔案並清除未儲存狀態
                saved_ok = settings_panel.save_settings(silent=True)
                self.assertTrue(saved_ok)
                self.assertFalse(settings_panel.has_unsaved_changes())

                # 驗證 cloud_sync_enabled=False 時 quiz_bank 不發送外部 GAS 請求
                with patch("quiz_bank.requests.get") as mock_get, patch("quiz_bank.requests.post") as mock_post:
                    bank = quiz_bank.gas_fetch_bank("123", config={"cloud_sync_enabled": False})
                    self.assertEqual(bank, {})
                    mock_get.assert_not_called()

                    quiz_bank.gas_save_questions(
                        "123",
                        [{"q_text": "測試題", "val": "0"}],
                        config={"cloud_sync_enabled": False},
                    )
                    mock_post.assert_not_called()


