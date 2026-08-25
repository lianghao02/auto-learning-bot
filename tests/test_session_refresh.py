import unittest
from unittest.mock import MagicMock, patch
import time
from app import AdminEfficiencyPilot

class ProactiveSessionRefreshTests(unittest.TestCase):
    def setUp(self):
        self.pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        self.pilot.config = {"session_refresh_hours": 5.0}
        self.pilot.driver = MagicMock()
        self.pilot.http_session = MagicMock()
        self.pilot._last_session_refresh_time = time.time() - 20000  # 模擬 5.5 小時前
        self.pilot._course_relogin_counts = {"c1": 1}

    def test_proactive_session_refresh_clears_cookies_and_relLogins(self):
        with patch.object(self.pilot, "login", return_value=True) as mock_login, \
             patch.object(self.pilot, "sync_session", return_value=True) as mock_sync:
            result = self.pilot._proactive_session_refresh()
            self.assertTrue(result)
            self.pilot.driver.delete_all_cookies.assert_called_once()
            self.pilot.http_session.cookies.clear.assert_called_once()
            mock_login.assert_called_once()
            mock_sync.assert_called_once()
            self.assertEqual(len(self.pilot._course_relogin_counts), 0)
            self.assertGreater(self.pilot._last_session_refresh_time, time.time() - 5)

if __name__ == "__main__":
    unittest.main()
