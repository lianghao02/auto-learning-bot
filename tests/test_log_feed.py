"""冒險日誌整理器：兩平臺格式統一、心跳訊息收斂與篩選。"""
import unittest

from utils.log_feed import LogFeed, matches_filter


class LogFeedTests(unittest.TestCase):
    def setUp(self):
        self.feed = LogFeed()

    def add_all(self, lines):
        return [self.feed.add(line) for line in lines]

    def test_progress_heartbeat_updates_live_card_and_only_logs_milestones(self):
        self.add_all([
            "12:24:22 [INFO] 處理: 媒體互動技巧",
            "  📊 研習進度：00:00:05 / 02:06:00 [--------------------] 0.1%",
            "  📍 進入單元：一、前言...",
            "  📊 研習進度：00:01:22 / 02:06:00 [--------------------] 1.1%",
            "  📍 進入單元：二、認識媒體與媒體重要性...",
            "  📊 研習進度：00:32:00 / 02:06:00 [#####---------------] 25.4%",
        ])
        kinds = [e.kind for e in self.feed.entries]
        self.assertEqual(kinds, ["header", "milestone", "milestone"])
        self.assertEqual(self.feed.live.course, "媒體互動技巧")
        self.assertEqual(self.feed.live.unit, "二、認識媒體與媒體重要性")
        self.assertAlmostEqual(self.feed.live.pct, 25.4)

    def test_both_platform_formats_become_same_entry_shape(self):
        egov = self.feed.add("12:24:04 [INFO] 📖 [1/47] 正在協助研習：114年資訊安全教育訓練(一般人員)").entry
        taipei = self.feed.add("處理: 個案談判技巧").entry
        self.assertEqual((egov.kind, egov.category), ("header", "course"))
        self.assertEqual((taipei.kind, taipei.category), ("header", "course"))
        self.assertIn("開始處理：114年資訊安全教育訓練", egov.text)
        self.assertEqual(taipei.text, "開始處理：個案談判技巧")
        self.assertEqual(self.feed.live.course, "個案談判技巧")

    def test_bracket_tags_dashboard_box_and_separators(self):
        updates = self.add_all([
            "  [題庫] 從 GAS 載入 10 題（course_id=3180）",
            "┌──────────────────────────┐",
            "│ 🏆 測驗成果：⚠️ 未達門檻 ｜ 問卷：✅ 已完成",
            "│ │",
            "=== 測驗 (course_id=3180) ===",
        ])
        bank, sep, card, empty_card, header = updates
        self.assertEqual((bank.entry.category, bank.entry.text), ("bank", "從 GAS 載入 10 題（course_id=3180）"))
        self.assertIsNone(sep)
        self.assertEqual(card.entry.kind, "card")
        self.assertEqual(card.entry.level, "WARNING")
        self.assertIsNone(empty_card.entry)
        self.assertEqual((header.entry.kind, header.entry.category, header.entry.text), ("header", "quiz", "測驗 (course_id=3180)"))

    def test_repeated_lines_merge_with_counter(self):
        updates = self.add_all(["      ⚠️ 點擊失敗，跳過"] * 4)
        self.assertEqual(len(self.feed.entries), 1)
        self.assertEqual(self.feed.entries[0].repeat, 4)
        self.assertTrue(all(u.merged for u in updates[1:]))
        self.assertEqual(self.feed.issue_count, 1)
        self.assertTrue(self.feed.entries[0].plain.endswith("×4"))

    def test_filters(self):
        self.add_all([
            "12:23:44 [INFO] 📝 作答進度：[1/10 題] 已填答 [題庫]",
            "12:23:52 [INFO] 🎉 測驗結果：及格 / 通過 【門檻：60.0 分】！",
            "12:21:56 [INFO] ✅ E政府登入成功",
            "12:22:33 [WARNING] ⚠️ 測驗待處理：老人福利服務｜未能進入教室介面",
        ])
        detail, quiz_ok, login_ok, warn = self.feed.entries
        self.assertEqual((detail.kind, detail.category), ("detail", "quiz"))
        self.assertTrue(matches_filter(detail, "quiz"))
        self.assertFalse(matches_filter(detail, "key"))
        self.assertFalse(matches_filter(detail, "study"))
        self.assertTrue(matches_filter(quiz_ok, "key"))
        self.assertEqual(login_ok.category, "login")
        self.assertTrue(matches_filter(login_ok, "system"))
        self.assertTrue(matches_filter(warn, "key"))

    def test_clear_resets_state(self):
        self.add_all(["處理: A", "  📊 研習進度：00:10:00 / 01:00:00 [###] 16.7%", "⚠️ 失敗"])
        self.feed.clear()
        self.assertEqual(len(self.feed.entries), 0)
        self.assertFalse(self.feed.live.active)
        self.assertEqual(self.feed.issue_count, 0)


