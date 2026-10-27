"""使用既有 ChromeDriver 驗證離線題型與交卷防護，不操作正式平台。"""

import json
from pathlib import Path
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

from app import AdminEfficiencyPilot
from quiz_bank import _read_questions, _fill_answers, _submission_counts, _submit_quiz, _review_grade_counts, _read_correct_from_review, _get_score_from_review
from taipei_eda_course import get_course_modules
from utils.quiz_policy import can_submit


def main():
    options = webdriver.ChromeOptions()
    for flag in ('--headless=new', '--disable-gpu', '--no-first-run', '--disable-background-networking'):
        options.add_argument(flag)
    driver = webdriver.Chrome(service=Service(str(ROOT / 'drivers' / 'chromedriver.exe')), options=options)
    passed = []

    def show(html):
        driver.get('data:text/html;charset=utf-8,' + quote(html))

    def check(name, condition):
        assert condition, name
        passed.append(name)
        print(json.dumps({'scenario': name, 'passed': True}))

    try:
        blocks = []
        for number in range(1, 21):
            multiple = number > 13
            inputs = ''.join(
                f'<div class="r{i}"><input type="{"checkbox" if multiple else "radio"}" '
                f'name="q{number}{"_" + str(i) if multiple else ""}" id="q{number}_{i}" '
                f'value="{1 if multiple else i}"><label for="q{number}_{i}">{text}</label></div>'
                for i, text in enumerate(('甲', '乙', '丙')))
            blocks.append(f'<div class="que" id="question-{number}"><div class="qtext">題目{number}</div><div class="answer">{inputs}</div></div>')
        nav = ''.join(f'<a class="qnbutton">{i}</a>' for i in range(1, 21))
        page = nav + ''.join(blocks)
        show(page)
        questions = _read_questions(driver)
        check('read_13_radio_and_7_checkbox_questions', len(questions) == 20 and sum(q['is_multiple'] for q in questions) == 7)
        answers = {q['name']: ['0', '2'] if q['is_multiple'] else '1' for q in questions}
        check('fill_and_verify_all_20_questions', _fill_answers(driver, answers, questions) == 20)
        check('ready_only_when_all_20_answered', can_submit(**_submission_counts(driver)))
        driver.execute_script("document.querySelectorAll('input:checked').forEach(el => el.checked = false)")
        check('empty_questions_block_submission', not can_submit(**_submission_counts(driver)))

        show(page + '<button onclick="document.body.dataset.clicked=1">完成作答</button>')
        check('incomplete_page_does_not_click_finish', _submit_quiz(driver, None) is None and not driver.execute_script('return document.body.dataset.clicked'))
        _fill_answers(driver, answers, _read_questions(driver))
        driver.execute_script("document.querySelector('button').onclick = function(){document.body.innerHTML='<p>Questions without a response: 7</p><button onclick=\"document.body.dataset.submitted=1\">全部送出並結束</button>';}")
        check('summary_warning_blocks_final_confirmation', _submit_quiz(driver, None) is None and not driver.execute_script('return document.body.dataset.submitted'))

        show(page + '<button>完成作答</button>')
        _fill_answers(driver, answers, _read_questions(driver))
        driver.execute_script("""
            document.querySelector('button').onclick = function() {
                document.body.innerHTML = '<p>答案已儲存</p><button id="confirm">全部送出並結束</button>';
                document.getElementById('confirm').onclick = function() {
                    var modal = document.createElement('div');
                    modal.innerHTML = '<p>Questions without a response: 7</p><button data-action="save">送出</button>';
                    modal.querySelector('button').onclick = function(){document.body.dataset.submitted = 1;};
                    document.body.appendChild(modal);
                };
            };
        """)
        check('late_modal_warning_blocks_submission', _submit_quiz(driver, None) is None and not driver.execute_script('return document.body.dataset.submitted'))

        show(page)
        _fill_answers(driver, answers, _read_questions(driver))
        driver.execute_script("document.querySelectorAll('.que').forEach(q => {q.classList.add('correct');var s=document.createElement('div');s.className='state';s.textContent='答對';q.append(s);})")
        check('review_reads_single_and_multiple_correct_answers', len(_read_correct_from_review(driver)) == 20)
        check('review_counts_all_20_graded', _review_grade_counts(driver) == (20, 20))

        short = '<div class="que shortanswer" id="question-text"><div class="qtext"><p>哪些項目正確？</p><p>1.甲</p><p>2.乙</p><p>3.丙</p><p>4.丁</p></div><input type="text" name="q1_answer"></div>'
        show(short)
        text_questions = _read_questions(driver)
        check('numeric_shortanswer_is_supported', text_questions[0]['supported'] and text_questions[0]['numeric_text'])
        check('numeric_shortanswer_empty_blocks_submit', not can_submit(**_submission_counts(driver)))
        check('numeric_shortanswer_sorted_without_separators', _fill_answers(driver, {'question-text': ['4', '1', '2']}, text_questions) == 1 and driver.find_element(By.NAME, 'q1_answer').get_attribute('value') == '124')
        check('numeric_shortanswer_counts_as_answered', can_submit(**_submission_counts(driver)))
        driver.execute_script("document.querySelector('.que').classList.add('correct')")
        check('numeric_shortanswer_verified_review', _read_correct_from_review(driver) == {'question-text': ['1', '2', '4']})
        show(short.replace('1.甲', '一般文字').replace('2.乙', '無編號').replace('3.丙', '').replace('4.丁', ''))
        check('unrecognized_text_question_stays_blocked', not _read_questions(driver)[0]['supported'])

        show('<table>' + ''.join(f'<tr><td><input type="radio" name="q{i}" value="1" {"checked" if i <= 13 else ""}></td></tr>' for i in range(1, 21)) + '</table>')
        pilot = AdminEfficiencyPilot.__new__(AdminEfficiencyPilot)
        pilot.driver = driver
        pilot._exam_manual_review = {}
        rows = driver.find_elements(By.CSS_SELECTOR, 'tr')
        check('egov_rejects_13_of_20_answers', not pilot._verify_exam_ready({'course_id': 'fixture'}, rows))
        driver.execute_script('document.querySelectorAll("input").forEach(input => input.checked = true)')
        check('egov_accepts_20_of_20_answers', pilot._verify_exam_ready({'course_id': 'fixture'}, rows))
        check('egov_partial_reply_cannot_use_old_checked_answers', not pilot._apply_interactive_exam_answers({'course_id': 'fixture'}, rows, {1: ['A']}))

        show('<p>及格標準：80 分</p><p>測驗分數達80分以上</p>')
        check('grade_instructions_are_not_actual_scores', _get_score_from_review(driver) == '')
        show('<table><tr><th>成績</th><td>8.00 / 10.00</td></tr></table>')
        check('actual_ratio_grade_is_percentage', '80' in _get_score_from_review(driver))

        course = '<p>修課時間：01:48:41</p><a href="https://example.invalid/elearn/mod/scorm/view.php?id=1">最吸睛！4小時簡報圖解術</a>'
        modules = get_course_modules(driver, 'data:text/html;charset=utf-8,' + quote(course))
        check('formal_scorm_with_presentation_in_title_is_kept', bool(modules.get('scorm_url')))
        check('official_study_record_is_read', modules.get('study') == '01:48:41')
        return len(passed)
    finally:
        driver.quit()


if __name__ == '__main__':
    print(f'passed: {main()}')
