"""使用者資料路徑相容遷移測試。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import app_paths


class AppPathTests(unittest.TestCase):
    def test_default_log_path_creates_directory_without_touching_existing_logs(self):
        with tempfile.TemporaryDirectory(prefix="日誌測試 空白 ") as tmp:
            root = Path(tmp)
            with patch.object(app_paths, "install_root", return_value=root):
                target = app_paths.log_path()
                self.assertEqual(target, root / "data" / "logs" / "app.log")
                self.assertTrue(target.parent.is_dir())
                self.assertFalse(target.exists())
                target.write_text("保留既有日誌", encoding="utf-8")
                self.assertEqual(app_paths.log_dir(), target.parent)
                self.assertEqual(app_paths.log_path(), target)
                self.assertEqual(target.read_text(encoding="utf-8"), "保留既有日誌")

    def test_named_log_path_keeps_filename_inside_logs_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(app_paths, "install_root", return_value=root):
                self.assertEqual(
                    app_paths.log_path("../startup_error.log"),
                    root / "data" / "logs" / "startup_error.log",
                )

    def test_portable_logs_remain_outside_current_application_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(app_paths.sys, "frozen", True, create=True), patch.object(
                app_paths.sys, "executable", str(root / "current" / "領航員.exe")
            ):
                target = app_paths.log_path("update_debug.log")
            self.assertEqual(target, root / "data" / "logs" / "update_debug.log")
            self.assertFalse((root / "current" / "data").exists())

    def test_legacy_data_is_copied_not_moved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "config.json"
            legacy.write_text('{"legacy": true}', encoding="utf-8")
            with patch.object(app_paths, "app_dir", return_value=root), patch.object(
                app_paths, "install_root", return_value=root
            ):
                target = app_paths.user_data_path("config.json")
            self.assertTrue(legacy.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), '{"legacy": true}')
            self.assertEqual(target, root / "data" / "config.json")


if __name__ == "__main__":
    unittest.main()
