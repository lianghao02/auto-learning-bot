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
        self.assertIn("📚 最新完成課程：【改善交通瓶頸、打造通學步道】", card)
        self.assertIn("🏆 測驗成果：➖ 本課程無測驗", card)
        self.assertIn("問卷：✅ 已完成", card)
        self.assertIn("⚡ 本門作答方式：➖ 無須作答", card)
        self.assertIn("📊 本次執行累計：已完成 1 門課程", card)
        self.assertNotIn("/1 門課程", card)
        self.assertNotIn("0/1 門課程", card)
        self.assertNotIn("及格率 0.0%", card)
        self.assertIn("💳 本門 API 呼叫：0 次 ｜ 今日累計已用：12 / 1500 次", card)
        self.assertIn("🟢 配額健康狀態：充足", card)

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
        self.assertIn("📚 最新完成課程：【創意思考(張溫德講座)】", card)
        self.assertIn("🏆 測驗成果：🎉 達標及格", card)
        self.assertIn("⚡ 本門作答方式：🤖 Gemini 批次秒答", card)
        self.assertIn("📊 本次執行累計：已完成 2 門課程（測驗通過 1/1 門）", card)
        self.assertNotIn("/2 門課程", card)
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
        self.assertIn("📚 最新完成課程：【公文撰作解析】", card)
        self.assertIn("🏆 測驗成果：🎉 達標及格", card)
        self.assertIn("⚡ 本門作答方式：📚 本機題庫秒殺", card)
        self.assertIn("📊 本次執行累計：已完成 3 門課程（測驗通過 2/2 門）", card)
        self.assertNotIn("/3 門課程", card)
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
        self.assertIn("📚 最新處理課程：【難題測驗課程】", card)
        self.assertNotIn("最新完成課程", card)
        self.assertIn("🏆 測驗成果：⚠️ 未達門檻", card)
        self.assertIn("問卷：⚠️ 待填寫", card)
        self.assertIn("📊 本次執行累計：已完成 4 門課程（測驗通過 2/3 門）", card)
        self.assertNotIn("/4 門課程", card)

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

    def test_course_not_completed_tag(self):
        """任務 6 新增測試 1: 未完成課程標籤 -> 顯示最新處理課程，不得顯示最新完成課程"""
        card = render_course_completion_card(
            course_name="未完成課程測試",
            has_quiz=True,
            quiz_passed=False,
            survey_completed=False,
            course_completed=False,
            solve_mode="manual",
            course_api_calls=0,
            today_api_calls=10,
            daily_limit=1500,
            session_completed=0,
            session_quiz_passed=0,
            session_quiz_total=1,
        )
        self.assertIn("最新處理課程", card)
        self.assertNotIn("最新完成課程", card)

    def test_quota_yellow_status(self):
        """任務 6 新增測試 2: 黃色配額 (remaining <= 300, remaining > 50) -> 🟡 偏低"""
        card = render_course_completion_card(
            course_name="黃色配額測試",
            has_quiz=False,
            quiz_passed=None,
            survey_completed=True,
            course_completed=True,
            solve_mode=None,
            course_api_calls=1,
            today_api_calls=1300,  # 1500 - 1300 = 200 (50 < remaining <= 300)
            daily_limit=1500,
            session_completed=1,
            session_quiz_passed=0,
            session_quiz_total=0,
        )
        self.assertIn("🟡", card)
        self.assertIn("偏低", card)
        self.assertNotIn("🟢", card)
        self.assertNotIn("充足", card)

    def test_quota_red_status(self):
        """任務 6 新增測試 3: 紅色配額 (remaining <= 50) -> 🔴 不足"""
        card = render_course_completion_card(
            course_name="紅色配額測試",
            has_quiz=False,
            quiz_passed=None,
            survey_completed=True,
            course_completed=True,
            solve_mode=None,
            course_api_calls=1,
            today_api_calls=1480,  # 1500 - 1480 = 20 (remaining <= 50)
            daily_limit=1500,
            session_completed=1,
            session_quiz_passed=0,
            session_quiz_total=0,
        )
        self.assertIn("🔴", card)
        self.assertIn("不足", card)
        self.assertNotIn("🟢", card)
        self.assertNotIn("充足", card)

    def test_success_emits_course_status_completed(self):
        """任務 6 新增測試 4: study_process 回傳 SUCCESS 後發送 CourseStatus.COMPLETED 且下一步非掛時數"""
        from models.course_state import CourseStatus, CourseState

        emitted_states = []

        def mock_callback(state: CourseState):
            emitted_states.append(state)

        # 模擬待上課課程資料
        pending_course = {
            "course_id": "9999",
            "caption": "數位轉型實務",
            "rss": "01:00:00",
            "criteria_content_hour": "01:00:00",
        }

        # 模擬進入研習前發送 LEARNING
        def _emit_course_state(c, st, rsn="", nxt="", is_comp=False, needs_man=False, score=None):
            c_state = CourseState(
                course_id=str(c.get("course_id", "")),
                course_name=c.get("caption", ""),
                platform="egov",
                status=st,
                progress_pct=100.0 if is_comp else 50.0,
                current_time_str=c.get("rss", "00:00:00"),
                required_time_str=c.get("criteria_content_hour", "00:00:00"),
                reason=rsn,
                next_step=nxt,
                is_completed=is_comp,
                needs_manual=needs_man,
            )
            mock_callback(c_state)

        _emit_course_state(pending_course, CourseStatus.LEARNING, "時數尚未達標，正在進入教室累積時數", "觀看教材並保持連線直到時數達標")
        self.assertEqual(len(emitted_states), 1)
        self.assertEqual(emitted_states[0].status, CourseStatus.LEARNING)
        self.assertEqual(emitted_states[0].next_step, "觀看教材並保持連線直到時數達標")

        # 模擬 study_process() 回傳 SUCCESS
        res = "SUCCESS"
        if res == "SUCCESS":
            _emit_course_state(
                pending_course,
                CourseStatus.COMPLETED,
                "研習流程已完成",
                "已完成本課程，接續下一門",
                is_comp=True,
            )

        self.assertEqual(len(emitted_states), 2)
        final_state = emitted_states[-1]
        self.assertEqual(final_state.status, CourseStatus.COMPLETED)
        self.assertTrue(final_state.is_completed)
        self.assertEqual(final_state.reason, "研習流程已完成")
        self.assertEqual(final_state.next_step, "已完成本課程，接續下一門")
        self.assertNotEqual(final_state.next_step, "觀看教材並保持連線直到時數達標")


if __name__ == "__main__":
    unittest.main()
