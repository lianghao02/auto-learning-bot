"""雙平臺答題政策及各平臺交卷邊界的隔離回歸。"""

import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import quiz_bank
from app import AdminEfficiencyPilot
from utils.quiz_policy import answer_values, can_submit, course_completed, grade_passed, needs_ai_review


class SharedQuizPolicyTests(unittest.TestCase):
    def test_bank_first_and_failed_attempt_requires_review(self):
        self.assertFalse(needs_ai_review('0'))
        self.assertTrue(needs_ai_review(None))
        self.assertTrue(needs_ai_review('0', 1))

    def test_missing_unread_or_unchecked_questions_block_submission(self):
        self.assertTrue(can_submit(20, 20, expected_total=20))
        self.assertFalse(can_submit(13, 13, expected_total=20))
        self.assertFalse(can_submit(20, 13))
        self.assertFalse(can_submit(0, 0))

    def test_unknown_grade_and_explicit_failure_are_distinct(self):
        self.assertIsNone(grade_passed(None, 80))
        self.assertFalse(grade_passed(50, 80))
        self.assertFalse(grade_passed(None, 80, '未通過'))
        self.assertTrue(grade_passed(80, 80))

    def test_course_requires_confirmed_quiz_and_survey(self):
        self.assertFalse(course_completed(True, None, True))
        self.assertFalse(course_completed(True, False, True))
        self.assertFalse(course_completed(True, True, False))
        self.assertTrue(course_completed(True, True, True))

    def test_answer_text_survives_option_shuffle(self):
        self.assertEqual(answer_values('甲', {'0': '乙', '1': '甲'}), ['1'])
        self.assertEqual(answer_values(['甲', '乙'], {'0': '乙', '1': '甲'}, multiple=True), ['1', '0'])
        self.assertEqual(answer_values(['0', 'missing'], {'0': '甲'}, multiple=True), [])
        self.assertEqual(answer_values(['0', '1'], {'0': '甲', '1': '乙'}), [])


class TaipeiPolicyFlowTests(unittest.TestCase):
    def run_flow(self, *, scores=('得50分', '得100分'), ai=None, expected=1, fill=1, record=''):
        q = {'name': 'q1', 'qtext': '題目', 'options': {'0': '甲', '1': '乙'}}
        self.calls = {}
        values = {
            'gas_fetch_bank': {'題目': '0'}, 'lookup_bank': '0',
            '_start_or_resume_quiz': 'attempt', '_read_questions': [q],
            '_submission_counts': {'total': 1, 'answered': 1, 'expected_total': expected},
            '_fill_answers': fill, '_submit_quiz': 'review', '_read_correct_from_review': {},
            '_review_grade_counts': None, '_get_score_from_course_record': record,
            'gas_save_questions': True, 'gas_report_missing_questions': None,
            'save_ai_answers_to_sqlite': None,
            'ai_batch_solve_quiz': ai if ai is not None else {'success': True, 'parsed_answers': {'q1': '1'}},
        }
        stats = {}
        with ExitStack() as stack:
            for name, value in values.items():
                self.calls[name] = stack.enter_context(patch.object(quiz_bank, name, return_value=value))
            stack.enter_context(patch.object(quiz_bank, '_get_score_from_review', side_effect=scores))
            stack.enter_context(patch.object(quiz_bank.time, 'sleep'))
            result = quiz_bank.do_quiz_with_bank(Mock(), Mock(), 806, 'https://example.invalid/elearn/mod/quiz/view.php?id=1',
                config={'ai_provider': 'Gemini', 'ai_api_key': 'test-key', 'ai_auto_solve': True},
                min_pass_score=80, stats=stats)
        return result, stats

    def test_bank_failure_triggers_ai_on_next_attempt(self):
        _, stats = self.run_flow()
        self.assertTrue(stats['passed'])
        self.assertEqual(self.calls['_submit_quiz'].call_count, 2)
        self.assertEqual(self.calls['ai_batch_solve_quiz'].call_count, 1)
        self.assertEqual(self.calls['gas_save_questions'].call_count, 1)
        self.assertEqual(self.calls['_fill_answers'].call_args.args[1], {'q1': '1'})

    def test_failed_ai_review_does_not_resubmit_stale_bank_answer(self):
        _, stats = self.run_flow(ai={'success': False, 'transient': True, 'error': '503'})
        self.assertTrue(stats['blocked'])
        self.assertEqual(self.calls['_submit_quiz'].call_count, 1)
        self.calls['gas_save_questions'].assert_not_called()

    def test_partial_ai_response_blocks_submission(self):
        _, stats = self.run_flow(ai={'success': True, 'parsed_answers': {}})
        self.assertTrue(stats['blocked'])
        self.assertEqual(self.calls['_submit_quiz'].call_count, 1)

    def test_unread_questions_are_not_sent_to_ai_or_submitted(self):
        _, stats = self.run_flow(expected=20)
        self.assertTrue(stats['blocked'])
        self.calls['_submit_quiz'].assert_not_called()
        self.calls['ai_batch_solve_quiz'].assert_not_called()

    def test_unchecked_answer_blocks_submission(self):
        _, stats = self.run_flow(fill=0)
        self.assertTrue(stats['blocked'])
        self.calls['_submit_quiz'].assert_not_called()

    def test_unknown_grade_stops_without_ai_or_sync(self):
        _, stats = self.run_flow(scores=('',))
        self.assertTrue(stats['score_unknown'])
        self.assertEqual(self.calls['_submit_quiz'].call_count, 1)
        self.calls['ai_batch_solve_quiz'].assert_not_called()
        self.calls['gas_save_questions'].assert_not_called()

    def test_course_record_grade_is_used(self):
        _, stats = self.run_flow(scores=('',), record='課程紀錄得分：80 分')
        self.assertTrue(stats['passed'])
        self.assertEqual(self.calls['_submit_quiz'].call_count, 1)

    def test_three_confirmed_failures_stop(self):
        _, stats = self.run_flow(scores=('得50分',) * 3)
        self.assertFalse(stats['passed'])
        self.assertEqual(self.calls['_submit_quiz'].call_count, 3)
        self.assertEqual(self.calls['ai_batch_solve_quiz'].call_count, 2)


