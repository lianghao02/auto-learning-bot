from __future__ import annotations

import ctypes
import io
import json
import logging
import os
import random
import re
import sqlite3
import sys
import threading
import time as _std_time
import traceback
import unicodedata
from contextlib import closing
from difflib import get_close_matches

import psutil
import requests
from colorama import Fore, Style
from selenium import webdriver
from selenium.common.exceptions import NoAlertPresentException, UnexpectedAlertPresentException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait as _StdWebDriverWait

from utils.app_paths import app_dir, ensure_seeded_database as _std_ensure_seeded_database, log_path, user_data_path
from utils.config_io import get_db_connection, write_json_atomically
from utils.helpers import (
    INTERACTIVE_QUIZ_TIMEOUT_SECONDS,
    draw_bar,
    get_logger,
    maintain_driver_windows_hidden,
    match_radio_option_index,
    parse_multiple_choice_answers,
    sec_to_str,
    set_driver_window_visibility,
    to_sec,
)
from utils.quiz_policy import (
    MAX_QUIZ_ATTEMPTS,
    answer_values,
    can_submit,
    grade_evidence,
    grade_passed,
    needs_ai_review,
)
from utils.security import is_cloud_sync_enabled, resolve_gas_url, validate_ai_base_url
from utils.webdriver_mgr import download_best_chromedriver as _std_download_best_chromedriver

GLOBAL_DB_LOCK = threading.Lock()
EXAM_AI_OUTAGE_DEFER_SECONDS = 600  # AI 服務中斷後延後重考的冷卻時間
EXAM_AI_OUTAGE_MAX_DEFERS = 3        # 每門課最多寬限幾次，避免 AI 長時間中斷時無限延後

_std_logger = get_logger()


class _AppTimeProxy:
    def __getattr__(self, name: str):
        app_mod = sys.modules.get("app")
        target = getattr(app_mod, "time", _std_time) if app_mod is not None else _std_time
        return getattr(target, name)


class _AppLoggerProxy:
    def __getattr__(self, name: str):
        app_mod = sys.modules.get("app")
        target = getattr(app_mod, "logger", _std_logger) if app_mod is not None else _std_logger
        return getattr(target, name)


time = _AppTimeProxy()
logger = _AppLoggerProxy()


def WebDriverWait(*args, **kwargs):
    app_mod = sys.modules.get("app")
    cls = getattr(app_mod, "WebDriverWait", _StdWebDriverWait) if app_mod is not None else _StdWebDriverWait
    return cls(*args, **kwargs)


def ensure_seeded_database(*args, **kwargs):
    app_mod = sys.modules.get("app")
    fn = getattr(app_mod, "ensure_seeded_database", _std_ensure_seeded_database) if app_mod is not None else _std_ensure_seeded_database
    return fn(*args, **kwargs)


def download_best_chromedriver(*args, **kwargs):
    app_mod = sys.modules.get("app")
    fn = getattr(app_mod, "download_best_chromedriver", _std_download_best_chromedriver) if app_mod is not None else _std_download_best_chromedriver
    return fn(*args, **kwargs)


def get_package_dashboard_script() -> str:
    app_mod = sys.modules.get("app")
    return getattr(app_mod, "_PACKAGE_DASHBOARD_SCRIPT", "")


# 每一步只點一個可操作按鈕，等待頁面更新後再由 Python 決定是否繼續。
_COURSE_ENTRY_SCRIPT = r"""
function available(button) {
    var style = window.getComputedStyle(button);
    return !button.disabled && button.getAttribute('aria-disabled') !== 'true' &&
        button.getClientRects().length > 0 && style.display !== 'none' &&
        style.visibility !== 'hidden' && style.visibility !== 'collapse';
}
function label(button) {
    return (button.innerText || button.value || button.textContent || '').trim();
}
var modalBtns = document.querySelectorAll('.modal button, .dialog button, div[role="dialog"] button, button.btn-primary, button.btn-confirm');
for (var m = 0; m < modalBtns.length; m++) {
    var modal = modalBtns[m];
    if (available(modal) && ['確定', '確認'].indexOf(label(modal)) !== -1) {
        var modalLabel = label(modal);
        modal.click();
        return {kind: 'confirm', label: modalLabel};
    }
}
var entryLabels = ['上課去', '進入課程', '開始上課', '前往教室', '繼續學習', '觀看影片', '前往研習', '開始學習', '前往學習'];
if (includeExam) entryLabels = entryLabels.concat(['認證', '進行測驗', '開始測驗', '參加測驗', '前往測驗', '測驗']);
var enrollLabels = ['報名課程', '我要報名', '加入課程', '確認報名', '選課', '我要選課'];
var btns = document.querySelectorAll('button, a.btn, a, input[type="button"], input[type="submit"]');
for (var i = 0; i < btns.length; i++) {
    var button = btns[i];
    if (!available(button)) continue;
    var text = label(button);
    var cleanText = text.replace(/\s+/g, '');
    var href = (button.getAttribute('href') || '').toLowerCase();
    var onclick = (button.getAttribute('onclick') || '').toLowerCase();
    var isEntry = entryLabels.some(k => cleanText.indexOf(k) !== -1) ||
        onclick.indexOf('goclass') !== -1 || onclick.indexOf('gotocourse') !== -1 ||
        href.indexOf('action=learn') !== -1;
    var isEnroll = includeEnrollment && enrollLabels.some(k => cleanText.indexOf(k) !== -1);
    if (isEntry || isEnroll) {
        button.click();
        return {kind: isEntry ? 'entry' : 'enroll', label: text || '課程連結'};
    }
}
return null;
"""


