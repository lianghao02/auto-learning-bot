import threading
import time
import unittest
from unittest.mock import patch

from utils import helpers


class WindowVisibilityGuardTests(unittest.TestCase):
    def tearDown(self):
        deadline = time.monotonic() + 1.0
        while helpers._WINDOW_HIDE_GUARDS and time.monotonic() < deadline:
            time.sleep(0.01)

    def test_hide_guard_retries_and_cleans_up(self):
        driver = object()
        called = threading.Event()
        calls = []

        def record_visibility(target, visible):
            calls.append((target, visible))
            if len(calls) >= 2:
                called.set()
            return 1

        with patch.object(helpers, "set_driver_window_visibility", side_effect=record_visibility):
            helpers.maintain_driver_windows_hidden(driver, duration=0.08, interval=0.02)
            self.assertTrue(called.wait(0.5))
            deadline = time.monotonic() + 0.5
            while helpers._WINDOW_HIDE_GUARDS and time.monotonic() < deadline:
                time.sleep(0.01)

        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(all(target is driver and visible is False for target, visible in calls))
        self.assertFalse(helpers._WINDOW_HIDE_GUARDS)

    def test_repeated_request_reuses_same_guard(self):
        driver = object()
        with patch.object(helpers, "set_driver_window_visibility", return_value=1):
            helpers.maintain_driver_windows_hidden(driver, duration=0.08, interval=0.02)
            first_state = helpers._WINDOW_HIDE_GUARDS[id(driver)]
            first_deadline = first_state["deadline"]
            helpers.maintain_driver_windows_hidden(driver, duration=0.12, interval=0.02)
            second_state = helpers._WINDOW_HIDE_GUARDS[id(driver)]

        self.assertIs(first_state, second_state)
        self.assertGreater(second_state["deadline"], first_deadline)

    def test_show_request_cancels_active_hide_guard(self):
        driver = object()
        with patch.object(helpers, "set_driver_window_visibility", return_value=1):
            helpers.maintain_driver_windows_hidden(driver, duration=0.2, interval=0.02)
            self.assertIn(id(driver), helpers._WINDOW_HIDE_GUARDS)

        helpers.set_driver_window_visibility(driver, True)
        self.assertNotIn(id(driver), helpers._WINDOW_HIDE_GUARDS)


if __name__ == "__main__":
    unittest.main()
