"""課程結案儀表板 Presenter 單元測試。"""

import unittest
from utils.course_dashboard import render_course_completion_card


class CourseDashboardPresenterTests(unittest.TestCase):
    def test_no_quiz_course(self):
        """情境 1: 無測驗課程 (如交通瓶頸 5621) -> 顯示無測驗、無須作答、本門 API=0"""
        card = render_course_completion_card(
            course_name="改善交通瓶頸、打造通學步道",
            has_quiz=False,
            quiz_passed=None,
            survey_completed=True,
            course_completed=True,
            solve_mode=None,
            course_api_calls=0,
            today_api_calls=12,
            daily_limit=1500,
            session_completed=1,
            session_quiz_passed=0,
            session_quiz_total=0,
        )
        self.assertIn("🏆 測驗成果：➖ 本課程無測驗", card)
        self.assertIn("問卷：✅ 已完成", card)
        self.assertIn("⚡ 本門作答方式：➖ 無須作答", card)
        self.assertIn("📊 本次執行累計：已完成 1/1 門課程", card)
        self.assertNotIn("0/1 門課程", card)
        self.assertNotIn("及格率 0.0%", card)
        self.assertIn("💳 本門 API 呼叫：0 次 ｜ 今日累計已用：12 / 1500 次", card)

    def test_quiz_passed_with_ai(self):
        """情境 2: 有測驗且 AI 解答通過 -> 達標及格、Gemini、本門 API=1"""
        card = render_course_completion_card(
            course_name="創意思考(張溫德講座)",
            has_quiz=True,
            quiz_passed=True,
            survey_completed=True,
            course_completed=True,
            solve_mode="ai",
            course_api_calls=1,
            today_api_calls=13,
            daily_limit=1500,
            session_completed=2,
            session_quiz_passed=1,
            session_quiz_total=1,
        )
        self.assertIn("🏆 測驗成果：🎉 達標及格", card)
        self.assertIn("⚡ 本門作答方式：🤖 Gemini 批次秒答", card)
        self.assertIn("📊 本次執行累計：已完成 2/2 門課程（測驗通過 1/1 門）", card)
        self.assertIn("💳 本門 API 呼叫：1 次 ｜ 今日累計已用：13 / 1500 次", card)

    def test_quiz_passed_with_bank(self):
        """情境 3: 有測驗且題庫命中通過 -> 達標及格、題庫秒殺、本門 API=0"""
        card = render_course_completion_card(
            course_name="公文撰作解析",
            has_quiz=True,
            quiz_passed=True,
            survey_completed=True,
            course_completed=True,
            solve_mode="quiz_bank",
            course_api_calls=0,
            today_api_calls=13,
            daily_limit=1500,
            session_completed=3,
            session_quiz_passed=2,
            session_quiz_total=2,
        )
        self.assertIn("🏆 測驗成果：🎉 達標及格", card)
        self.assertIn("⚡ 本門作答方式：📚 本機題庫秒殺", card)
        self.assertIn("💳 本門 API 呼叫：0 次", card)

    def test_quiz_failed(self):
        """情境 4: 有測驗但未及格 -> ⚠️ 未達門檻"""
        card = render_course_completion_card(
            course_name="難題測驗課程",
            has_quiz=True,
            quiz_passed=False,
            survey_completed=False,
            course_completed=False,
            solve_mode="ai",
            course_api_calls=1,
            today_api_calls=14,
            daily_limit=1500,
            session_completed=4,
            session_quiz_passed=2,
            session_quiz_total=3,
        )
        self.assertIn("🏆 測驗成果：⚠️ 未達門檻", card)
        self.assertIn("問卷：⚠️ 待填寫", card)
        self.assertIn("📊 本次執行累計：已完成 4/4 門課程（測驗通過 2/3 門）", card)

    def test_quiz_skipped(self):
        """情境 5: 使用者選擇跳過測驗模式 -> ⏩ 跳過測驗模式"""
        card = render_course_completion_card(
            course_name="跳過測驗課",
            has_quiz=True,
            quiz_passed=False,
            survey_completed=True,
            course_completed=True,
            solve_mode="skipped",
            course_api_calls=0,
            today_api_calls=14,
            daily_limit=1500,
            session_completed=5,
            session_quiz_passed=2,
            session_quiz_total=4,
        )
        self.assertIn("⚡ 本門作答方式：⏩ 跳過測驗模式", card)
        self.assertIn("💳 本門 API 呼叫：0 次", card)


if __name__ == "__main__":
    unittest.main()
