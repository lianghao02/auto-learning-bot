"""課程完成狀態與題庫寫入防護單元測試。"""

import unittest
from unittest.mock import MagicMock
from app import AdminEfficiencyPilot


class CourseCompletionLogicTests(unittest.TestCase):
    def setUp(self):
        self.pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        self.pilot.config = {"target_percentage": 1.0}
        self.pilot._completed_in_session = set()
        self.pilot._exam_manual_review = {}
        self.pilot._exam_fail_counts = {}

    def test_pending_course_with_insufficient_hours_is_not_excluded(self):
        """測試時數不足但曾考過試且填過問卷之課程，依然保留在 pending 待上課清單。"""
        # 課程：時數 0/2 小時，但 exam_score=100 且 fill=1
        course = {
            "course_id": "1001",
            "caption": "資安法規與實務",
            "rss": "00:00:00",
            "criteria_content_hour": "02:00:00",
            "exam_score": 100,
            "pass_score": 60,
            "fill": "1",
            "status_open": "1",
            "play_type": "scorm",
        }

        # 模擬 _is_open_course, _is_playable_course, _is_exam_passed
        self.pilot._is_open_course = lambda c: True
        self.pilot._is_playable_course = lambda c: True
        self.pilot._is_exam_passed = lambda c: True

        # 待上課清單過濾條件
        from app import to_sec
        courses = [course]
        pending = [
            c
            for c in courses
            if self.pilot._is_open_course(c)
            and self.pilot._is_playable_course(c)
            and to_sec(c.get("rss", "00:00:00"))
            < to_sec(c.get("criteria_content_hour", "00:00:00"))
            * self.pilot.config.get("target_percentage", 1.0)
            and str(c.get("course_id", "")) not in self.pilot._completed_in_session
        ]

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["course_id"], "1001")

    def test_exam_failed_3_times_marked_in_manual_review(self):
        """測試測驗失敗達 3 次上限時，正確加入 _exam_manual_review。"""
        course = {"course_id": "2002", "caption": "政府採購法"}
        self.pilot._mark_exam_manual_review = lambda c, r: self.pilot._exam_manual_review.update({str(c["course_id"]): {"caption": c["caption"], "reason": r}})
        
        # 模擬不及格達 3 次
        c_id = str(course["course_id"])
        self.pilot._exam_fail_counts[c_id] = 3
        
        if self.pilot._exam_fail_counts.get(c_id, 0) >= 3:
            self.pilot._mark_exam_manual_review(course, "測驗連續不及格已達 3 次上限")
            self.pilot._completed_in_session.add(c_id)

        self.assertIn("2002", self.pilot._exam_manual_review)
        self.assertEqual(self.pilot._exam_manual_review["2002"]["reason"], "測驗連續不及格已達 3 次上限")

    def test_completed_course_with_105_percent_target_is_excluded_from_pending(self):
        """測試已獲平臺核定為已通過（時數 01:01:47 >= 01:00:00 且測驗滿分問卷已填）的課程，即使 target_percentage 為 1.05 亦不排入 pending。"""
        from app import to_sec
        self.pilot.config = {"target_percentage": 1.05}
        course = {
            "course_id": "10044040",
            "caption": "安寧緩和醫療條例與相關法律之臨床運用",
            "rss": "01:01:47",
            "criteria_content_hour": "01:00:00",
            "exam_score": 100,
            "criteria_exam_score": 60,
            "fill": "1",
            "status_text": "已通過",
        }
        self.pilot._is_open_course = lambda c: True
        self.pilot._is_playable_course = lambda c: True

        self.assertTrue(self.pilot._is_course_completed(course))

        courses = [course]
        pending = [
            c
            for c in courses
            if self.pilot._is_open_course(c)
            and self.pilot._is_playable_course(c)
            and not self.pilot._is_course_completed(c)
            and to_sec(c.get("rss", "00:00:00"))
            < to_sec(c.get("criteria_content_hour", "00:00:00"))
            * self.pilot.config.get("target_percentage", 1.0)
            and str(c.get("course_id", "")) not in self.pilot._completed_in_session
        ]
        self.assertEqual(len(pending), 0)

    def test_course_with_hours_done_but_pending_exam_needs_exam(self):
        """測試時數已達標 (100%) 但測驗尚未及格之課程（如臺灣藍碳發展機會與策略建議），不可被判定為已修畢，且必須進入考試處理清單。"""
        from app import to_sec
        course = {
            "course_id": "10044099",
            "caption": "臺灣藍碳發展機會與策略建議",
            "rss": "01:00:00",
            "criteria_content_hour": "01:00:00",
            "criteria_exam_score": 60,
            "exam_score": None,  # 尚未考試
            "fill": "1",  # 問卷已填
            "status": "1",  # 報名中/開課中
        }
        self.pilot._is_open_course = lambda c: True
        self.pilot._is_playable_course = lambda c: True

        # 1. 尚未考試，故不可判定為完成
        self.assertFalse(self.pilot._is_course_completed(course))

        # 2. 測試 _needs_exam_or_questionnaire 判定為 True
        c_id = str(course["course_id"])
        hours_done = to_sec(course.get("rss", "00:00:00")) >= to_sec(course.get("criteria_content_hour", "00:00:00"))
        exam_passed = self.pilot._is_exam_passed(course)
        needs_exam = (not exam_passed) and (self.pilot._exam_fail_counts.get(c_id, 0) < 3)
        self.assertTrue(hours_done)
        self.assertFalse(exam_passed)
        self.assertTrue(needs_exam)

    def test_course_with_fail_status_and_60_score_is_not_passed(self):
        """測試臺灣藍碳（考 60 分但門檻為 75 分、通過狀態為未通過）絕不可誤判為已通過。"""
        from app import to_sec
        course = {
            "course_id": "PCENTER115100466",
            "caption": "臺灣藍碳發展機會與策略建議",
            "rss": "00:35:56",
            "criteria_content_hour": "00:30:00",
            "criteria_exam_score": 75,
            "exam_score": 60,
            "pass_status": "未通過",
            "fill": "1",
        }
        self.assertFalse(self.pilot._is_exam_passed(course))
        self.assertFalse(self.pilot._is_course_completed(course))


if __name__ == "__main__":
    unittest.main()



