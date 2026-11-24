"""交卷末段、成績證據與同步交易的邊界回歸；不連正式平台。"""

import logging
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import quiz_bank
from app import AdminEfficiencyPilot, _PlainTextLogFormatter, _can_resolve_exam_answer
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


class ExamAnswerPrevalidationTests(unittest.TestCase):
    def test_can_resolve_exam_answer_detects_mismatched_bank_entries(self):
        self.assertTrue(_can_resolve_exam_answer('公務人員保障法', ['訴願法', '公務人員保障法', '行政訴訟法', '刑法'], 4, 0))
        self.assertFalse(_can_resolve_exam_answer('舊版已刪除的選項文字', ['選項甲', '選項乙', '選項丙', '選項丁'], 4, 0))
        self.assertTrue(_can_resolve_exam_answer('正確', ['', ''], 2, 0))
        self.assertTrue(_can_resolve_exam_answer('A,C', ['甲', '乙', '丙', '丁'], 0, 4))
        self.assertFalse(_can_resolve_exam_answer('完全對不上的多選描述', ['甲', '乙', '丙', '丁'], 0, 4))
        self.assertFalse(_can_resolve_exam_answer('E', ['甲', '乙', '丙', '丁'], 0, 4))
        self.assertTrue(_can_resolve_exam_answer('以上皆是', ['甲', '乙', '丙'], 0, 3))

    def test_plain_text_log_formatter_strips_ansi_sequences(self):
        formatter = _PlainTextLogFormatter('%(levelname)s - %(message)s')
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='✅ 引擎就緒：\x1b[32mV2.2.0\x1b[0m｜\x1b[33m測試課程\x1b[0m',
            args=(),
            exc_info=None,
        )
        self.assertEqual(formatter.format(record), 'INFO - ✅ 引擎就緒：V2.2.0｜測試課程')

    def test_unresolvable_bank_answer_falls_back_to_ai_batch(self):
        """題庫命中但答案與當前考卷選項不符時，應改納入 AI 批次補答，不應靜默略過導致漏答擋交卷。"""
        pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        pilot.running = True
        pilot.config = {'ai_auto_solve': True, 'ai_provider': 'Gemini', 'ai_keys': {'Gemini': 'test-key'}}
        pilot._answer_map = {'dummy': {'answer': 'x'}}
        pilot.answers = []
        pilot._exam_fail_counts = {}
        pilot._exam_manual_review = {}
        pilot._completed_in_session = set()
        pilot._auto_hide_popups_if_needed = Mock()
        pilot._accept_alert = Mock()
        pilot._read_exam_result = Mock(return_value=True)
        pilot._wait_s_main_action_or_status = Mock(return_value=('button', Mock()))
        pilot._find_answer = Mock(side_effect=['正確選項一', '題庫裡對不上現在頁面的舊選項'])

        def _make_row():
            row = Mock()
            radios = [Mock(), Mock(), Mock(), Mock()]
            row.find_elements.side_effect = lambda by, sel: radios if 'radio' in sel else []
            return row

        rows = [_make_row(), _make_row()]
        driver = Mock()
        driver.current_window_handle = 'main'
        driver.window_handles = ['main', 'exam']
        driver.current_url = 'https://ecollege.elearn.hrd.gov.tw/learn/exam/exam_start.php'
        driver.find_elements.return_value = rows

        def _exec_script(script, *args):
            if 'arguments[0].click()' in script and 'checked' not in script:
                return None
            if '\u958b\u59cb' in script and 'querySelectorAll(\'input\')' in script:
                return '開始作答'
            if 'td.childNodes' in script:
                return '第一題題幹' if args and args[0] is rows[0] else '第二題題幹'
            if 'ol li, ul li' in script:
                return ['正確選項一', '選項二', '選項三', '選項四'] if args and args[0] is rows[0] else ['新選項甲', '新選項乙', '新選項丙', '新選項丁']
            if 'return arguments[0].checked;' in script:
                return True
            if 'input[type=radio]:checked' in script:
                return {'total': 2, 'answered': 2}
            if 'finish' in script or '繳交' in script:
                return True
            return None

        driver.execute_script.side_effect = _exec_script
        pilot.driver = driver

        captured_batch = []

        def _fake_ai_batch(title, questions, cfg):
            captured_batch.extend(questions)
            return {'success': True, 'parsed_answers': {q['name']: 'B' for q in questions}}

        with patch('app.time.sleep'), \
             patch('app.WebDriverWait') as mock_wait, \
             patch('quiz_bank.ai_batch_solve_quiz', side_effect=_fake_ai_batch):
            mock_wait.return_value.until.return_value = True
            passed = pilot._auto_exam_attempt({'course_id': 'c1', 'caption': '測試課程'})

        self.assertTrue(passed)
        # 第 1 題題庫可解析不送 AI；第 2 題題庫無法對應選項，已自動轉交 AI 批次
        self.assertEqual([q['index'] for q in captured_batch], [2])

    def test_find_answer_fuzzy_rejects_negation_flip_and_tf_to_mcq_mismatch(self):
        """模糊比對不得把肯定/否定句對調，也不得把 4 選 1 單選題配成純是非題。"""
        from app import _is_driver_disconnect_error, _normalize_q

        pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        pilot.answers = []
        q_pos = "下列何者是公務人員行政中立法所稱行政資源？"
        q_tf_only = "下列何者是公務人員行政中立法所稱行政資源"
        pilot._answer_map = {
            _normalize_q(q_pos): {"answer": "正確", "options": [], "question": q_pos},
        }
        pilot._answer_keys = list(pilot._answer_map.keys())

        # 否定句（多一個「不」）不得模糊配到肯定句
        self.assertIsNone(
            pilot._find_answer("下列何者「不」是公務人員行政中立法所稱行政資源？", num_options=4)
        )
        # 4 選 1 單選題不得模糊配到純是非題（精準不同字元、靠模糊命中時須擋下）
        self.assertIsNone(
            pilot._find_answer("下列何者是公務人員行政中立法所稱行政資源呢？", num_options=4)
        )
        # 2 選 1 是非題仍可正常模糊命中
        self.assertEqual(
            pilot._find_answer("下列何者是公務人員行政中立法所稱行政資源呢？", num_options=2),
            "正確",
        )
        # 驗證視窗關閉訊息能被辨識為 Driver 中斷
        self.assertTrue(_is_driver_disconnect_error("Message: no such window: target window already closed"))
        self.assertFalse(_is_driver_disconnect_error("ValueError: unrelated parse error"))

    def test_auto_healing_preserves_running_flag_and_handlers(self):
        pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        pilot.running = True
        pilot.config = {"login_type": "egov"}
        pilot.driver = Mock()
        pilot.ui_handler = Mock()
        pilot.file_handler = Mock()
        pilot._auto_healing_count = 0
        pilot._kill_managed_processes = Mock()
        pilot.init_engine = Mock(return_value=True)
        pilot.login = Mock(return_value=True)

        with patch("app.time.sleep"):
            healed = pilot._try_auto_healing("no such window")

        self.assertTrue(healed)
        self.assertTrue(pilot.running)
        self.assertIsNotNone(pilot.ui_handler)
        self.assertIsNotNone(pilot.file_handler)

    def test_read_exam_result_confirms_pass_via_s_main_without_saving_unscored_ai(self):
        pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        pilot.driver = Mock()
        pilot.driver.current_window_handle = "exam"
        pilot.driver.window_handles = ["main", "exam"]
        # 結果頁無分數文字
        pilot.driver.execute_script.side_effect = ["測驗已提交，感謝您的作答", ""]
        pilot._exam_manual_review = {}
        pilot._exam_fail_counts = {"c1": 1}
        pilot._check_exam_passed_via_s_main = Mock(return_value=True)
        pilot._save_answers_to_db = Mock(return_value=True)

        with patch("app.time.sleep"):
            passed = pilot._read_exam_result(
                {"course_id": "c1", "criteria_exam_score": 75},
                _ai_answered={"第一題": "選項甲"},
                main_window="main",
            )

        self.assertTrue(passed)
        self.assertFalse(pilot._last_exam_score_unknown)
        self.assertNotIn("c1", pilot._exam_manual_review)
        self.assertNotIn("c1", pilot._exam_fail_counts)
        # 僅確認通過但無 100 分明確證據，嚴禁將 AI 答案寫入題庫
        pilot._save_answers_to_db.assert_not_called()

    def test_harvest_correct_answers_uses_same_origin_fetch(self):
        pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        pilot.driver = Mock()
        pilot.http_session = Mock()
        pilot.driver.execute_script.side_effect = ["cid=1&att=2", "0", []]
        pilot.driver.execute_async_script.return_value = {"ok": True, "text": "1"}

        with patch("app.time.sleep"):
            pilot._harvest_correct_answers("https://ecollege.elearn.hrd.gov.tw/learn/exam/view_result.php?1+2+abc")

        pilot.driver.execute_async_script.assert_called_once()
        pilot.driver.refresh.assert_called_once()
        pilot.http_session.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