def _normalize_q(text: str) -> str:
    """題目正規化：小寫、去空白、只保留中文/英數字。
    用於 _answer_map 的 key 和 difflib fuzzy 比對。
    """
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    # 只保留中文字、英文字母、數字（去掉標點、空白、特殊符號）
    text = re.sub(r"[^\w\u4e00-\u9fff\u3400-\u4dbf]", "", text)
    return text


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

_ALL_ABOVE_PATTERNS = (
    "以上皆是",
    "以上皆可",
    "以上皆正確",
    "以上皆對",
    "all of the above",
    "ll of the above",
)


class _PlainTextLogFormatter(logging.Formatter):
    """寫入純文字日誌檔前剝除 ANSI 終端機色碼，保持可讀性。"""

    def format(self, record):
        return _ANSI_ESCAPE_RE.sub("", super().format(record))


def _can_resolve_exam_answer(ans, option_texts, num_radios: int, num_checkboxes: int) -> bool:
    """預先驗證題庫答案是否能實際對應到當前頁面的單選或多選控制項。"""
    if ans is None:
        return False
    if num_checkboxes > 0:
        valid_letters = {chr(ord("A") + i) for i in range(num_checkboxes)}
        ans_text = (
            ans
            if isinstance(ans, str)
            else (ans[0] if isinstance(ans, list) and ans else str(ans))
        )
        ans_norm = str(ans_text or "").strip()
        if not ans_norm:
            return False
        if any(p in ans_norm.lower() or p in ans_norm for p in _ALL_ABOVE_PATTERNS):
            return True
        expected_letters = answer_values(
            ans,
            {chr(65 + i): text for i, text in enumerate((option_texts or [])[:num_checkboxes])},
            multiple=True,
        )
        if not expected_letters:
            expected_letters = parse_multiple_choice_answers(ans, num_options=num_checkboxes)
        if not expected_letters and option_texts:
            for i, opt_t in enumerate(option_texts[:num_checkboxes]):
                opt_clean = (opt_t or "").strip()
                if opt_clean and (opt_clean in ans_norm or ans_norm in opt_clean):
                    expected_letters.append(chr(ord("A") + i))
        resolved = [ch for ch in expected_letters if ch in valid_letters]
        return bool(resolved)
    if num_radios > 0:
        idx = match_radio_option_index(ans, option_texts, num_radios)
        return idx is not None and 0 <= idx < num_radios
    return False


_UNAVAILABLE_INFO_TEXT_KEYWORDS = (
    "查無此課程",
    "找不到此課程",
    "課程不存在",
    "課程已下架",
    "此課程已下架",
    "本課程已下架",
    "已下架",
    "課程已關閉",
    "此課程已關閉",
    "本課程已關閉",
    "課程尚未上架",
    "本課程尚未上架",
    "尚未上架",
    "非上課期間",
    "非開放期間",
    "非開課期間",
    "已超過開課期間",
    "已超過上課期間",
    "已過開課期間",
    "開課期間已結束",
    "上課期間已結束",
    "已逾開課期間",
    "本課程已結束",
    "課程已結束",
    "直播已結束",
    "本課程尚未開放",
    "無法進入教室",
)

_UNAVAILABLE_DISABLED_BTN_KEYWORDS = (
    "已下架",
    "已結束",
    "已關閉",
    "尚未開課",
    "尚未上架",
    "未開放",
    "非上課期間",
    "報名已截止",
)


def _match_unavailable_course_reason(
    body_text: str,
    disabled_labels: list[str] | tuple[str, ...] = (),
    has_active_entry: bool = False,
) -> str | None:
    """依據 /info/ 頁面快照判讀課程是否已下架或非開課期間。

    只要頁面上仍存在可見且可點擊的上課入口按鈕，一律回傳 None，避免誤判正常開課課程。
    """
    if has_active_entry:
        return None
    text = str(body_text or "")
    for kw in _UNAVAILABLE_INFO_TEXT_KEYWORDS:
        if kw in text:
            return f"平臺顯示「{kw}」"
    for label in disabled_labels or ():
        clean_label = str(label or "").strip()
        if not clean_label:
            continue
        for kw in _UNAVAILABLE_DISABLED_BTN_KEYWORDS:
            if kw in clean_label:
                return f"課程入口狀態為「{clean_label[:20]}」"
    return None


_NEGATION_TOKENS = ("不", "非", "未", "無", "誤", "錯", "免")
_TRUE_FALSE_ANSWERS = frozenset({"正確", "錯誤", "對", "錯", "是", "否", "o", "x", "true", "false"})


def _negation_signature(text: str) -> tuple[int, ...]:
    """回傳題幹否定關鍵字計數簽章，防止模糊比對把肯定句與否定句誤配。"""
    s = str(text or "")
    return tuple(s.count(tok) for tok in _NEGATION_TOKENS)


def _is_driver_disconnect_error(err_str: str) -> bool:
    """判斷例外訊息是否代表瀏覽器視窗已關閉或 WebDriver 連線中斷。"""
    raw = str(err_str or "")
    low = raw.lower()
    return (
        "HTTPConnectionPool" in raw
        or "Failed to establish a new connection" in raw
        or "WebDriver" in raw
        or "session" in low
        or "chrome not reachable" in low
        or "no such window" in low
        or "target window already closed" in low
        or "web view not found" in low
        or "disconnected" in low
    )

