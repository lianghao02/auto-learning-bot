"""課程狀態模型單元測試。"""
import unittest
from datetime import datetime
from models.course_state import CourseState, CourseStatus


class CourseStateModelTests(unittest.TestCase):
    def test_course_state_initialization_defaults(self):
        state = CourseState(
            course_id="101",
            course_name="公務倫理",
            platform="taipei_eda",
        )
        self.assertEqual(state.status, CourseStatus.WAITING)
        self.assertEqual(state.progress_pct, 0.0)
        self.assertFalse(state.is_completed)
        self.assertFalse(state.needs_manual)
        self.assertEqual(state.status.badge_text, "○ 等待中")

    def test_course_state_status_summary_with_reason_and_next_step(self):
        state = CourseState(
            course_id="102",
            course_name="資訊安全法規",
            platform="egov",
            status=CourseStatus.QUIZ,
            reason="時數已達標，進入總結測驗",
            next_step="查詢 SQLite 題庫或 Gemini 智慧作答",
        )
        summary = state.status_summary
        self.assertIn("【📝 測驗中】", summary)
        self.assertIn("原因: 時數已達標，進入總結測驗", summary)
        self.assertIn("➜ 下一步: 查詢 SQLite 題庫或 Gemini 智慧作答", summary)

    def test_course_state_manual_review_status(self):
        state = CourseState(
            course_id="103",
            course_name="採購法實務",
            platform="egov",
            status=CourseStatus.MANUAL_REVIEW,
            reason="測驗連續不及格已達 3 次上限",
            next_step="請至網站手動查看考卷解析",
            needs_manual=True,
        )
        self.assertTrue(state.needs_manual)
        self.assertEqual(state.status.badge_text, "⚠️ 需人工確認")
        self.assertEqual(state.status.color_hex, "#C96D63")

    def test_formatted_study_progress(self):
        state = CourseState(
            course_id="104",
            course_name="性別平等",
            platform="taipei_eda",
            current_time_str="00:30:00",
            required_time_str="01:00:00",
            progress_pct=50.0,
        )
        self.assertEqual(state.formatted_study_progress, "00:30:00 / 01:00:00 (50.0%)")


if __name__ == "__main__":
    unittest.main()
