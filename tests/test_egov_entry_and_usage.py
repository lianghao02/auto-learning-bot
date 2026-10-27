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


if __name__ == "__main__":
    unittest.main()