class TaipeiScoreParsingTests(unittest.TestCase):
    def test_score_formats(self):
        from quiz_bank import _extract_score_num
        cases = {
            "分數 得80.00分(滿分為100.00分)": 80.0,
            "分數 得8.00分(滿分為10.00分)": 80.0,
            "成績 8.00/10.00": 80.0,
            "評分 7.00 滿分 10.00 (70%)": 70.0,
            "審閱頁推算 9/10 題正確": 90.0,
            "得分：80.0 分": 80.0,
            "": None,
            "分數 尚未評分": None,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                got = _extract_score_num(text)
                if expected is None:
                    self.assertIsNone(got)
                else:
                    self.assertAlmostEqual(got, expected)


class TaipeiQuizFlowTests(unittest.TestCase):
    """以假 driver 驗證成績判定流程，不連線平臺。"""

    def run_quiz(self, score_text, grade_counts):
        from unittest.mock import patch, Mock
        import quiz_bank
        questions = [{"name": "q1", "qtext": "題目一", "options": {"0": "對", "1": "錯"}}]
        submit = Mock(return_value='review-url')
        stats = {}
        with patch.object(quiz_bank, "gas_fetch_bank", return_value={"題目一": "0"}), \
             patch.object(quiz_bank, "lookup_bank", return_value="0"), \
             patch.object(quiz_bank, "_start_or_resume_quiz", return_value="attempt-url"), \
             patch.object(quiz_bank, "_read_questions", return_value=questions), \
             patch.object(quiz_bank, "_submission_counts", return_value={'total': 1, 'answered': 1, 'expected_total': 1}), \
             patch.object(quiz_bank, "_fill_answers", return_value=1), \
             patch.object(quiz_bank, "_submit_quiz", submit), \
             patch.object(quiz_bank, "_read_correct_from_review", return_value={}), \
             patch.object(quiz_bank, "_get_score_from_review", return_value=score_text), \
             patch.object(quiz_bank, "_get_score_from_course_record", return_value=''), \
             patch.object(quiz_bank, "_review_grade_counts", return_value=grade_counts), \
             patch.object(quiz_bank, "gas_save_questions"), \
             patch.object(quiz_bank, "save_ai_answers_to_sqlite"), \
             patch.object(quiz_bank, "gas_report_missing_questions"), \
             patch.object(quiz_bank.time, "sleep"):
            result = quiz_bank.do_quiz_with_bank(Mock(), Mock(), "1", "url", config={}, min_pass_score=70, stats=stats)
        return result, stats, submit.call_count

    def test_bank_only_full_score_does_not_crash(self):
        (score, is_100), stats, submits = self.run_quiz("分數 得100.00分(滿分為100.00分)", None)
        self.assertTrue(is_100)
        self.assertTrue(stats["passed"])
        self.assertEqual(submits, 1)

    def test_missing_score_falls_back_to_review_marks(self):
        (score, _), stats, submits = self.run_quiz("", (8, 10))
        self.assertTrue(stats["passed"])
        self.assertIn("8/10", score)
        self.assertEqual(submits, 1)

    def test_unreadable_score_stops_instead_of_blind_retries(self):
        (score, _), stats, submits = self.run_quiz("", None)
        self.assertFalse(stats["passed"])
        self.assertTrue(stats["score_unknown"])
        self.assertEqual(submits, 1)

    def test_real_fail_still_retries_three_times(self):
        _, stats, submits = self.run_quiz("分數 得50.00分(滿分為100.00分)", None)
        self.assertFalse(stats["passed"])
        self.assertFalse(stats["score_unknown"])
        self.assertEqual(submits, 3)


if __name__ == "__main__":
    unittest.main()
