"""AI 服務暫時中斷（503／逾時）時的重試、備援模型、延後重考與日誌路由。"""
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

import quiz_bank

QUESTIONS = [{
    "index": 1, "name": "q1", "type": "單選", "is_multiple": False, "q_text": "題目",
    "options": [{"label": "A", "text": "甲", "val": "0"}, {"label": "B", "text": "乙", "val": "1"}],
}]
CONFIG = {"ai_provider": "Gemini", "ai_api_key": "test-key", "ai_model": "gemini-3.1-flash-lite"}


def _http_error(code):
    resp = requests.Response()
    resp.status_code = code
    return requests.exceptions.HTTPError(response=resp)


def _ok(text='{"answers": {"1": "B"}}'):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {"content": text}}]}
    return resp


class AIBatchRetryTests(unittest.TestCase):
    def solve(self, side_effect):
        post = Mock(side_effect=side_effect)
        with patch.object(quiz_bank.requests, "post", post), \
             patch.object(quiz_bank.time, "sleep"), \
             patch("utils.security.global_ai_rate_limiter.acquire", return_value=True):
            result = quiz_bank.ai_batch_solve_quiz("課程", QUESTIONS, dict(CONFIG))
        return result, post

    def test_503_then_fallback_model_succeeds(self):
        def effect(*args, **kwargs):
            if effect.calls < 2:
                effect.calls += 1
                bad = Mock()
                bad.raise_for_status.side_effect = _http_error(503)
                return bad
            return _ok()
        effect.calls = 0
        result, post = self.solve(effect)
        self.assertTrue(result["success"])
        self.assertEqual(result["parsed_answers"], {"q1": "1"})
        models = [c.kwargs["json"]["model"] for c in post.call_args_list]
        self.assertEqual(models, ["gemini-3.1-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash"])

    def test_timeout_everywhere_marks_transient(self):
        result, post = self.solve(requests.exceptions.ReadTimeout("slow"))
        self.assertFalse(result["success"])
        self.assertTrue(result["transient"])
        self.assertEqual(post.call_count, 3)

    def test_unauthorized_is_not_retried(self):
        bad = Mock()
        bad.raise_for_status.side_effect = _http_error(401)
        result, post = self.solve([bad])
        self.assertFalse(result["success"])
        self.assertFalse(result["transient"])
        self.assertEqual(post.call_count, 1)


class ExamDeferTests(unittest.TestCase):
    def pilot(self, outage):
        from app import AdminEfficiencyPilot
        stub = SimpleNamespace(_last_exam_ai_outage=outage, _exam_fail_counts={"c1": 1})
        stub.defer = lambda course: AdminEfficiencyPilot._defer_exam_after_ai_outage(stub, course)
        return stub

    def test_outage_failure_not_counted_and_deferred(self):
        stub = self.pilot(True)
        self.assertTrue(stub.defer({"course_id": "c1", "caption": "淨零"}))
        self.assertEqual(stub._exam_fail_counts["c1"], 0)
        self.assertIn("c1", stub._exam_retry_after)

    def test_normal_failure_still_counts(self):
        stub = self.pilot(False)
        self.assertFalse(stub.defer({"course_id": "c1"}))
        self.assertEqual(stub._exam_fail_counts["c1"], 1)

    def test_defer_grace_is_limited(self):
        from app import EXAM_AI_OUTAGE_MAX_DEFERS
        stub = self.pilot(True)
        results = []
        for _ in range(EXAM_AI_OUTAGE_MAX_DEFERS + 1):
            stub._exam_fail_counts["c1"] = 1
            results.append(stub.defer({"course_id": "c1"}))
        self.assertEqual(results, [True] * EXAM_AI_OUTAGE_MAX_DEFERS + [False])


class PrintRoutingTests(unittest.TestCase):
    def test_other_thread_print_goes_to_logging_when_stdout_owned_elsewhere(self):
        owned = SimpleNamespace(owner_thread=-1, write=Mock(), flush=Mock())
        with patch.object(sys, "stdout", owned), patch("logging.Logger.info") as info:
            quiz_bank._safe_print("  [AI批次] 正在呼叫")
        info.assert_called_once_with("[AI批次] 正在呼叫")
        owned.write.assert_not_called()

    def test_owner_thread_prints_normally(self):
        owned = SimpleNamespace(owner_thread=threading.get_ident(), write=Mock(), flush=Mock())
        with patch.object(sys, "stdout", owned), patch("logging.Logger.info") as info:
            quiz_bank._safe_print("臺北E大訊息")
        info.assert_not_called()
        self.assertTrue(owned.write.called)


if __name__ == "__main__":
    unittest.main()