class EgovSubmissionPolicyTests(unittest.TestCase):
    def pilot(self):
        p = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        p.driver = Mock()
        p._exam_manual_review = {}
        p._exam_fail_counts = {}
        return p

    def test_unchecked_egov_row_blocks_submission(self):
        p = self.pilot()
        p.driver.execute_script.return_value = {'total': 20, 'answered': 13}
        self.assertFalse(p._verify_exam_ready({'course_id': '1'}, [Mock()] * 20))
        self.assertIn('1', p._exam_manual_review)

    def test_complete_egov_rows_allow_submission(self):
        p = self.pilot()
        p.driver.execute_script.return_value = {'total': 20, 'answered': 20}
        self.assertTrue(p._verify_exam_ready({'course_id': '1'}, [Mock()] * 20))

    def test_unknown_egov_grade_is_manual_review_without_failure_increment(self):
        p = self.pilot()
        p.driver.execute_script.return_value = ''
        with patch('app.time.sleep'):
            self.assertFalse(p._read_exam_result({'course_id': '1'}))
        self.assertIn('1', p._exam_manual_review)
        self.assertEqual(p._exam_fail_counts, {})


class SubmissionAndSyncSafetyTests(unittest.TestCase):
    def test_verified_multiple_answers_are_stored_as_text_and_survive_shuffle(self):
        import json
        import sqlite3
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from contextlib import closing
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / 'questions.db'
            with closing(sqlite3.connect(target)) as connection:
                connection.execute('CREATE TABLE questions (question TEXT UNIQUE, option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT, answer TEXT)')
                connection.commit()
            data = [{'index': 1, 'q_text': '測試題目', 'options': [
                {'label': 'A', 'text': '甲'}, {'label': 'B', 'text': '乙'}, {'label': 'C', 'text': '丙'}]}]
            with patch('utils.app_paths.user_data_path', return_value=target):
                quiz_bank.save_ai_answers_to_sqlite(data, {'1': 'A,C'})
            with closing(sqlite3.connect(target)) as connection:
                stored = connection.execute('SELECT answer FROM questions').fetchone()[0]
            self.assertEqual(json.loads(stored), ['甲', '丙'])
            raw = AdminEfficiencyPilot._clean_answer(stored)
            self.assertEqual(answer_values(raw, {'A': '丙', 'B': '甲', 'C': '乙'}, multiple=True), ['B', 'A'])

    def test_unknown_grade_card_is_not_no_quiz(self):
        from utils.course_dashboard import render_course_completion_card
        card = render_course_completion_card(course_name='測試', has_quiz=True, quiz_passed=None,
            survey_completed=True, course_completed=False, solve_mode='quiz_bank',
            course_api_calls=0, today_api_calls=0)
        self.assertIn('成績待確認', card)
        self.assertNotIn('本課程無測驗', card)
        self.assertIn('最新處理課程', card)

    def test_taipei_incomplete_page_does_not_even_click_finish(self):
        driver = Mock()
        with patch.object(quiz_bank, '_submission_counts', return_value={'total': 20, 'answered': 13, 'expected_total': 20}):
            self.assertIsNone(quiz_bank._submit_quiz(driver, Mock()))
        driver.execute_script.assert_not_called()

    def test_summary_unanswered_warning_is_not_confirmed(self):
        driver = Mock()
        driver.find_element.return_value.text = 'Questions without a response: 7'
        with patch.object(quiz_bank, '_submission_counts', return_value={'total': 20, 'answered': 20, 'expected_total': 20}), \
             patch.object(quiz_bank, '_click_js') as click, patch.object(quiz_bank.time, 'sleep'), \
             patch.object(quiz_bank, '_dismiss_alerts'):
            self.assertIsNone(quiz_bank._submit_quiz(driver, Mock()))
        click.assert_called_once()

    def test_sync_conflict_is_not_reported_as_success(self):
        response = Mock()
        response.json.return_value = {'status': 'error', 'error': '409'}
        with patch.object(quiz_bank.requests, 'post', return_value=response):
            self.assertIs(quiz_bank.gas_save_questions(1, [{'q_text': '題目', 'val': '0'}]), False)

    def test_split_grade_row_is_read(self):
        driver = Mock()
        driver.find_element.return_value.text = '成績\n50.00 / 100.00'
        self.assertEqual(quiz_bank._extract_score_num(quiz_bank._get_score_from_review(driver)), 50)


