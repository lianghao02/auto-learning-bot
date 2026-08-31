"""人機協同測驗視窗的基本建立測試。"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui import InteractiveQuizDialog, PlatformTabPanel


class InteractiveQuizDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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

