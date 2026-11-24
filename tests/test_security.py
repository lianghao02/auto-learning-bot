"""安全規則的單元測試。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.config_io import write_json_atomically
from utils.security import (
    DEFAULT_GAS_URL,
    is_cloud_sync_enabled,
    resolve_gas_url,
    validate_ai_base_url,
    validate_gas_url,
    verify_file_sha256,
)


class ValidateAiBaseUrlTests(unittest.TestCase):
    def test_accepts_official_provider_url(self):
        result = validate_ai_base_url("OpenAI", "https://api.openai.com/v1/")
        self.assertEqual(result, "https://api.openai.com/v1")

    def test_rejects_non_https_url(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_ai_base_url("自訂", "http://localhost:8080/v1")

    def test_rejects_wrong_official_host(self):
        with self.assertRaisesRegex(ValueError, "官方網域"):
            validate_ai_base_url("Gemini", "https://example.com/v1")

    def test_accepts_custom_https_url(self):
        result = validate_ai_base_url("自訂", "https://ai.example.com/v1/")
        self.assertEqual(result, "https://ai.example.com/v1")

    def test_rejects_credentials_in_url(self):
        with self.assertRaisesRegex(ValueError, "帳號或密碼"):
            validate_ai_base_url("自訂", "https://user:secret@ai.example.com/v1")

    def test_verifies_file_sha256(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "update.exe"
            path.write_bytes(b"verified update")
            self.assertTrue(
                verify_file_sha256(
                    path,
                    "59f19f34399b14e5f1628642e9ce341d660094ba76898e4db6b1875f525b6a6a",
                )
            )
            self.assertFalse(verify_file_sha256(path, "0" * 64))

    def test_writes_json_atomically_and_keeps_backup(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text('{"version": 1}', encoding="utf-8")
            write_json_atomically(path, {"version": 2})
            self.assertEqual(path.read_text(encoding="utf-8"), '{\n    "version": 2\n}')
            self.assertEqual(
                path.with_suffix(".json.bak").read_text(encoding="utf-8"),
                '{"version": 1}',
            )

    def test_daily_quota_tracker_and_dashboard_cards(self):
        from utils.security import DailyQuotaTracker, format_course_dashboard_card, format_batch_summary_card
        with TemporaryDirectory() as temp_dir:
            temp_quota_file = Path(temp_dir) / "daily_quota.json"
            tracker = DailyQuotaTracker(daily_limit=1500, storage_path=temp_quota_file)
            res = tracker.record_usage(2)
            self.assertEqual(res["used"], 2)
            self.assertEqual(res["remaining"], 1498)

            card = format_course_dashboard_card(
                course_name="數位轉型實戰",
                score_text="85.0 分及格",
                is_passed=True,
                solve_mode_desc="🤖 Gemini 批次秒答",
                feedback_status="✅ 已完成",
                session_completed=1,
                session_passed=1
            )
            self.assertIn("行政效能領航員 - 即時研習成效儀表板", card)
            self.assertIn("數位轉型實戰", card)
            self.assertIn("85.0 分及格", card)

            batch_card = format_batch_summary_card(
                session_courses=5,
                pass_count=5,
                bank_solved=20,
                ai_solved=30,
                ai_requests=3
            )
            self.assertIn("階段成效彙整", batch_card)

    def test_gas_url_validation_and_cloud_sync_opt_in(self):
        self.assertFalse(is_cloud_sync_enabled(None))
        self.assertFalse(is_cloud_sync_enabled({}))
        self.assertTrue(is_cloud_sync_enabled({"cloud_sync_enabled": True}))
        self.assertTrue(is_cloud_sync_enabled({"settings": {"cloud_sync_enabled": True}}))

        self.assertEqual(resolve_gas_url({}), DEFAULT_GAS_URL)
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_gas_url("http://script.google.com/macros/s/abc/exec")
        with self.assertRaisesRegex(ValueError, "帳號或密碼"):
            validate_gas_url("https://user:pass@script.google.com/macros/s/abc/exec")
        with self.assertRaisesRegex(ValueError, "官方網域"):
            validate_gas_url("https://evil.example.com/exec")

    def test_daily_quota_default_path_has_no_nested_data_dir(self):
        from utils.security import DailyQuotaTracker
        tracker = DailyQuotaTracker()
        default_path = tracker._get_file_path()
        self.assertEqual(default_path.name, "daily_quota.json")
        self.assertNotEqual(default_path.parent.parent.name, "data")

    def test_usage_tracker_defaults_to_disabled_when_unconfigured(self):
        import usage_tracker
        from unittest.mock import patch
        with TemporaryDirectory() as temp_dir:
            missing_cfg = Path(temp_dir) / "config.json"
            with patch.object(usage_tracker, "_config_path", return_value=missing_cfg), \
                 patch.object(usage_tracker.requests, "post") as mock_post:
                self.assertFalse(usage_tracker.is_cloud_sync_enabled())
                self.assertIsNone(usage_tracker.ping("V2.1.0"))
                mock_post.assert_not_called()

    def test_usage_tracker_never_overwrites_config_json(self):
        import usage_tracker
        from unittest.mock import patch

        with TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.json"
            original_raw = '{"accounts":[{"account":"u1","password":"p1"}],"settings":{"ai_api_key":"secret"}}'
            cfg_path.write_text(original_raw, encoding="utf-8")
            with patch.object(usage_tracker, "_config_path", return_value=cfg_path):
                dev_id = usage_tracker.get_device_id()
                self.assertTrue(len(dev_id) >= 16)
                # config.json 必須分毫不差保留原狀，device_id 獨立寫入 device_id.txt
                self.assertEqual(cfg_path.read_text(encoding="utf-8"), original_raw)
                self.assertEqual((Path(temp_dir) / "device_id.txt").read_text(encoding="utf-8").strip(), dev_id)

            # 即使 config.json 暫時損毀或正在寫入中，get_device_id 也絕不覆寫它
            broken_cfg = Path(temp_dir) / "sub" / "config.json"
            broken_cfg.parent.mkdir(parents=True, exist_ok=True)
            broken_cfg.write_text("{partial_json_being_written", encoding="utf-8")
            with patch.object(usage_tracker, "_config_path", return_value=broken_cfg):
                dev_id2 = usage_tracker.get_device_id()
                self.assertTrue(len(dev_id2) >= 16)
                self.assertEqual(broken_cfg.read_text(encoding="utf-8"), "{partial_json_being_written")

    def test_webdriver_missing_chrome_returns_none_without_hardcoded_120(self):
        from unittest.mock import patch
        from utils import webdriver_mgr

        with patch.object(webdriver_mgr.sys, "platform", "linux"):
            self.assertIsNone(webdriver_mgr.get_local_chrome_version())
        with TemporaryDirectory() as temp_dir, \
             patch.object(webdriver_mgr, "_resolve_target_folder", return_value=temp_dir), \
             patch.object(webdriver_mgr, "get_local_chrome_version", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "無法從系統登錄檔偵測 Chrome 版本"):
                webdriver_mgr.download_best_chromedriver()


if __name__ == "__main__":
    unittest.main()
