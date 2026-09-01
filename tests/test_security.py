"""安全規則的單元測試。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.config_io import write_json_atomically
from utils.security import validate_ai_base_url, verify_file_sha256


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


if __name__ == "__main__":
    unittest.main()
