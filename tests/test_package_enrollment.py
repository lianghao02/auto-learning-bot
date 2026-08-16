"""組裝課程報名流程的單元測試。"""

import unittest
from pathlib import Path

from app import AdminEfficiencyPilot


class _FakeDriver:
    """只模擬本測試所需的瀏覽器互動，不會連線至平台。"""

    def __init__(self, subcourse_state="in_progress"):
        self.urls = []
        self.subcourse_state = subcourse_state

    def get(self, url):
        self.urls.append(url)

    def execute_script(self, script, *args):
        if "var cards =" in script:
            # 儀表板雖掃到另一門已完成組裝課程，API 來源仍必須聯集處理。
            return [{"id": "dashboard-done", "title": "已完成組裝課程", "is100": True}]
        if "var nextBtns" in script:
            return {"clicked": False, "text": ""}
        if "var tabs" in script:
            return True
        if "var mainArea" in script:
            return [{"href": "https://elearn.hrd.gov.tw/info/sub-course", "text": "子課程"}]
        if "var statusBox" in script:
            return {"action": self.subcourse_state, "text": "上課去"}
        return None


class PackageEnrollmentTests(unittest.TestCase):
    @staticmethod
    def _make_pilot(subcourse_state="in_progress"):
        pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        pilot.running = True
        pilot.driver = _FakeDriver(subcourse_state)
        pilot._expanded_packages = set()
        pilot.safe_sleep = lambda seconds: None
        pilot._accept_alert_if_present = lambda: ""
        return pilot

    def test_api_package_is_processed_when_dashboard_has_other_packages(self):
        pilot = self._make_pilot()

        changed = pilot.auto_enroll_package_subcourses(
            [
                {
                    "course_id": "api-package",
                    "caption": "API 組裝課程",
                    "course_type": "組裝課程",
                }
            ]
        )

        self.assertTrue(changed)
        self.assertIn("api-package", pilot._expanded_packages)
        self.assertIn("https://elearn.hrd.gov.tw/info/api-package", pilot.driver.urls)
        self.assertIn("https://elearn.hrd.gov.tw/info/sub-course", pilot.driver.urls)

    def test_unverified_subcourse_keeps_parent_for_retry(self):
        pilot = self._make_pilot("none")

        changed = pilot.auto_enroll_package_subcourses(
            [{"course_id": "api-package", "caption": "API 組裝課程", "course_type": "組裝課程"}]
        )

        self.assertFalse(changed)
        self.assertNotIn("api-package", pilot._expanded_packages)

    def test_dashboard_extractor_excludes_expanded_subcourse_rows(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("link.closest('table, tbody, tr')", source)
        self.assertIn("cards[i].querySelector('table, tbody, tr')", source)
        self.assertIn("controls = cards[i].querySelectorAll", source)

    def test_package_preflight_runs_only_once_per_session(self):
        pilot = self._make_pilot()
        courses = [{"course_id": "api-package", "caption": "API 組裝課程", "course_type": "組裝課程"}]

        self.assertTrue(pilot.auto_enroll_package_subcourses(courses))
        first_url_count = len(pilot.driver.urls)
        self.assertFalse(pilot.auto_enroll_package_subcourses(courses))
        self.assertEqual(len(pilot.driver.urls), first_url_count)
        self.assertTrue(pilot._package_preflight_completed)

    def test_ai_lookup_returns_without_key(self):
        pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        pilot.config = {"ai_provider": "Gemini", "ai_keys": {}, "ai_api_key": ""}

        self.assertIsNone(pilot._ai_find_answer("測試題目", ["選項 A", "選項 B"]))


if __name__ == "__main__":
    unittest.main()
