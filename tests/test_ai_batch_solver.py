"""AI 批次作答、限速器與金鑰遮罩單元測試。"""

import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3

from utils.security import RateLimiter, mask_api_key
from quiz_bank import ai_batch_solve_quiz, save_ai_answers_to_sqlite


class RateLimiterTests(unittest.TestCase):
    def test_rate_limiter_allows_up_to_max(self):
        limiter = RateLimiter(max_requests=3, window_seconds=10.0)
        self.assertTrue(limiter.acquire(timeout=0.1))
        self.assertTrue(limiter.acquire(timeout=0.1))
        self.assertTrue(limiter.acquire(timeout=0.1))
        self.assertFalse(limiter.acquire(timeout=0.1))

    def test_mask_api_key(self):
        self.assertEqual(mask_api_key(''), '')
        self.assertEqual(mask_api_key(None), '')
        self.assertEqual(mask_api_key('12345'), '***')
        self.assertEqual(mask_api_key('AIzaSy1234567890ABCD'), 'AIzaSy***ABCD')


class AiBatchSolverTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = TemporaryDirectory()
        self.temp_quota_path = Path(self._temp_dir.name) / "daily_quota.json"
        from utils.security import global_quota_tracker
        self._orig_storage = global_quota_tracker._storage_path
        global_quota_tracker._storage_path = self.temp_quota_path

        self.sample_questions = [
            {
                'index': 1,
                'name': 'q1',
                'type': '單選',
                'is_multiple': False,
                'q_text': '資通安全通報辦法中，資通安全事件分為幾級？',
                'options': [
                    {'label': 'A', 'text': '2 級', 'val': '0'},
                    {'label': 'B', 'text': '3 級', 'val': '1'},
                    {'label': 'C', 'text': '4 級', 'val': '2'},
                    {'label': 'D', 'text': '5 級', 'val': '3'},
                ],
            },
            {
                'index': 2,
                'name': 'q2',
                'type': '是非',
                'is_multiple': False,
                'q_text': '公務機關辦理採購應遵循政府採購法。',
                'options': [
                    {'label': 'A', 'text': '是', 'val': '0'},
                    {'label': 'B', 'text': '否', 'val': '1'},
                ],
            },
        ]
        self.config = {
            'ai_provider': 'Gemini',
            'ai_base_url': 'https://generativelanguage.googleapis.com/v1beta/openai',
            'ai_model': 'gemini-3.1-flash-lite',
            'ai_api_key': 'AIzaSyTestMockKey12345678',
        }

    def tearDown(self):
        from utils.security import global_quota_tracker
        global_quota_tracker._storage_path = self._orig_storage
        self._temp_dir.cleanup()


    @patch('requests.post')
    def test_ai_batch_solve_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'choices': [
                {
                    'message': {
                        'content': '{"answers": {"1": "C", "2": "A"}}'
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        res = ai_batch_solve_quiz('資訊安全概論', self.sample_questions, self.config)
        self.assertTrue(res['success'])
        self.assertEqual(res['answers'], {'1': 'C', '2': 'A'})
        self.assertEqual(res['parsed_answers'], {'q1': '2', 'q2': '0'})

    @patch('requests.post')
    def test_ai_batch_solve_partial_answers(self, mock_post):
        """測試當 AI 僅回傳部分題目（例如 10 題中只回傳 1、3、6）時，缺題不會導致拋錯或錯位"""
        expanded_questions = [
            {'index': 1, 'name': 'q1', 'type': '單選', 'is_multiple': False, 'q_text': 'Q1', 'options': [{'label': 'A', 'text': 'opt1', 'val': '0'}, {'label': 'B', 'text': 'opt2', 'val': '1'}]},
            {'index': 2, 'name': 'q2', 'type': '是非', 'is_multiple': False, 'q_text': 'Q2', 'options': [{'label': 'A', 'text': '是', 'val': '0'}, {'label': 'B', 'text': '否', 'val': '1'}]},
            {'index': 3, 'name': 'q3', 'type': '單選', 'is_multiple': False, 'q_text': 'Q3', 'options': [{'label': 'A', 'text': 'optA', 'val': '0'}, {'label': 'B', 'text': 'optB', 'val': '1'}]},
            {'index': 4, 'name': 'q4', 'type': '單選', 'is_multiple': False, 'q_text': 'Q4', 'options': [{'label': 'A', 'text': 'optA', 'val': '0'}, {'label': 'B', 'text': 'optB', 'val': '1'}]},
            {'index': 5, 'name': 'q5', 'type': '單選', 'is_multiple': False, 'q_text': 'Q5', 'options': [{'label': 'A', 'text': 'optA', 'val': '0'}, {'label': 'B', 'text': 'optB', 'val': '1'}]},
            {'index': 6, 'name': 'q6', 'type': '單選', 'is_multiple': False, 'q_text': 'Q6', 'options': [{'label': 'A', 'text': 'optA', 'val': '0'}, {'label': 'B', 'text': 'optB', 'val': '1'}]},
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # AI 只回答了 1, 3, 6 題
        mock_resp.json.return_value = {
            'choices': [
                {
                    'message': {
                        'content': '{"answers": {"1": "B", "3": "A", "6": "B"}}'
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        res = ai_batch_solve_quiz('測試課程', expanded_questions, self.config)
        self.assertTrue(res['success'])
        self.assertEqual(res['answers'], {'1': 'B', '3': 'A', '6': 'B'})
        # 驗證 parsed_answers 只包含對應有回答的題目，缺漏的題目 (q2, q4, q5) 不應存在
        self.assertEqual(res['parsed_answers'], {'q1': '1', 'q3': '0', 'q6': '1'})
        self.assertNotIn('q2', res['parsed_answers'])
        self.assertNotIn('q4', res['parsed_answers'])
        self.assertNotIn('q5', res['parsed_answers'])

    @patch('requests.post')
    def test_ai_batch_solve_missing_key(self, mock_post):
        empty_config = {'ai_provider': 'Gemini', 'ai_api_key': ''}
        res = ai_batch_solve_quiz('測試課程', self.sample_questions, empty_config)
        self.assertFalse(res['success'])
        self.assertIn('尚未設定 API Key', res['error'])
        mock_post.assert_not_called()

    def test_score_extraction_and_is_100(self):
        from quiz_bank import _extract_score_num, _is_100
        self.assertEqual(_extract_score_num("得分：100.0 分"), 100.0)
        self.assertTrue(_is_100("得 100 分"))
        self.assertTrue(_is_100("得分：100 分"))
        self.assertEqual(_extract_score_num("得分：80.0 分"), 80.0)
        self.assertFalse(_is_100("得 80.0 分"))
        self.assertEqual(_extract_score_num("8/10"), 80.0)
        self.assertTrue(_is_100("10/10"))
        self.assertFalse(_is_100("6/10"))


if __name__ == '__main__':
    unittest.main()
