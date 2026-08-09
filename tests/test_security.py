"""安全規則的單元測試。"""

import unittest

from utils.security import validate_ai_base_url


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


if __name__ == "__main__":
    unittest.main()
