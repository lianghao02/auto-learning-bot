"""複選簡答與平台入帳時數回歸，不呼叫正式平台。"""

import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import quiz_bank
import taipei_eda_course as taipei


class NumericTextTests(unittest.TestCase):
    def setUp(self):
        self.question = {'options': {'1': '甲', '2': '乙', '3': '丙', '4': '丁'},
                         'numeric_text': True, 'is_multiple': True}

    def test_contiguous_codes_and_option_text(self):
        self.assertEqual(quiz_bank._question_values(self.question, '124'), ['1', '2', '4'])
        self.assertEqual(quiz_bank._question_values(self.question, ['丁', '甲']), ['4', '1'])

    def test_unknown_or_duplicate_code_is_rejected(self):
        for value in ('125', '112', '0', '不確定'):
            self.assertEqual(quiz_bank._question_values(self.question, value), [])

    def test_radio_codes_are_not_split_into_digits(self):
        self.assertEqual(quiz_bank._question_values(dict(self.question, numeric_text=False, is_multiple=False), '124'), [])


class OfficialStudyIntegrationTests(unittest.TestCase):
    def run_case(self, records):
        course = {'name': '測試課程', 'href': 'https://example.invalid/course/view.php?id=3597',
                  'study': '00:00:00', 'cert_hrs': '4', 'score': '-', 'quest': '已完成', 'done': '未完成'}
        module = {'course_id': 3597, 'req_minutes': 120, 'quiz_url': None, 'fb_url': None}
        driver = Mock()
        driver.window_handles = ['main']
        card, state = Mock(return_value='摘要'), Mock()
        with ExitStack() as stack:
            for name, value in {
                'load_config': {}, '_acquire_taipei_run_lock': 'test-lock', '_release_taipei_run_lock': None,
                'do_login': True, 'get_course_list': [course], 'build_taipei_work_queue': [course],
            }.items():
                stack.enter_context(patch.object(taipei, name, return_value=value))
            stack.enter_context(patch.object(taipei, 'get_course_modules', side_effect=[dict(module, study='00:00:00')] + [dict(module, **({'study': r} if r else {})) for r in records]))
            scorm = stack.enter_context(patch.object(taipei, 'do_scorm_course', return_value=True))
            stack.enter_context(patch.object(taipei.webdriver, 'Chrome', return_value=driver))
            stack.enter_context(patch('app.download_best_chromedriver', return_value='test-driver.exe'))
            stack.enter_context(patch.object(taipei.time, 'sleep'))
            stack.enter_context(patch('utils.course_dashboard.render_course_completion_card', card))
            taipei.run_taipei_eda(config_override={'account': 'test_user', 'password': 'test_password'}, course_state_callback=state)
        return scorm, card, state

    def test_local_timer_does_not_override_108_recorded_minutes(self):
        scorm, card, state = self.run_case(['01:48:41', '01:49:00'])
        self.assertEqual(scorm.call_count, 2)
        card.assert_not_called()
        self.assertFalse(state.call_args.args[0].is_completed)

    def test_top_up_can_complete_only_after_official_record_reaches_threshold(self):
        scorm, card, _ = self.run_case(['01:48:41', '02:00:01'])
        self.assertEqual(scorm.call_count, 2)
        self.assertTrue(card.call_args.kwargs['course_completed'])

    def test_missing_official_record_is_not_completion(self):
        scorm, card, state = self.run_case([None])
        self.assertEqual(scorm.call_count, 1)
        card.assert_not_called()
        self.assertFalse(state.call_args.args[0].is_completed)


if __name__ == '__main__':
    unittest.main()