class TaipeiCompletionIntegrationTests(unittest.TestCase):
    def test_failed_quiz_is_not_counted_as_completed(self):
        self.assert_pending_case()

    def test_existing_survey_with_unknown_status_is_not_completed(self):
        self.assert_pending_case(score='100', quest='--', fb_url='survey-url')

    def test_missing_course_id_does_not_turn_required_quiz_into_no_quiz(self):
        self.assert_pending_case(course_id=None)

    def assert_pending_case(self, score='50', quest='已完成', course_id=806, fb_url=None):
        import taipei_eda_course as taipei
        course = {'name': '測試課程', 'href': 'https://example.invalid/course/view.php?id=806',
                  'study': '02:06:29', 'cert_hrs': '2', 'score': score, 'quest': quest}
        driver = Mock()
        driver.window_handles = ['main']
        card = Mock(return_value='摘要')
        state = Mock()
        def quiz(*args, **kwargs):
            kwargs['stats'].update(passed=float(score) >= 80, score_unknown=False)
            return f'得{score}分', score == '100'
        with ExitStack() as stack:
            for name, value in {
                'load_config': {}, '_acquire_taipei_run_lock': 'test-lock',
                '_release_taipei_run_lock': None, 'do_login': True,
                'get_course_list': [course], 'build_taipei_work_queue': [course],
                'get_course_modules': {'course_id': course_id, 'req_minutes': 120, 'req_score': 80, 'quiz_url': 'quiz-url', 'fb_url': fb_url},
                'is_study_incomplete': False,
            }.items():
                stack.enter_context(patch.object(taipei, name, return_value=value))
            stack.enter_context(patch.object(taipei.webdriver, 'Chrome', return_value=driver))
            stack.enter_context(patch('app.download_best_chromedriver', return_value='test-driver.exe'))
            stack.enter_context(patch.object(taipei, 'do_quiz_with_bank', side_effect=quiz))
            stack.enter_context(patch.object(taipei.time, 'sleep'))
            stack.enter_context(patch('utils.course_dashboard.render_course_completion_card', card))
            self.assertFalse(taipei.run_taipei_eda(config_override={'account': 'test_user', 'password': 'test_password'}, course_state_callback=state))
        self.assertIs(card.call_args.kwargs['course_completed'], False)
        self.assertEqual(card.call_args.kwargs['session_completed'], 0)
        self.assertIs(state.call_args.args[0].is_completed, False)


if __name__ == '__main__':
    unittest.main()
