"""e 等教室多步入口與跨重考用量的回歸測試。"""

import json
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

import app
from app import AdminEfficiencyPilot


class CourseEntryFlowTests(unittest.TestCase):
    def setUp(self):
        self.pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        self.pilot.running = True
        self.pilot.driver = Mock(current_url="https://elearn.hrd.gov.tw/info/123")
        self.pilot.driver.window_handles = ["main"]
        self.pilot.safe_sleep = Mock(return_value=True)

    def test_confirmation_then_entry(self):
        self.pilot.driver.execute_script.side_effect = [
            {"kind": "confirm", "label": "確定"},
            {"kind": "entry", "label": "上課去"},
        ]
        self.assertEqual(self.pilot._click_course_entry(), "上課去")
        self.assertEqual(self.pilot.driver.execute_script.call_count, 2)

    def test_enrollment_confirmation_then_entry(self):
        self.pilot.driver.execute_script.side_effect = [
            {"kind": "enroll", "label": "我要報名"},
            {"kind": "confirm", "label": "確認"},
            {"kind": "entry", "label": "開始上課"},
        ]
        self.assertEqual(self.pilot._click_course_entry(allow_enrollment=True), "開始上課")

    def test_no_entry_after_confirmation_is_not_reported_as_entered(self):
        self.pilot.driver.execute_script.side_effect = [
            {"kind": "confirm", "label": "確定"}, None,
        ]
        self.assertIsNone(self.pilot._click_course_entry())

    def test_repeated_confirmation_is_bounded(self):
        self.pilot.driver.execute_script.return_value = {"kind": "confirm", "label": "確定"}
        self.assertIsNone(self.pilot._click_course_entry())
        self.assertEqual(self.pilot.driver.execute_script.call_count, 4)

    def test_stop_after_confirmation_prevents_next_click(self):
        self.pilot.driver.execute_script.return_value = {"kind": "confirm", "label": "確定"}
        self.pilot.safe_sleep.return_value = False
        self.assertIsNone(self.pilot._click_course_entry())
        self.assertEqual(self.pilot.driver.execute_script.call_count, 1)

    def test_confirmation_opening_new_window_stops_clicking_old_page(self):
        def click(*_args):
            self.pilot.driver.window_handles = ["main", "classroom"]
            return {"kind": "confirm", "label": "確定"}
        self.pilot.driver.execute_script.side_effect = click
        self.assertEqual(self.pilot._click_course_entry(), "確定")
        self.assertEqual(self.pilot.driver.execute_script.call_count, 1)


@unittest.skipUnless(shutil.which("node"), "JavaScript 執行驗證需要既有 Node.js")
class CourseEntryScriptTests(unittest.TestCase):
    def execute(self, modal=None, entry=None, exam=False):
        # 執行正式入口腳本；模擬 DOM 只提供可見性、停用與按鈕動作。
        harness = r'''
const clicks = [];
function button(spec, name) {
  return Object.assign({innerText: '', disabled: false,
    getClientRects() { return this.hidden ? [] : [{}]; },
    getAttribute(key) { return key === 'aria-disabled' ? String(!!this.ariaDisabled) : ''; },
    click() { clicks.push(name); }
  }, spec);
}
const modal = MODAL;
const entry = ENTRY;
const modals = modal ? [button(modal, 'modal')] : [];
const entries = entry ? [button(entry, 'entry')] : [];
const document = {querySelectorAll(selector) {
  return selector.includes('.modal') ? modals : [...modals, ...entries];
}};
const window = {getComputedStyle(b) {
  return {display: b.hidden ? 'none' : 'block', visibility: b.visibility || 'visible'};
}};
const result = new Function('document', 'window', SCRIPT)(document, window);
console.log(JSON.stringify({result, clicks}));
'''
        script = getattr(app, "_COURSE_ENTRY_SCRIPT", "")
        self.assertTrue(script, "必須執行正式入口腳本")
        harness = harness.replace("MODAL", json.dumps(modal)).replace("ENTRY", json.dumps(entry))
        harness = harness.replace("SCRIPT", json.dumps("const includeExam = " + json.dumps(exam) + ";\nconst includeEnrollment = false;\n" + script))
        result = subprocess.run([shutil.which("node"), "-e", harness], capture_output=True,
                                text=True, encoding="utf-8", check=True)
        return json.loads(result.stdout)

    def test_hidden_confirmation_does_not_block_entry(self):
        result = self.execute({"innerText": "確定", "hidden": True}, {"innerText": "上課去"})
        self.assertEqual(result["clicks"], ["entry"])

    def test_visible_confirmation_precedes_entry(self):
        result = self.execute({"innerText": "確定"}, {"innerText": "上課去"})
        self.assertEqual(result["result"]["kind"], "confirm")

    def test_disabled_entries_are_not_clicked(self):
        for state in ({"disabled": True}, {"ariaDisabled": True}, {"visibility": "hidden"}):
            with self.subTest(state=state):
                result = self.execute(entry={"innerText": "上課去", **state})
                self.assertEqual(result["clicks"], [])

    def test_exam_entry_only_in_exam_mode(self):
        self.assertEqual(self.execute(entry={"innerText": "開始測驗"})["clicks"], [])
        self.assertEqual(self.execute(entry={"innerText": "開始測驗"}, exam=True)["clicks"], ["entry"])


