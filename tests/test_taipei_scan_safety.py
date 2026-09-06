"""臺北E大課程清單掃描的誤判防護測試。"""

import unittest
from unittest.mock import MagicMock, patch

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


class TaipeiNonScormReaderTests(unittest.TestCase):
    def test_do_scorm_course_already_satisfied(self):
        """測試當課程時數已達標時，do_scorm_course 直接回傳 True 無需進入播放器"""
        from taipei_eda_course import do_scorm_course

        mock_driver = MagicMock()
        mock_wait = MagicMock()

        course = {
            'name': '改善交通瓶頸【補充教材1】',
            'href': 'https://elearning.taipei/course/view.php?id=5621',
            'study': '0時10分00秒',
            'cert_hrs': '1.0',
        }
        modules = {'req_minutes': 5.0}  # 需要 5 分鐘，已有 10 分鐘
        res = do_scorm_course(mock_driver, mock_wait, course, modules=modules)
        self.assertTrue(res)

    def test_do_scorm_course_timed_reading_fallback_without_chapters(self):
        """測試當課程無 SCORM 章節樹但已開啓閱讀時，能依時數累積模式順利完成而不跳過"""
        from taipei_eda_course import do_scorm_course

        mock_driver = MagicMock()
        mock_driver.current_url = 'https://elearning.taipei/mod/resource/view.php?id=12345'
        mock_driver.window_handles = ['win1']
        mock_wait = MagicMock()

        course = {
            'name': '改善交通瓶頸【補充教材1】',
            'href': 'https://elearning.taipei/course/view.php?id=5621',
            'study': '0時0分0秒',
            'cert_hrs': '0.0',
        }
        # cert_hrs = 0, no req_minutes -> target_sec = 0 -> chapters check -> empty chapters -> return True
        with patch("taipei_eda_course.get_scorm_player_url", return_value="https://elearning.taipei/mod/resource/view.php?id=12345"):
            with patch("taipei_eda_course.get_chapters", return_value=[]):
                with patch("taipei_eda_course.time.sleep"):
                    res = do_scorm_course(mock_driver, mock_wait, course, modules={})
        self.assertTrue(res)
