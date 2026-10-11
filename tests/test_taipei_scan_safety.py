"""臺北E大課程清單掃描的誤判防護測試。"""

import io
import sys
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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


class TaipeiScormPriorityTests(unittest.TestCase):
    def test_scorm_priority_over_resource_and_pdf(self):
        """當同頁同時存在 scorm 與 resource/pdf/補充教材 時，必須優先選擇 scorm 且排除 resource。"""
        from taipei_eda_course import get_scorm_player_url
        from selenium.webdriver.common.by import By

        mock_driver = MagicMock()
        mock_wait = MagicMock()
        mock_driver.current_url = 'https://elearning.taipei/course/view.php?id=5621'
        mock_driver.window_handles = ['win1']

        # 模擬頁面上的元素
        scorm_link = MagicMock()
        scorm_link.get_attribute.side_effect = lambda attr: {
            'href': 'https://elearning.taipei/elearn/mod/scorm/view.php?id=19173',
            'title': '改善交通瓶頸、打造通學步道'
        }.get(attr, '')
        scorm_link.text = '改善交通瓶頸、打造通學步道'

        resource_btn = MagicMock()
        resource_btn.get_attribute.side_effect = lambda attr: {
            'href': 'https://elearning.taipei/elearn/mod/resource/view.php?id=19169',
            'title': '【補充教材1】得獎工程案例分享.pdf'
        }.get(attr, '')
        resource_btn.text = '【補充教材1】'

        def fake_find_elements(by, selector):
            if by == By.CSS_SELECTOR:
                if 'mod/scorm/view.php' in selector:
                    # 返回 scorm 連結
                    return [scorm_link]
                elif 'a[href*="mod/resource/view.php"]' in selector:
                    return [resource_btn]
                elif 'form' in selector:
                    return []
                elif selector == 'a' or 'button' in selector or 'btn' in selector:
                    return [resource_btn, scorm_link]
            return []

        mock_driver.find_elements.side_effect = fake_find_elements

        # 模擬 driver.get(scorm_url) 後進入 scorm 播放器
        def fake_get(url):
            if 'mod/scorm/view.php?id=19173' in url:
                mock_driver.current_url = 'https://elearning.taipei/mod/scorm/player.php?id=19173'

        mock_driver.get.side_effect = fake_get

        with patch("taipei_eda_course.time.sleep"), patch("taipei_eda_course.dismiss_alerts", return_value=[]):
            player_url = get_scorm_player_url(mock_driver, mock_wait, 'https://elearning.taipei/course/view.php?id=5621')

        # 必須進入 SCORM 播放器，而不是 resource
        self.assertIsNotNone(player_url)
        self.assertIn('mod/scorm', player_url)
        self.assertNotIn('mod/resource', player_url)

    def test_ignore_course_presentation_and_handout_submit_buttons(self):
        """當課程目錄頁存在「課程簡報」或「課程講義」等 submit 按鈕時，不可誤判為 SCORM 播放器按鈕。"""
        from taipei_eda_course import get_scorm_player_url
        from selenium.webdriver.common.by import By

        mock_driver = MagicMock()
        mock_wait = MagicMock()
        mock_driver.current_url = 'https://elearning.taipei/course/view.php?id=2734'
        mock_driver.window_handles = ['win1']

        scorm_link = MagicMock()
        scorm_link.get_attribute.side_effect = lambda attr: {
            'href': 'https://elearning.taipei/elearn/mod/scorm/view.php?id=7667',
            'title': 'CRPD之工作與就業'
        }.get(attr, '')
        scorm_link.text = 'CRPD之工作與就業'

        # 模擬容易引發誤觸的簡報按鈕
        presentation_submit_btn = MagicMock()
        presentation_submit_btn.get_attribute.side_effect = lambda attr: {
            'type': 'submit',
            'value': '課程簡報-CRPD之工作與就業',
            'href': '',
        }.get(attr, '')
        presentation_submit_btn.text = '課程簡報-CRPD之工作與就業'

        # 模擬容易引發誤觸的講義按鈕
        handout_submit_btn = MagicMock()
        handout_submit_btn.get_attribute.side_effect = lambda attr: {
            'type': 'submit',
            'value': '【課程講義】',
            'href': '',
        }.get(attr, '')
        handout_submit_btn.text = '【課程講義】'

        def fake_find_elements(by, selector):
            if by == By.CSS_SELECTOR:
                if 'mod/scorm/view.php' in selector:
                    return [scorm_link]
                elif 'form' in selector:
                    return []
                elif 'input[type=submit]' in selector or 'button' in selector:
                    return [presentation_submit_btn, handout_submit_btn]
                elif selector == 'a':
                    return [scorm_link]
            return []

        mock_driver.find_elements.side_effect = fake_find_elements

        def fake_get(url):
            if 'mod/scorm/view.php?id=7667' in url:
                mock_driver.current_url = 'https://elearning.taipei/mod/scorm/player.php?id=7667'

        mock_driver.get.side_effect = fake_get

        with patch("taipei_eda_course.time.sleep"), patch("taipei_eda_course.dismiss_alerts", return_value=[]):
            player_url = get_scorm_player_url(mock_driver, mock_wait, 'https://elearning.taipei/course/view.php?id=2734')

        # 簡報與講義 submit 按鈕不可被點擊
        self.assertFalse(presentation_submit_btn.click.called)
        self.assertFalse(handout_submit_btn.click.called)
        self.assertIsNotNone(player_url)
        self.assertIn('mod/scorm/player.php', player_url)


class TaipeiRunQueueLoopTests(unittest.TestCase):
    def test_run_taipei_eda_work_queue_quota_tracker_integration(self):
        """測試 run_taipei_eda 進入待處理課程處理時，global_quota_tracker 正常可用且不拋出 NameError"""
        from taipei_eda_course import run_taipei_eda

        mock_driver = MagicMock()
        mock_driver.window_handles = ['win1']

        sample_course = {
            'name': '測試資安意識課程',
            'href': 'https://elearning.taipei/course/view.php?id=9999',
            'study': '01:00:00',
            'cert_hrs': '1.0',
            'quiz': '已及格',
            'quest': '已完成',
        }

        # 模擬登入成功、取得 1 門待處理課程、模組解析完成
        with patch('taipei_eda_course.webdriver.Chrome', return_value=mock_driver), \
             patch('taipei_eda_course.do_login', return_value=True), \
             patch('taipei_eda_course.get_course_list', return_value=[sample_course]), \
             patch('taipei_eda_course.build_taipei_work_queue', return_value=[sample_course]), \
             patch('taipei_eda_course.get_course_modules', return_value={'course_id': 9999, 'req_minutes': 30.0, 'req_score': 60.0}), \
             patch('taipei_eda_course.is_study_incomplete', return_value=False), \
             patch('taipei_eda_course.is_quiz_passed', return_value=True), \
             patch('taipei_eda_course.is_questionnaire_pending', return_value=False), \
             patch('taipei_eda_course.time.sleep'):

            # 呼叫 run_taipei_eda，若 global_quota_tracker 未定義會拋出 NameError
            success = run_taipei_eda(config_override={'account': 'test_user', 'password': 'pwd'})
            self.assertTrue(success)

