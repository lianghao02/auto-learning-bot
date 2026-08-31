"""AI 批次作答、限速器與金鑰遮罩單元測試。"""

import unittest
from unittest.mock import MagicMock, patch
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
    def test_ai_batch_solve_missing_key(self, mock_post):
        empty_config = {'ai_provider': 'Gemini', 'ai_api_key': ''}
        res = ai_batch_solve_quiz('測試課程', self.sample_questions, empty_config)
        self.assertFalse(res['success'])
        self.assertIn('尚未設定 API Key', res['error'])
        mock_post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
