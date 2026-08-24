"""使用者資料路徑相容遷移測試。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import app_paths


class AppPathTests(unittest.TestCase):
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