class CourseUsageTests(unittest.TestCase):
    def setUp(self):
        self.pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)

    def attempt(self, course_id, before, after, result=False, error=None):
        with patch("utils.security.global_quota_tracker.get_stats", side_effect=[before, after]), \
             patch.object(self.pilot, "_auto_exam_attempt", return_value=result,
                          side_effect=error, create=True):
            return self.pilot.auto_exam({"course_id": course_id})

    def stats(self, used, date="2026-10-25"):
        return {"used": used, "date": date}

    def test_three_attempts_accumulate_and_other_course_is_separate(self):
        self.attempt("A", self.stats(0), self.stats(1))
        self.attempt("B", self.stats(1), self.stats(3), result=True)
        self.attempt("A", self.stats(3), self.stats(4))
        self.assertTrue(self.attempt("A", self.stats(4), self.stats(5), result=True))
        self.assertEqual(self.pilot._course_api_calls, {"A": 3, "B": 2})

    def test_bank_only_attempt_does_not_erase_previous_usage(self):
        self.attempt("A", self.stats(0), self.stats(1))
        self.attempt("A", self.stats(1), self.stats(1), result=True)
        self.assertEqual(self.pilot._course_api_calls["A"], 1)

    def test_failed_attempt_still_records_consumed_calls(self):
        with self.assertRaisesRegex(RuntimeError, "測試中斷"):
            self.attempt("A", self.stats(0), self.stats(2), error=RuntimeError("測試中斷"))
        self.assertEqual(self.pilot._course_api_calls["A"], 2)

    def test_daily_reset_does_not_make_usage_negative(self):
        self.attempt("A", self.stats(20), self.stats(1, "2026-10-26"))
        self.assertEqual(self.pilot._course_api_calls["A"], 1)


