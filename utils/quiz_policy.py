"""雙平臺共用答題政策；不讀取瀏覽器、帳密或題庫。"""

import re

MAX_QUIZ_ATTEMPTS = 3


def has_unanswered_warning(text):
    """辨識實際漏答警告，單純操作說明不算漏答。"""
    return bool(re.search(
        r'Questions without a response\s*[:：]\s*[1-9]\d*|'
        r'^(?:尚未回答|未作答|未回答)\s*$|'
        r'(?:尚有|仍有)\s*[1-9]\d*\s*題(?:未回答|未作答)|'
        r'(?:未回答|未作答)題數\s*[:：]\s*[1-9]\d*',
        str(text or ''), re.I | re.M))


def needs_ai_review(answer, failed_attempts=0):
    """題庫缺答或已確認未及格時，需要補答／覆核。"""
    return answer is None or answer == "" or answer == [] or failed_attempts > 0


def can_submit(total, answered, *, expected_total=None, skipped=0):
    """必須完整讀取且全部填答驗證通過，才能交卷。"""
    return (total > 0 and answered == total and skipped == 0
            and (expected_total is None or expected_total == total))


def grade_passed(score, threshold, status=""):
    """三態結果：及格、未及格、未知；未知不得視為零分重考。"""
    if score is not None:
        return float(score) >= float(threshold)
    text = str(status).lower()
    if any(word in text for word in ("不及格", "未通過", "不合格", "未合格", "未完成", "fail")):
        return False
    if any(word in text for word in ("及格", "通過", "合格", "passed")):
        return True
    return None


def course_completed(has_quiz, passed, survey_done):
    return (not has_quiz or passed is True) and survey_done is True


def grade_evidence(text):
    """只讀明確成績欄位／結果狀態；排除門檻、操作說明與空白分數。"""
    lines = [line.strip() for line in str(text or '').splitlines() if line.strip()]
    status = ''
    for index, line in enumerate(lines):
        field = re.match(r'^(?:測驗分數|測驗成績|課程紀錄得分|成績|得分|分數|總分|評分|Grade|Marks)\s*[：:]?\s*(.*)$', line, re.I)
        if field:
            value = field.group(1) or (lines[index + 1] if index + 1 < len(lines) else '')
            if not re.search(r'門檻|標準|以上|以下|必須|須達|分數達', value) and not value.startswith('達'):
                score = extract_score(value + ' 分' if re.fullmatch(r'\d+(?:\.\d+)?', value) else value)
                if score is not None and 0 <= score <= 100:
                    return score, ''
        result = re.fullmatch(r'(?:(?:測驗結果|測驗|結果|通過狀態|作答結果|狀態)\s*(?:為|是)?\s*[：:]?\s*)?(已通過|未通過|不及格|及格|不合格|合格|passed|failed)[。！!\s]*', line, re.I)
        if result:
            status = result.group(1)
    return None, status


def answer_values(raw, options, *, multiple=False):
    """將題庫／AI 的值或選項文字對應為本題值；無效或單選多答均拒絕。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        text = str(raw).strip()
        # 先比對完整文字，避免選項內逗號被切開。
        exact = [str(key) for key, value in options.items() if text == str(key) or text == str(value).strip()]
        if len(exact) == 1:
            return exact
        parts = [part for part in re.split(r"[,，、;；\s]+", text) if part]
    values = []
    for part in parts:
        text = str(part).strip()
        matches = [str(key) for key, value in options.items() if text == str(key) or text == str(value).strip()]
        if len(matches) != 1:
            return []
        if matches[0] not in values:
            values.append(matches[0])
    return values if multiple or len(values) == 1 else []


def extract_score(score_text):
    """解析百分制分數；支援「得80.00分(滿分為100.00分)」「8.00/10.00」「80 滿分 100」「(80%)」「80 分」。"""
    text = str(score_text or '')
    def _ratio(got, total):
        try:
            return float(got) / float(total) * 100.0 if float(total) > 0 else None
        except Exception:
            return None
    m = re.search(r'得\s*([\d.]+)\s*分.*?滿分為?\s*([\d.]+)', text)
    if m:
        return _ratio(m.group(1), m.group(2))
    m = re.search(r'得\s*([\d.]+)\s*分', text)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    m = re.search(r'([\d.]+)\s*/\s*([\d.]+)', text)
    if m:
        return _ratio(m.group(1), m.group(2))
    m = re.search(r'([\d.]+)\s*滿分為?\s*([\d.]+)', text)
    if m:
        return _ratio(m.group(1), m.group(2))
    m = re.search(r'([\d.]+)\s*%', text)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    m = re.search(r'([\d.]+)\s*分', text)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    return None

