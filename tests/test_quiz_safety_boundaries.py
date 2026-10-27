"""交卷末段、成績證據與同步交易的邊界回歸；不連正式平台。"""

import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import quiz_bank
from app import AdminEfficiencyPilot
from utils.quiz_policy import grade_evidence, has_unanswered_warning


class GradeEvidenceTests(unittest.TestCase):
    def test_instructions_are_not_scores_or_pass_results(self):
        for text in ('及格標準：80 分', '測驗分數達80分以上', '分數：80分以上才算通過', '通過測驗才能取得時數'):
            with self.subTest(text=text):
                self.assertEqual(grade_evidence(text), (None, ''))

    def test_actual_fields_and_split_rows(self):
        for text, score in [('分數\n50', 50), ('得分：8/10', 80), ('成績 得8分(滿分為10分)', 80), ('Grade\n75.00 / 100.00', 75)]:
            with self.subTest(text=text):
                self.assertEqual(grade_evidence(text), (score, ''))

    def test_explicit_status_only(self):
        self.assertEqual(grade_evidence('測驗結果：未通過'), (None, '未通過'))
        self.assertEqual(grade_evidence('通過狀態\n已通過'), (None, '已通過'))

    def test_zero_denominator_is_not_full_score(self):
        self.assertIsNone(quiz_bank._extract_score_num('0/0'))

    def test_unanswered_instructions_and_zero_warning_are_not_blocked(self):
        self.assertFalse(has_unanswered_warning('請留意未回答的題目，交卷前確認。'))
        self.assertFalse(has_unanswered_warning('Questions without a response: 0'))
        self.assertTrue(has_unanswered_warning('Questions without a response: 7'))
        self.assertTrue(has_unanswered_warning('尚未回答'))


class LateSubmitWarningTests(unittest.TestCase):
    def test_warning_created_only_by_final_modal_is_blocked(self):
        driver = Mock()
        driver.current_url = 'https://example.invalid/summary.php'
        finish, confirm, modal_save = Mock(), Mock(), Mock()
        driver.execute_script.side_effect = [finish, confirm, None]
        driver.find_element.side_effect = [Mock(text='答案已儲存'), Mock(text='Questions without a response: 7')]
        waiter = Mock()
        waiter.until.return_value = modal_save
        with patch.object(quiz_bank, '_submission_counts', return_value={'total': 20, 'answered': 20, 'expected_total': 20}), \
             patch.object(quiz_bank, '_click_js'), patch.object(quiz_bank, '_dismiss_alerts'), \
             patch.object(quiz_bank.time, 'sleep'), patch.object(quiz_bank, 'WebDriverWait', return_value=waiter):
            self.assertIsNone(quiz_bank._submit_quiz(driver, Mock()))
        self.assertEqual(driver.execute_script.call_count, 3)
        self.assertIs(driver.execute_script.call_args.args[1], confirm)


class EgovBoundaryTests(unittest.TestCase):
    def pilot(self, body=''):
        pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        pilot.driver = Mock()
        pilot.driver.execute_script.side_effect = [body, '']
        pilot._exam_manual_review = {}
        pilot._exam_fail_counts = {}
        return pilot

    def test_old_checked_answers_cannot_fill_partial_interactive_response(self):
        pilot = self.pilot()
        rows = [Mock(), Mock()]
        self.assertFalse(pilot._apply_interactive_exam_answers({'course_id': '1'}, rows, {1: ['A']}))
        pilot.driver.execute_script.assert_not_called()
        self.assertIn('1', pilot._exam_manual_review)

    def test_pass_instructions_are_unknown_not_success(self):
        pilot = self.pilot('及格標準：80分\n通過測驗才能取得時數')
        with patch('app.time.sleep'):
            self.assertFalse(pilot._read_exam_result({'course_id': '1', 'criteria_exam_score': 80}))
        self.assertEqual(pilot._exam_fail_counts, {})
        self.assertIn('1', pilot._exam_manual_review)

    def test_ratio_score_uses_percentage(self):
        pilot = self.pilot('得分：8/10')
        with patch('app.time.sleep'):
            self.assertTrue(pilot._read_exam_result({'course_id': '1', 'criteria_exam_score': 80}))

    def test_full_score_with_storage_failure_does_not_announce_sync_success(self):
        pilot = self.pilot('得分：100 分')
        pilot._save_answers_to_db = Mock(return_value=False)
        with patch('app.time.sleep'), patch('app.logger') as logger:
            self.assertTrue(pilot._read_exam_result({'course_id': '1'}, {'測試題': '甲'}))
        self.assertFalse(any('正式同步至題庫' in str(call) for call in logger.info.call_args_list))


class StorageTransactionTests(unittest.TestCase):
    def test_partial_write_failure_rolls_back_database_and_memory(self):
        pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        pilot._answer_map = {}
        pilot._answer_keys = []
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / 'questions.db'
            with patch('app.ensure_seeded_database', return_value=target):
                self.assertFalse(pilot._save_answers_to_db({'第一題': '甲', '第二題': object()}))
            with closing(sqlite3.connect(target)) as connection:
                self.assertEqual(connection.execute('SELECT count(*) FROM questions').fetchone()[0], 0)
            self.assertEqual(pilot._answer_map, {})
            self.assertEqual(pilot._answer_keys, [])

    def test_committed_answers_update_memory_and_report_true(self):
        pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / 'questions.db'
            with patch('app.ensure_seeded_database', return_value=target):
                self.assertTrue(pilot._save_answers_to_db({'測試題': '甲'}))
            with closing(sqlite3.connect(target)) as connection:
                self.assertEqual(connection.execute('SELECT answer FROM questions').fetchone()[0], '甲')
            self.assertEqual(pilot._answer_map['測試題']['answer'], '甲')


if __name__ == '__main__':
    unittest.main()