class EgovLoginRedirectTests(unittest.TestCase):
    def setUp(self):
        self.pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        self.pilot.running = True
        self.pilot.stat_url = "https://elearn.hrd.gov.tw/learn/mycourse/learn_stat.php"
        self.pilot.driver = Mock()
        self.pilot.safe_sleep = Mock(return_value=True)
        self.pilot.sync_session = Mock(return_value=True)

    def test_intermediate_sso_urls_are_not_treated_as_logged_in(self):
        self.assertFalse(
            AdminEfficiencyPilot._is_elearn_logged_in_url(
                "https://elearn.hrd.gov.tw/egov_login.php?token=xyz",
                check_no_login=False,
            )
        )
        self.assertFalse(
            AdminEfficiencyPilot._is_elearn_logged_in_url(
                "https://www.cp.gov.tw/portal/Clogin.aspx?ReturnUrl=https://elearn.hrd.gov.tw/egov_login.php",
                check_no_login=True,
            )
        )
        self.assertTrue(
            AdminEfficiencyPilot._is_elearn_logged_in_url(
                "https://elearn.hrd.gov.tw/mooc/index.php",
                check_no_login=True,
            )
        )

    def test_wait_for_redirect_survives_egov_login_relay_and_slow_sso(self):
        # 模擬先在 cp.gov.tw 處理中，接著經過 egov_login.php 中繼，最後才進 mooc/index.php 與 learn_stat.php
        urls = [
            "https://www.cp.gov.tw/portal/Clogin.aspx",
            "https://www.cp.gov.tw/portal/LoginSimple.aspx",
            "https://elearn.hrd.gov.tw/egov_login.php?ticket=abc",
            "https://elearn.hrd.gov.tw/mooc/index.php",
            "https://elearn.hrd.gov.tw/learn/mycourse/learn_stat.php",
        ]
        idx = {"i": 0}

        def get_url():
            val = urls[min(idx["i"], len(urls) - 1)]
            idx["i"] += 1
            return val

        type(self.pilot.driver).current_url = property(lambda _self: get_url())
        self.pilot.driver.execute_script.return_value = ""

        with patch("app.time.sleep"):
            ok = self.pilot._wait_for_redirect_and_sync(
                "✅ E政府登入成功", check_no_login=True, timeout_seconds=120
            )
        self.assertTrue(ok)
        # 在到達 mooc/index.php 之前不可提前打斷 egov_login.php 跳去 stat_url
        self.pilot.driver.get.assert_called_once_with(self.pilot.stat_url)
        self.pilot.sync_session.assert_called_once()

    def test_dismiss_announcement_modals_is_called_after_login_and_stat_redirect(self):
        self.pilot.driver.current_url = "https://elearn.hrd.gov.tw/mooc/index.php"
        self.pilot.driver.execute_script.return_value = 1

        with patch("app.time.sleep"):
            ok = self.pilot._wait_for_redirect_and_sync(
                "✅ E政府登入成功", check_no_login=True, timeout_seconds=180
            )
        self.assertTrue(ok)
        self.assertGreaterEqual(self.pilot.driver.execute_script.call_count, 2)

    def test_wait_for_redirect_aborts_immediately_on_portal_error_text(self):
        type(self.pilot.driver).current_url = property(
            lambda _self: "https://www.cp.gov.tw/portal/LoginSimple.aspx"
        )
        self.pilot.driver.execute_script.return_value = "帳號或密碼錯誤，請重新輸入"

        with patch("app.time.sleep"):
            ok = self.pilot._wait_for_redirect_and_sync(
                "✅ E政府登入成功", check_no_login=True, timeout_seconds=120
            )
        self.assertFalse(ok)
        self.pilot.sync_session.assert_not_called()

    def test_wait_s_main_polls_until_button_appears_and_questionnaire_rejects_timeout(self):
        fake_btn = Mock()
        fake_btn.is_displayed.return_value = True
        calls = {"n": 0}

        def find_elems(_by, selector):
            calls["n"] += 1
            if selector == "div.process-btn.pay.active" and calls["n"] >= 4:
                return [fake_btn]
            return []

        self.pilot.driver.find_elements.side_effect = find_elems
        self.pilot.driver.execute_script.return_value = ""
        with patch("app.time.sleep"):
            status, btn = self.pilot._wait_s_main_action_or_status(
                done_keywords=("已通過",),
                none_keywords=("目前沒有任何測驗",),
                timeout=5.0,
            )
        self.assertEqual(status, "button")
        self.assertIs(btn, fake_btn)

        # 問卷若只遇 timeout 不可假完課回 True；需明確回 False
        self.pilot.config = {}
        self.pilot.driver.current_window_handle = "main"
        with patch.object(self.pilot, "_wait_s_main_action_or_status", return_value=("timeout", None)):
            q_ok = self.pilot.auto_questionnaire({"caption": "測試課", "fill": "0", "write_questionnaire": "1"})
        self.assertFalse(q_ok)

    def test_missing_exam_button_twice_marks_manual_review_to_stop_infinite_rescan(self):
        self.pilot.config = {"ai_provider": "Gemini", "ai_api_key": ""}
        self.pilot._answer_map = {"q": {"answer": "1"}}
        self.pilot.answers = []
        self.pilot._exam_fail_counts = {}
        self.pilot._exam_manual_review = {}
        self.pilot.driver.current_url = "https://scitechvista.elearn.hrd.gov.tw/learn/"
        self.pilot.driver.current_window_handle = "main"
        self.pilot.driver.window_handles = ["main"]

        course = {"course_id": "999", "caption": "週日閱讀"}
        with patch.object(self.pilot, "_wait_s_main_action_or_status", return_value=("timeout", None)):
            self.assertFalse(self.pilot._auto_exam_attempt(course))
            self.assertNotIn("999", self.pilot._exam_manual_review)
            self.assertFalse(self.pilot._auto_exam_attempt(course))
            self.assertIn("999", self.pilot._exam_manual_review)

    def test_unavailable_info_page_detection_never_overrides_active_entry(self):
        from app import _match_unavailable_course_reason

        # 只要頁面上還有可用「上課去」入口，就算簡介內文含「已結束」「尚未上架」也不得誤判
        self.assertIsNone(
            _match_unavailable_course_reason(
                "本課程介紹：課程已結束後可領證書，舊版已下架",
                disabled_labels=["已結束"],
                has_active_entry=True,
            )
        )
        # 無可用入口且出現明確下架/非開課期間文案
        self.assertIn(
            "課程已下架",
            _match_unavailable_course_reason("很抱歉，本課程已下架，無法進入。", [], has_active_entry=False) or "",
        )
        self.assertIn(
            "非上課期間",
            _match_unavailable_course_reason("目前非上課期間，請留意開課公告。", [], has_active_entry=False) or "",
        )
        # 無可用入口且停用按鈕顯示已結束
        self.assertIn(
            "已結束",
            _match_unavailable_course_reason("課程資訊", ["課程已結束"], has_active_entry=False) or "",
        )
        # 無可用入口但也沒有任何下架線索 → 回 None 交給原本待查核防護
        self.assertIsNone(_match_unavailable_course_reason("課程簡介載入中", [], has_active_entry=False))

    def test_detect_unavailable_course_on_info_page_and_record_skips_manual_review(self):
        self.pilot.driver.current_url = "https://elearn.hrd.gov.tw/info/10011810"
        self.pilot.driver.execute_script.return_value = {
            "hasActiveEntry": False,
            "disabledLabels": ["已下架"],
            "bodyText": "精神疾病與家庭暴力議題\n本課程已下架",
        }
        self.pilot._completed_in_session = set()
        self.pilot._exam_manual_review = {}
        self.pilot._unavailable_in_session = {}

        reason = self.pilot._detect_unavailable_course_on_info_page()
        self.assertIsNotNone(reason)
        self.pilot._record_unavailable_course(
            {"course_id": "10011810", "caption": "精神疾病與家庭暴力議題"},
            reason,
        )
        self.assertIn("10011810", self.pilot._completed_in_session)
        self.assertIn("10011810", self.pilot._unavailable_in_session)
        self.assertNotIn("10011810", self.pilot._exam_manual_review)


if __name__ == "__main__":
    unittest.main()
