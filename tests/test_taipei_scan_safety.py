"""臺北E大課程清單掃描的誤判防護測試。"""

import unittest
from unittest.mock import patch

from taipei_eda_course import get_course_list


class _EmptyCourseListDriver:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)

    def find_elements(self, *_args):
        return []


class TaipeiCourseListSafetyTests(unittest.TestCase):
    def test_empty_first_page_is_scan_failure_not_empty_course_list(self):
        driver = _EmptyCourseListDriver()
        with patch("taipei_eda_course.time.sleep"):
            courses = get_course_list(driver, wait=None)
        self.assertIsNone(courses)
        self.assertTrue(driver.urls)
