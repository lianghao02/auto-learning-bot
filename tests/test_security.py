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


if __name__ == "__main__":
    unittest.main()
