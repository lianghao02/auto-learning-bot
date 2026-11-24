# /// script
# dependencies = [
#   "selenium",
#   "requests",
#   "colorama",
#   "psutil",
# ]
# ///

import sys
import io
import time
import os
import re
import random
import logging
import json
import sqlite3
import unicodedata
import ctypes
import threading
from difflib import get_close_matches
import requests
import psutil
import atexit
import signal
import traceback
import weakref
from contextlib import closing
from utils.config_io import get_db_connection, write_json_atomically
from utils.app_paths import app_dir, ensure_seeded_database, log_path, user_data_path

# 強制 stdout/stderr 使用 UTF-8，避免在 cp950 環境下因 emoji 崩潰
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import UnexpectedAlertPresentException, NoAlertPresentException
from colorama import Fore, Style

from utils.helpers import (
    get_logger,
    to_sec,
    sec_to_str,
    draw_bar,
    set_driver_window_visibility,
    maintain_driver_windows_hidden,
    INTERACTIVE_QUIZ_TIMEOUT_SECONDS,
    match_radio_option_index,
    parse_multiple_choice_answers,
)
from utils.security import is_cloud_sync_enabled, resolve_gas_url, validate_ai_base_url
from utils.quiz_policy import MAX_QUIZ_ATTEMPTS, answer_values, can_submit, grade_evidence, grade_passed, needs_ai_review
from utils.webdriver_mgr import download_best_chromedriver

from egov import (
    EXAM_AI_OUTAGE_DEFER_SECONDS,
    EXAM_AI_OUTAGE_MAX_DEFERS,
    EgovAuthMixin,
    EgovExamSurveyMixin,
    EgovQuestionStoreMixin,
    EgovStudyMixin,
    GLOBAL_DB_LOCK,
    _ALL_ABOVE_PATTERNS,
    _ANSI_ESCAPE_RE,
    _COURSE_ENTRY_SCRIPT,
    _NEGATION_TOKENS,
    _PlainTextLogFormatter,
    _TRUE_FALSE_ANSWERS,
    _UNAVAILABLE_DISABLED_BTN_KEYWORDS,
    _UNAVAILABLE_INFO_TEXT_KEYWORDS,
    _can_resolve_exam_answer,
    _is_driver_disconnect_error,
    _match_unavailable_course_reason,
    _negation_signature,
    _normalize_q,
)
_LIVE_PILOTS: weakref.WeakSet = weakref.WeakSet()
_PROCESS_HOOKS_REGISTERED = False


def _cleanup_all_pilots(*_args):
    for pilot in list(_LIVE_PILOTS):
        try:
            pilot._cleanup()
        except Exception:
            pass


def _register_process_cleanup_hooks_once():
    global _PROCESS_HOOKS_REGISTERED
    if _PROCESS_HOOKS_REGISTERED:
        return
    _PROCESS_HOOKS_REGISTERED = True
    atexit.register(_cleanup_all_pilots)
    if threading.current_thread() is threading.main_thread():
        try:
            signal.signal(signal.SIGTERM, _cleanup_all_pilots)
        except (AttributeError, OSError, ValueError):
            pass
        try:
            signal.signal(signal.SIGBREAK, _cleanup_all_pilots)
        except (AttributeError, OSError, ValueError):
            pass

# 降低 Selenium 自身的冗長日誌
logging.getLogger("selenium").setLevel(logging.ERROR)
logger = get_logger()


_PACKAGE_DASHBOARD_SCRIPT = """
                    var cards = document.querySelectorAll('.course-item, .card, .thumbnail, div[class*="item"], .col-md-4, .col-sm-6, .panel, div[class*="panel"]');
                    var results = [];
                    for (var i = 0; i < cards.length; i++) {
                        var txt = cards[i].innerText || cards[i].textContent || '';
                        var html = cards[i].innerHTML || '';
                        var controls = cards[i].querySelectorAll('[onclick*="goCourse"], [onclick*="gotoCourse"], [onclick*="unEnroll"]');
                        var m = null;
                        for (var c = 0; c < controls.length; c++) {
                            m = (controls[c].getAttribute('onclick') || '').match(/(?:goCourse|gotoCourse|unEnroll)\\s*\\(\\s*['"]?(\\d{6,10})/);
                            if (m && m[1]) break;
                        }
                        // 卡片已展開子課程表格時，不可再以內層 /info/ 連結推測母課程 ID。
                        if (!m && !cards[i].querySelector('table, tbody, tr')) {
                            m = html.match(/(?:info\\/|course_id=|\\/course\\/)['"]?(\\d{6,10})/);
                        }
                        var titleEl = cards[i].querySelector('h3, h4, .title, .caption, strong, .panel-title');
                        var title = titleEl ? (titleEl.innerText || titleEl.textContent || '').trim() : '';
                        if (!title) {
                            var lines = txt.split('\\n').map(function(s) { return s.trim(); }).filter(function(s) { return s.length > 2 && s.indexOf('組裝') === -1; });
                            title = lines[0] || '組裝課程';
                        }

                        // 平台的完成率可能顯示在文字、aria-valuenow 或 style 寬度。
                        var progress = cards[i].querySelector('.progress-bar, [role="progressbar"], [class*="progress"]');
                        var progressValue = progress ? (progress.getAttribute('aria-valuenow') || progress.getAttribute('data-progress') || '') : '';
                        var progressStyle = progress ? (progress.getAttribute('style') || '') : '';
                        var is100 = /(^|\\s)100\\s*%/.test(txt) || Number(progressValue) >= 100 || /width\\s*:\\s*100\\s*%/i.test(progressStyle);

                        if (m && m[1]) {
                            results.push({id: m[1], title: title, is100: is100});
                        }
                    }

                    // 課程卡片的 onclick 可能由平台改為連結；直接掃描課程連結補漏。
                    var linkIds = {};
                    for (var r = 0; r < results.length; r++) linkIds[results[r].id] = true;
                    var packageLinks = document.querySelectorAll('a[href*="/info/"], a[href*="course_id="], [onclick*="goCourse"], [onclick*="gotoCourse"], [onclick*="unEnroll"]');
                    for (var j = 0; j < packageLinks.length; j++) {
                        var link = packageLinks[j];
                        // 展開表格中的連結均為子課程，不可當作母套裝。
                        if (link.closest('table, tbody, tr')) continue;
                        var source = (link.href || '') + ' ' + (link.getAttribute('onclick') || '');
                        var matched = source.match(/(?:goCourse|gotoCourse|unEnroll)\\s*\\(\\s*['"]?(\\d{6,10})/) ||
                                      source.match(/(?:info\\/|course_id=|\\/course\\/)[ '"]?(\\d{6,10})/);
                        if (!matched || !matched[1] || linkIds[matched[1]]) continue;
                        linkIds[matched[1]] = true;
                        var container = link.closest('.course-item, .course-card, .card, .thumbnail, .panel, div[class*="course"], div[class*="Course"], div[class*="item"]') || link.parentElement;
                        var containerText = container ? (container.innerText || container.textContent || '') : '';
                        var titleEl2 = container && container.querySelector('h1, h2, h3, h4, h5, .course-title, .title, .caption, strong, .panel-title');
                        var linkTitle = titleEl2 ? (titleEl2.innerText || titleEl2.textContent || '').trim() : ((link.innerText || link.textContent || '').trim() || '組裝課程');
                        var linkProgress = container && container.querySelector('.progress-bar, [role="progressbar"], [class*="progress"]');
                        var linkProgressValue = linkProgress ? (linkProgress.getAttribute('aria-valuenow') || linkProgress.getAttribute('data-progress') || '') : '';
                        var linkProgressStyle = linkProgress ? (linkProgress.getAttribute('style') || '') : '';
                        var linkIs100 = /(^|\\s)100\\s*%/.test(containerText) || Number(linkProgressValue) >= 100 || /width\\s*:\\s*100\\s*%/i.test(linkProgressStyle);
                        results.push({id: matched[1], title: linkTitle, is100: linkIs100});
                    }
                    return results;
"""

class UILogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        msg = self.format(record)
        if self.callback:
            self.callback(msg)


class ThreadBoundUILogHandler(logging.Handler):
    """🧠 線程綁定全自動日誌路由轉接器 (Thread-Bound Log Router)
    自動精確過濾目前 Thread 產生的任何 logger.info 訊息，100% 準確分流至各自控制台，零跨頁污染！
    """
    _active_pilots = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, thread_id, pilot):
        with cls._lock:
            cls._active_pilots[thread_id] = pilot

    @classmethod
    def unregister(cls, thread_id):
        with cls._lock:
            cls._active_pilots.pop(thread_id, None)

    def emit(self, record):
        tid = threading.get_ident()
        with self._lock:
            pilot = self._active_pilots.get(tid)
        if not pilot:
            return
        if getattr(pilot, "ui_handler", None):
            pilot.ui_handler.emit(record)
        if getattr(pilot, "file_handler", None):
            try:
                pilot.file_handler.emit(record)
            except Exception:
                pass


# 全域註冊 ThreadBound Router 確保任何地方 logger.info 都能精確導向該平臺 UI
_global_router = ThreadBoundUILogHandler()
_global_router.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
)
if not any(isinstance(h, ThreadBoundUILogHandler) for h in logger.handlers):
    logger.addHandler(_global_router)


def _version_tuple(version):
    nums = re.findall(r"\d+", str(version or ""))
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def _is_newer_version(latest, current):
    return _version_tuple(latest) > _version_tuple(current)


def _read_local_version() -> str:
    try:
        return (app_dir() / "version.txt").read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError):
        return "V0.0.0"


def _read_local_changelog() -> str:
    try:
        text = (app_dir() / "CHANGELOG.md").read_text(encoding="utf-8-sig").strip()
        if text:
            return text
    except (OSError, UnicodeError):
        pass
    return (
        "V2.3.0 雙平臺穩定性強化與架構瘦身版\n"
        "• Gemini 3.5 Flash-Lite 升級與跨節點備援鏈\n"
        "• 雙平臺下架判讀、同源抓正解、長時數重登與自癒修復\n"
        "• ui_parts / egov 模組化架構與 PySide6-Essentials 瘦身"
    )




class AdminEfficiencyPilot(
    EgovAuthMixin,
    EgovQuestionStoreMixin,
    EgovExamSurveyMixin,
    EgovStudyMixin,
):
    VERSION = _read_local_version()
    CHANGELOG = _read_local_changelog()



    def __init__(
        self,
        config_path=None,
        log_callback=None,
        config_override=None,
        progress_callback=None,
        quiz_interactive_callback=None,
        course_state_callback=None,
    ):
        self.course_state_callback = course_state_callback
        self.progress_callback = progress_callback
        self.quiz_interactive_callback = quiz_interactive_callback
        self.log_callback = log_callback
        self.ui_handler = UILogHandler(log_callback) if log_callback else None
        if self.ui_handler:
            self.ui_handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
            )
        self._auto_healing_count = 0
        self.config = self.load_config(config_path)


        # ⭐ 重要：config_override 要完整覆蓋
        if config_override:
            # ⭐ 只更新傳入的字段，保留其他設定
            self.config.update(config_override)

        if "settings" in self.config:
            for key, value in self.config["settings"].items():
                if key not in self.config:
                    self.config[key] = value

        # ⭐ 把 accounts[0] 的欄位展開到頂層（供 login_ecpa/login_egov 使用）
        accounts = self.config.get("accounts", [])
        if accounts and isinstance(accounts, list) and len(accounts) > 0:
            acc = accounts[0]
            if "account" not in self.config and "account" in acc:
                self.config["account"] = acc["account"]
            if "password" not in self.config and "password" in acc:
                self.config["password"] = acc["password"]
            if "login_type" not in self.config and "login_type" in acc:
                self.config["login_type"] = acc["login_type"]
            if "name" not in self.config and "name" in acc:
                self.config["name"] = acc["name"]

        # ⭐ 調試：打印最終配置（遮蔽敏感欄位）
        logger.info(f"📋 最終配置: headless={self.config.get('headless', True)}")
        _safe_settings = {k: ("***" if "key" in k.lower() or "password" in k.lower() else v) for k, v in self.config.get('settings', {}).items()}
        logger.info(f"📋 settings={_safe_settings}")

        self.version = self.VERSION
        self.changelog = self.CHANGELOG
        self._update_checked = False
        # 讀取題庫答案
        # 優先從 questions.db（SQLite）載入，建立 normalized lookup dict
        # fallback: answers.json -> answer.json
        self.answer_path = str(user_data_path("answers.json"))
        # _answer_map: normalize(q) -> {"answer":..., "options":[...], "question":...}
        # _answer_keys: key list 供 difflib fuzzy 使用
        self._answer_map = {}
        self._answer_keys = []
        # ⚡ In-Memory 快取 token 索引（預先建立，避免 AttributeError）
        self._answer_token_map = {}
        self.answers = []  # 向後相容
        self._session_completed_count = 0
        self._session_passed_count = 0
        loaded = self.config.get("login_type") == "taipei_eda"


        # 優先：questions.db（SQLite，含選項結構）
        db_path = str(ensure_seeded_database())
        if not loaded and os.path.exists(db_path):
            try:
                conn = get_db_connection(db_path)
                rows = conn.execute(
                    "SELECT question, option_a, option_b, option_c, option_d, answer FROM questions"
                ).fetchall()
                conn.close()
                for row in rows:
                    q = (row["question"] or "").strip()
                    a = (row["answer"] or "").strip()
                    if not q or not a:
                        continue
                    opts = [
                        (row["option_a"] or "").strip(),
                        (row["option_b"] or "").strip(),
                        (row["option_c"] or "").strip(),
                        (row["option_d"] or "").strip(),
                    ]
                    opts = [o for o in opts if o]
                    nk = _normalize_q(q)
                    if nk and nk not in self._answer_map:
                        self._answer_map[nk] = {
                            "answer": a,
                            "options": opts,
                            "question": q,
                        }
                self._answer_keys = list(self._answer_map.keys())
                # ⚡ In-Memory 快取：預先建立雙層查找結構（精確 key → frozenset token 備用）
                self._answer_token_map = {
                    k: frozenset(k.split()) for k in self._answer_keys
                }
                logger.info(
                    f"📚 已載入題庫（questions.db）：{len(self._answer_map)} 題，In-Memory 快取索引已建立"
                )
                loaded = True
            except Exception as e:
                logger.warning(f"📚 questions.db 讀取失敗: {e}")

        # fallback: answers.json
        if not loaded and os.path.exists(self.answer_path):
            try:
                with open(self.answer_path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    for item in raw:
                        q = item.get("題目", "").strip()
                        a = item.get("答案", "").strip()
                        if q and a:
                            self.answers.append((q, a))
                            nk = _normalize_q(q)
                            if nk and nk not in self._answer_map:
                                self._answer_map[nk] = {
                                    "answer": a,
                                    "options": [],
                                    "question": q,
                                }
                    self._answer_keys = list(self._answer_map.keys())
                    logger.info(
                        f"📚 已載入題庫（answers.json）：{len(self._answer_map)} 題"
                    )
                    loaded = True
            except Exception as e:
                logger.warning(f"📚 answers.json 讀取失敗: {e}")

        # fallback: answer.json
        if not loaded:
            fallback_path = str(app_dir() / "answer.json")
            if os.path.exists(fallback_path):
                try:
                    with open(fallback_path, encoding="utf-8") as f:
                        raw = json.load(f)
                    for k, val in raw.items():
                        if k.startswith("_"):
                            continue
                        a = val[0] if isinstance(val, list) else str(val)
                        self.answers.append((k, a))
                        nk = _normalize_q(k)
                        if nk and nk not in self._answer_map:
                            self._answer_map[nk] = {
                                "answer": a,
                                "options": [],
                                "question": k,
                            }
                    self._answer_keys = list(self._answer_map.keys())
                    logger.info(
                        f"📚 已載入題庫（answer.json）：{len(self._answer_map)} 題"
                    )
                    loaded = True
                except Exception as e:
                    logger.warning(f"📚 answer.json 讀取失敗: {e}")

        if not loaded:
            logger.info("📚 未找到題庫檔案，跳過自動作答功能")

        self.api_url = "https://elearn.hrd.gov.tw/mooc/user/co_get_course.php"
        self.stat_url = "https://elearn.hrd.gov.tw/mooc/user/learn_stat.php"
        self.ecpa_url = "https://ecpa.dgpa.gov.tw/webform/clogin.aspx?returnUrl=https://elearn.hrd.gov.tw/sso_verify.php"

        self.driver = None
        self.wait = None
        self.http_session = requests.Session()
        self.current_idx = 0
        self.total_courses = 0
        self._driver_service = None
        self._managed_pids = set()
        self.log_callback = log_callback
        self.running = True  # 停止開關
        self._exam_fail_counts = {}  # course_id → 不及格次數
        self._course_api_calls = {}  # course_id → 本次執行所有測驗嘗試的 API 用量
        self._completed_in_session = (
            set()
        )  # course_id → 本次已成功處理（考試通過+問卷完成）
        self._exam_manual_review = {}  # course_id → 無法開啟測驗，待下次重新嘗試或人工確認
        self._unavailable_in_session = {}  # course_id → 本輪偵測為平臺已下架／非開課期間課程
        self._course_relogin_counts = {}  # course_id → 重登/重試次數防護
        self._last_session_refresh_time = time.time()  # 上次主動刷新 Session 時間
        self._expanded_packages = set()  # 手動修復模式已檢查之組裝/套裝課程 ID
        self._package_preflight_completed = False  # 組裝課程手動修復檢查狀態
        self._last_course_count = 0

        # 防螢幕關閉
        self._keep_awake_stop = threading.Event()
        self._keep_awake_thread = None

        # 🔒 獨立日誌管道 (Instance-Scoped Isolated Logger)
        self.login_type = self.config.get("login_type", "default")
        self.instance_id = f"{self.login_type}_{id(self)}"
        self.log_instance = logging.getLogger(f"Pilot.{self.instance_id}")
        self.log_instance.setLevel(logging.INFO)
        self.log_instance.propagate = False  # 阻止日誌向 Root Logger 擴散造成頻道污染！
        self.logger = self.log_instance  # 使 self.logger 指向專屬實例！

        if self.log_callback:
            self.ui_handler = UILogHandler(self.log_callback)
            self.ui_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
                )
            )
            self.logger.addHandler(self.ui_handler)
        else:
            self.ui_handler = None

        # 日誌檔案延後至 run() 實際啟動時才建立（避免僅初始化實例或提前返回就把前輪日誌清空為 0 bytes）
        self.log_file = str(log_path(f"debug_{self.config.get('login_type', 'default')}.log"))
        self.file_handler = None

        # 以弱參考集合集中管理清理，避免重複註冊累積實例或雙開時互蓋 signal handler
        _LIVE_PILOTS.add(self)
        _register_process_cleanup_hooks_once()

        # GAS 題庫靜默背景同步（須明確啟用雲端同步）
        if is_cloud_sync_enabled(self.config):
            _t = threading.Thread(target=self._update_db_from_gas, daemon=True, name="GAS-DB-Sync")
            _t.start()

    def _ensure_file_handler(self):
        """於執行緒正式啟動 run() 時開啟本輪專屬日誌檔。"""
        if getattr(self, "file_handler", None) is not None:
            return
        existing_fh = next(
            (h for h in self.log_instance.handlers if isinstance(h, logging.FileHandler)),
            None,
        )
        if existing_fh is not None:
            self.file_handler = existing_fh
            return
        try:
            fh = logging.FileHandler(self.log_file, mode="w", encoding="utf-8")
            fh.setFormatter(
                _PlainTextLogFormatter("%(asctime)s - %(levelname)s - %(message)s")
            )
            self.log_instance.addHandler(fh)
            self.file_handler = fh
        except OSError:
            self.file_handler = None

    def load_config(self, path):
        if path is None:
            path = str(user_data_path("config.json"))

        # 第一次建立設定檔
        if not os.path.exists(path):
            config_data = {
                "accounts": [],
                "settings": {
                    "headless": True,
                    "target_percentage": 1.05,
                    "residence_time": 75,
                },
                "blacklist": ["課程環境", "勘誤說明", "前言", "新手導覽", "課程簡介", "環境檢測"],
            }

            write_json_atomically(path, config_data)

        else:
            with open(path, "r", encoding="utf-8") as f:
                config_data = json.load(f)

        # ⭐ 關鍵：確保必要的設定存在（合併）
        if "settings" not in config_data:
            config_data["settings"] = {}

        # ⭐ 確保 blacklist 存在
        if "blacklist" not in config_data:
            config_data["blacklist"] = ["課程環境", "勘誤說明", "前言", "新手導覽", "課程簡介", "環境檢測"]

        # ⭐ 直接回傳完整配置
        return config_data

    def _start_keep_awake(self):
        """啟用防螢幕關閉：SetThreadExecutionState + 定時滑鼠微動備援"""
        # 1. Windows API：告訴系統目前有任務，不要關螢幕
        try:
            ES_CONTINUOUS = 0x80000000
            ES_DISPLAY_REQUIRED = 0x00000002
            ES_SYSTEM_REQUIRED = 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED
            )
            logger.info("🖥️ 防螢幕關閉已啟用（SetThreadExecutionState）")
        except Exception as e:
            logger.warning(f"防螢幕 API 呼叫失敗（將改用滑鼠微動備援）: {e}")

        # 2. 備援：每 60 秒微動滑鼠 1 pixel 再移回
        self._keep_awake_stop.clear()

        def _mouse_nudge():
            try:
                import ctypes as _ct

                pt = _ct.wintypes.POINT()
                while not self._keep_awake_stop.wait(60):
                    _ct.windll.user32.GetCursorPos(_ct.byref(pt))
                    _ct.windll.user32.SetCursorPos(pt.x + 1, pt.y)
                    time.sleep(0.1)
                    _ct.windll.user32.SetCursorPos(pt.x, pt.y)
            except Exception:
                pass

        self._keep_awake_thread = threading.Thread(
            target=_mouse_nudge, daemon=True, name="KeepAwake"
        )
        self._keep_awake_thread.start()

    def _stop_keep_awake(self):
        """停用防螢幕關閉，還原系統設定"""
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                0x80000000
            )  # ES_CONTINUOUS only
            logger.info("🖥️ 防螢幕關閉已停用，系統還原正常省電設定")
        except Exception:
            pass
        self._keep_awake_stop.set()

    def _close_driver_only(self):
        """僅關閉當前瀏覽器與受管 Driver 行程（供 Auto-Healing 與重啟使用，保留 running 與日誌管道）。"""
        if self.config.get("login_type") == "taipei_eda":
            try:
                from taipei_eda_course import force_close_active_driver
                force_close_active_driver()
            except Exception:
                pass
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        self._kill_managed_processes()

    def _cleanup(self):
        """統一清理入口，重複呼叫安全（atexit/signal/finally 都指向這裡）。"""
        self.running = False
        self._stop_keep_awake()
        self._close_driver_only()
        if getattr(self, "ui_handler", None):
            try:
                if getattr(self, "log_instance", None):
                    self.log_instance.removeHandler(self.ui_handler)
                logger.removeHandler(self.ui_handler)
                self.ui_handler = None
            except Exception:
                pass
        if getattr(self, "file_handler", None):
            try:
                if getattr(self, "log_instance", None):
                    self.log_instance.removeHandler(self.file_handler)
                self.file_handler.flush()
                self.file_handler.close()
                self.file_handler = None
            except Exception:
                pass

    def kill_orphan_drivers(self):
        """
        啟動前清理：只殺「孤立的 chromedriver」。
        判斷標準：行程名稱是 chromedriver，且它的父行程已經不存在 (或不是 Python 相關行程)。
        完全不碰使用者自己開的 chrome.exe。
        """
        my_pid = os.getpid()
        killed = []
        for proc in psutil.process_iter(["pid", "name", "ppid"]):
            try:
                name = (proc.info["name"] or "").lower()
                if "chromedriver" not in name:
                    continue
                
                ppid = proc.info["ppid"]
                parent_alive = False
                if ppid and ppid != my_pid:
                    try:
                        parent_proc = psutil.Process(ppid)
                        p_name = parent_proc.name().lower()
                        # 若父行程是 python、行政效能領航員或 pilot 且還活著，代表是另一個正在運行的多開實例
                        if "python" in p_name or "行政效能領航員" in p_name or "pilot" in p_name:
                            parent_alive = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        parent_alive = False

                # 若是本行程建立的，或父行程依然存活且為多開實例，則保留不予清理
                if ppid == my_pid or parent_alive:
                    continue

                # 連同它啟動的 chrome 子行程一起清掉
                for child in proc.children(recursive=True):
                    try:
                        child.kill()
                        killed.append(f"{child.name()}(PID {child.pid})")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                proc.kill()
                killed.append(f"{proc.name()}(PID {proc.pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if killed:
            logger.info(f"🧹 已清理殘留的背景 WebDriver 進程：{', '.join(killed)}")
            time.sleep(0.5)
        else:
            logger.info("✅ 無任何殘留的背景 Driver 進程。")

    def _kill_managed_processes(self):
        """結束時清理：只殺本次自己記錄的 PID 樹，不影響使用者其他 Chrome。"""
        if not self._managed_pids:
            return
        for pid in list(self._managed_pids):
            try:
                proc = psutil.Process(pid)
                for child in proc.children(recursive=True):
                    try:
                        child.kill()
                        logger.info(f"🧹 釋放背景子進程：{child.name()}(PID {child.pid})")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                proc.kill()
                logger.info(f"🧹 釋放背景主進程：{proc.name()}(PID {pid})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        self._managed_pids.clear()
        time.sleep(0.5)


    def safe_sleep(self, seconds):
        """⭐ 正確位置：在類內"""
        for _ in range(int(seconds)):
            if not self.running:
                logger.info("🛑 使用者手動停止")
                return False
            time.sleep(1)
        return True

    def run(self):
        """⭐ 正確位置：在類內"""
        tid = threading.get_ident()
        self._ensure_file_handler()
        ThreadBoundUILogHandler.register(tid, self)

        if self.config.get("login_type") == "taipei_eda":
            self._start_keep_awake()
            try:
                logger.info("🏫 啟動臺北E大平台流程...")
                from taipei_eda_course import run_taipei_eda

                ok = run_taipei_eda(
                    config_override=self.config,
                    should_continue=lambda: self.running,
                    log_callback=self.log_callback,
                    quiz_interactive_callback=self.quiz_interactive_callback,
                    course_state_callback=self.course_state_callback,
                )
                if ok:
                    logger.info("🏆 臺北E大所有任務完成！")
                else:
                    logger.warning("⚠️ 臺北E大流程未完整完成，請查看 taipei_eda_course.log")
            except ImportError as e:
                logger.error(f"❌ 臺北E大模組載入失敗，請確認依賴已安裝: {e}")
            except Exception as e:
                logger.error(f"⚠️ 臺北E大流程發生錯誤: {e}")
                logger.debug(traceback.format_exc())
            finally:
                ThreadBoundUILogHandler.unregister(tid)
                self._cleanup()
            return

        self._start_keep_awake()
        print(
            f"\n{Fore.CYAN}{'=' * 60}\n【行政效能領航員 - 數位研習輔助方案 {self.version}】\n{'=' * 60}{Style.RESET_ALL}"
        )
        # AI API 狀態提示
        provider = self.config.get("ai_provider", "OpenAI")
        ai_keys = self.config.get("ai_keys", {})
        ai_key = ai_keys.get(provider) or self.config.get("ai_api_key", "")
        if ai_key:
            base_url = self.config.get("ai_base_url", "https://api.openai.com/v1")
            model = self.config.get("ai_model", "gpt-4o-mini")
            if provider == "Gemini" and any(v in model for v in ("gemini-2.0", "gemini-1.5", "gemini-2.5", "gemini-3.1-flash-lite")):
                model = "gemini-3.5-flash-lite"
            logger.info(f"🤖 AI 補答已啟用（model: {model}，endpoint: {base_url}）")
        else:
            logger.info("📖 AI 補答未啟用，僅使用本地題庫作答")
        try:
            can_prompt_stdin = (
                not getattr(self, "log_callback", None)
                and sys.stdin is not None
                and hasattr(sys.stdin, "isatty")
                and sys.stdin.isatty()
            )
            if not self.init_engine():
                if can_prompt_stdin:
                    input(
                        f"\n{Fore.RED}❌ 引擎啟動失敗，請檢查驅動程式後按 Enter 退出...{Style.RESET_ALL}"
                    )
                return

            if not self.login():
                login_type = self.config.get("login_type", "ecpa")
                if login_type == "egov":
                    msg = "❌ 登入失敗！請確認『我的E政府』帳密正確，或是否出現驗證碼／伺服器逾時。"
                else:
                    msg = "❌ 登入失敗！請確認 eCPA 帳密正確且無驗證碼要求。"
                logger.error(msg)
                if can_prompt_stdin:
                    input(f"\n{Fore.RED}{msg} 按 Enter 退出...{Style.RESET_ALL}")
                return

            empty_api_count = 0

            while self.running:
                try:
                    cur_y = time.strftime("%Y")
                    try:
                        courses = self.fetch_course_list_checked(cur_y)
                    except Exception as e:
                        logger.error(f"無法讀取列表，重試中... ({e})")
                        alert_text = self._accept_alert_if_present()
                        if self._is_logout_text(f"{alert_text} {e}"):
                            if self.recover_login_session("API 查詢時偵測到登出"):
                                continue
                            break
                        for _ in range(10):
                            if not self.running:  # ⭐ 重試時也檢查
                                logger.info("🛑 使用者手動停止")
                                break
                            time.sleep(1)
                        if not self.running:
                            break
                        continue

                    # ⭐ 檢查點（取得課程後）
                    if not self.running:
                        logger.info("🛑 已收到停止指令（取得課程後）")
                        break

                    logger.info(f"📋 API 回傳課程總數：{len(courses)} 筆")

                    # e等公務園報名組裝課程時會自動加入旗下子課程。
                    # 正常流程直接使用 API 清單，不再重複掃描母課程或再次報名子課程。

                    # API 回 0 筆通常是被登出或 cookie 失效，不可無限等待。
                    if len(courses) == 0:
                        empty_api_count += 1
                        logger.warning("⚠️ API 回傳 0 筆，先重新同步 session 後重查...")
                        self.sync_session()
                        time.sleep(3)
                        try:
                            courses = self.fetch_course_list(cur_y)
                        except Exception as e:
                            logger.error(f"重查失敗: {e}")
                            courses = []
                        logger.info(f"📋 重查後課程總數：{len(courses)} 筆")

                        if len(courses) == 0:
                            if not self.recover_login_session("API 連續回傳 0 筆，判定 session 可能已失效"):
                                break
                            try:
                                courses = self.fetch_course_list(cur_y)
                            except Exception as e:
                                logger.error(f"重新登入後重查失敗: {e}")
                                courses = []
                            logger.info(f"📋 重新登入後課程總數：{len(courses)} 筆")

                        if len(courses) == 0:
                            if empty_api_count >= 3:
                                logger.warning("🚀 API 連續 0 筆無法恢復，重啟輔助引擎後再試。")
                                self._close_driver_only()
                                if not self.safe_sleep(5):
                                    break
                                if not self.init_engine() or not self.login():
                                    logger.error("❌ 引擎重啟或登入失敗，無法繼續。")
                                    break
                                empty_api_count = 0
                            else:
                                for _ in range(10):
                                    if not self.running:
                                        break
                                    time.sleep(1)
                            continue

                    empty_api_count = 0

                    pending = [
                        c
                        for c in courses
                        if self._is_open_course(c)
                        and self._is_playable_course(c)
                        and not self._is_course_completed(c)
                        and to_sec(c.get("rss", "00:00:00"))
                        < to_sec(c.get("criteria_content_hour", "00:00:00"))
                        * self.config.get("target_percentage", 1.0)
                        # 本次 session 已永久跳過（如「非本門課」）的課程
                        and str(c.get("course_id", "")) not in self._completed_in_session
                    ]
                    if pending:
                        logger.info(
                            f"⏳ 待上課程 {len(pending)} 筆："
                            + "、".join(c.get("caption", "?")[:15] for c in pending[:5])
                            + ("..." if len(pending) > 5 else "")
                        )

                    # 時數已達標 且 考試未通過 或 問卷未填 的課程
                    def _needs_exam_or_questionnaire(c):
                        c_id = str(c.get("course_id", ""))
                        if not self._is_open_course(c) or not self._is_playable_course(c):
                            return False
                        # 若平臺或資料已全數修畢，直接略過
                        if self._is_course_completed(c):
                            return False
                        # 本次已成功處理過，跳過
                        if c_id in self._completed_in_session:
                            return False
                        # 本次曾無法開啟測驗的課程，不重複卡住；最後會明確列為待處理。
                        if c_id in self._exam_manual_review:
                            return False
                        # AI 服務中斷後的冷卻期間先不重考
                        if getattr(self, "_exam_retry_after", {}).get(c_id, 0) > time.time():
                            return False
                        hours_done = to_sec(c.get("rss", "00:00:00")) >= to_sec(
                            c.get("criteria_content_hour", "00:00:00")
                        )
                        if not hours_done:
                            return False
                        # 考試未通過（且未達 3 次不及格上限）
                        exam_passed = self._is_exam_passed(c)
                        needs_exam = (not exam_passed) and (self._exam_fail_counts.get(c_id, 0) < MAX_QUIZ_ATTEMPTS)
                        # 問卷未填（fill=="0" 且 write_questionnaire 非空）
                        needs_questionnaire = (str(c.get("fill", "0")) == "0") and bool(c.get("write_questionnaire", ""))
                        if self.config.get("skip_exam_for_session", False):
                            return needs_questionnaire
                        return needs_exam or needs_questionnaire

                    completed_hours = [
                        c for c in courses if _needs_exam_or_questionnaire(c)
                    ]

                    if not pending and not completed_hours:
                        break

                    def _emit_course_state(c, st, rsn="", nxt="", is_comp=False, needs_man=False, score=None):
                        if getattr(self, "course_state_callback", None):
                            try:
                                from models.course_state import CourseState
                                cur_s = c.get("rss", "00:00:00")
                                req_s = c.get("criteria_content_hour", "00:00:00")
                                cur_sec = to_sec(cur_s)
                                req_sec = max(1, to_sec(req_s))
                                pct = min(100.0, round((cur_sec / req_sec) * 100, 1))
                                if is_comp:
                                    pct = 100.0
                                c_state = CourseState(
                                    course_id=str(c.get("course_id", "")),
                                    course_name=c.get("caption", ""),
                                    platform="egov",
                                    status=st,
                                    progress_pct=pct,
                                    current_time_str=cur_s,
                                    required_time_str=req_s,
                                    exam_score=score or c.get("exam_score"),
                                    pass_score=c.get("criteria_exam_score", 60),
                                    reason=rsn,
                                    next_step=nxt,
                                    is_completed=is_comp,
                                    needs_manual=needs_man,
                                )
                                self.course_state_callback(c_state)
                            except Exception:
                                pass

                    # ── 第一步：先對時數已達標但考試/問卷未完成的課程執行 ──
                    # （初始使用者全部 pending 時，completed_hours 為空，此段直接跳過）
                    all_exam_done = True
                    if completed_hours:
                        all_exam_done = True
                        for c in completed_hours:
                            if not self.running:
                                break
                            from models.course_state import CourseStatus
                            _emit_course_state(c, CourseStatus.QUIZ, "時數已達標，正在執行測驗或問卷確認", "準備進入教室開始測驗或填寫問卷")
                            logger.info(
                                f"📝 對已達標課程執行考試/問卷：{c.get('caption', '')}"
                            )
                            # 導航到學習統計頁，再進入課程教室
                            self.driver.get(self.stat_url)
                            if not self.safe_sleep(3):
                                break
                            c_id = str(c.get("course_id", ""))
                            try:
                                self.driver.execute_script(
                                    f"gotoCourse({c['course_id']})"
                                )
                                if not self.safe_sleep(5):
                                    break
                                
                                # 💡 檢查是否有 alert 彈窗 (例如「課程尚未上架，無法進入教室介面」)
                                alert_text = self._accept_alert_if_present()
                                if alert_text:
                                    logger.warning(f"   ⚠️ 進入教室時偵測到彈窗訊息: {alert_text}")
                                    if any(
                                        word in alert_text
                                        for word in [
                                            "尚未上架",
                                            "無法進入",
                                            "已下架",
                                            "直播已結束",
                                            "未開放",
                                            "非上課期間",
                                            "非開放期間",
                                            "無法上課",
                                        ]
                                    ):
                                        logger.warning(
                                            f"   ⚠️ 課程「{c.get('caption', '')}」尚未上架、已下架或非上課期間，將在本工作階段永久跳過"
                                        )
                                        self._completed_in_session.add(c_id)
                                        continue

                                # 若停留在 /info/ 介紹頁，先檢查是否平臺已標註修畢/通過，或已下架／非開課期間
                                if "/info/" in self.driver.current_url:
                                    if self._is_course_already_completed_on_info_page():
                                        logger.info(
                                            f"   🎉 課程「{c.get('caption', '')}」平臺顯示已全數修畢（已通過），免重複執行。"
                                        )
                                        self._completed_in_session.add(c_id)
                                        continue
                                    unavail_reason = self._detect_unavailable_course_on_info_page()
                                    if unavail_reason:
                                        self._record_unavailable_course(c, unavail_reason)
                                        _emit_course_state(c, CourseStatus.SKIPPED, unavail_reason, "平臺已下架或非開課期間，本輪自動略過", is_comp=False)
                                        continue

                                # 點「開始上課」/「進入課程」/「上課去」按鈕（如有）
                                try:
                                    clicked_entry = self._click_course_entry(include_exam=True)
                                    if clicked_entry:
                                        logger.info(f"   📝 已點擊「{clicked_entry}」進入教室/測驗介面")
                                    if not self.safe_sleep(5):
                                        break
                                    classroom_h = self.find_classroom_window()
                                    if classroom_h:
                                        self.driver.switch_to.window(classroom_h)
                                        self._auto_hide_popups_if_needed(settle=True)
                                    elif len(self.driver.window_handles) > 1:
                                        self.driver.switch_to.window(self.driver.window_handles[-1])
                                        self._auto_hide_popups_if_needed(settle=True)
                                except Exception:
                                    pass
                                logger.info(
                                    f"   📝 目前頁面 URL: {self.driver.current_url}"
                                )
                                # 💡 若當前依然停留在 /info/ 介紹頁（未能進入教室），先辨識是否下架再決定待查核
                                if "/info/" in self.driver.current_url:
                                    unavail_reason = self._detect_unavailable_course_on_info_page()
                                    if unavail_reason:
                                        self._record_unavailable_course(c, unavail_reason)
                                        _emit_course_state(c, CourseStatus.SKIPPED, unavail_reason, "平臺已下架或非開課期間，本輪自動略過", is_comp=False)
                                        continue
                                    logger.warning(
                                        f"   ⚠️ 課程「{c.get('caption', '')}」尚未載入教室介面（仍在介紹頁），暫緩本次測驗。"
                                    )
                                    self._mark_exam_manual_review(c, "未能進入教室介面（停留在介紹頁）")
                                    continue
                            except Exception as e:
                                logger.debug(f"導航課程失敗: {e}")

                            if self.config.get("skip_exam_for_session", False):
                                logger.warning("本次已選擇跳過測驗；時數已達標，改為嘗試填寫問卷。")
                                q_ok = True
                                if self.running and str(c.get("fill", "0")) != "1":
                                    q_ok = self.auto_questionnaire(c)
                                else:
                                    logger.info(f"   ✅ 「{c.get('caption', '')}」問卷先前已完成，跳過填寫。")
                                if q_ok:
                                    self._completed_in_session.add(c_id)
                                    self._mark_exam_manual_review(c, "本次跳過測驗，尚未確認完課")
                                    from models.course_state import CourseStatus
                                    _emit_course_state(c, CourseStatus.SKIPPED, "使用者選擇本次跳過測驗（問卷已完成）", "課程已完成時數與問卷，後續補測即可完課", is_comp=False)
                                    try:
                                        from utils.security import global_quota_tracker
                                        from utils.course_dashboard import render_course_completion_card
                                        api_after = global_quota_tracker.get_stats().get("used", 0)
                                        card = render_course_completion_card(
                                            course_name=c.get('caption', ''),
                                            has_quiz=True,
                                            quiz_passed=False,
                                            survey_completed=True,
                                            course_completed=False,
                                            solve_mode="skipped",
                                            course_api_calls=0,
                                            today_api_calls=api_after,
                                            daily_limit=global_quota_tracker.daily_limit,
                                            session_completed=self._session_completed_count,
                                            session_quiz_passed=getattr(self, "_session_quiz_passed_count", getattr(self, "_session_passed_count", 0)),
                                            session_quiz_total=getattr(self, "_session_quiz_total_count", self._session_completed_count),
                                        )
                                        logger.info("\n" + card)
                                    except Exception as e:
                                        logger.warning(f"⚠️ 課程結案摘要產生失敗，不影響課程完成流程：{e}")
                                else:
                                    self._mark_exam_manual_review(c, "問卷填寫失敗，尚未確認完成")
                                    from models.course_state import CourseStatus
                                    _emit_course_state(c, CourseStatus.MANUAL_REVIEW, "問卷填寫失敗，尚未確認完成", "請手動前往網站填寫問卷", needs_man=True)
                                continue

                            self._count_session_quiz_course(c_id)
                            passed = self.auto_exam(c)
                            if passed and self.running:
                                q_ok = True
                                if str(c.get("fill", "0")) != "1":
                                    q_ok = self.auto_questionnaire(c)
                                else:
                                    logger.info(f"   ✅ 「{c.get('caption', '')}」問卷先前已完成，跳過填寫。")
                                if q_ok:
                                    self._completed_in_session.add(c_id)
                                    self._session_completed_count = getattr(self, "_session_completed_count", 0) + 1
                                    self._session_passed_count = getattr(self, "_session_passed_count", 0) + 1
                                    self._session_quiz_passed_count = getattr(self, "_session_quiz_passed_count", 0) + 1
                                    from models.course_state import CourseStatus
                                    _emit_course_state(c, CourseStatus.COMPLETED, "時數達標且測驗及格，問卷已送出", "已完課，接續下一門", is_comp=True)
                                    try:
                                        from utils.security import global_quota_tracker
                                        from utils.course_dashboard import render_course_completion_card
                                        api_after = global_quota_tracker.get_stats().get("used", 0)
                                        course_api = self._course_api_calls.get(c_id, 0)
                                        s_mode = "ai" if course_api > 0 else "quiz_bank"
                                        card = render_course_completion_card(
                                            course_name=c.get('caption', ''),
                                            has_quiz=True,
                                            quiz_passed=True,
                                            survey_completed=True,
                                            course_completed=True,
                                            solve_mode=s_mode,
                                            course_api_calls=course_api,
                                            today_api_calls=api_after,
                                            daily_limit=global_quota_tracker.daily_limit,
                                            session_completed=self._session_completed_count,
                                            session_quiz_passed=self._session_quiz_passed_count,
                                            session_quiz_total=getattr(self, "_session_quiz_total_count", self._session_completed_count),
                                        )
                                        logger.info("\n" + card)
                                    except Exception as e:
                                        logger.warning(f"⚠️ 課程結案摘要產生失敗，不影響課程完成流程：{e}")

                                else:
                                    self._mark_exam_manual_review(c, "問卷填寫失敗，尚未確認完成")
                                    from models.course_state import CourseStatus
                                    _emit_course_state(c, CourseStatus.MANUAL_REVIEW, "問卷填寫失敗，尚未確認完成", "請手動前往網站填寫問卷", needs_man=True)
                            elif not passed:
                                if c_id in self._exam_manual_review:
                                    _emit_course_state(c, CourseStatus.MANUAL_REVIEW, self._exam_manual_review[c_id]["reason"], "請確認平臺紀錄或保留的草稿", needs_man=True)
                                    continue
                                if self._defer_exam_after_ai_outage(c):
                                    from models.course_state import CourseStatus
                                    _emit_course_state(c, CourseStatus.QUIZ, "AI 服務暫時無法回應，本次不及格不計入上限", f"{EXAM_AI_OUTAGE_DEFER_SECONDS // 60} 分鐘後自動重考")
                                    continue
                                # 若不及格次數未達上限，跳回迴圈頂部繼續重考
                                if self._exam_fail_counts.get(c_id, 0) < MAX_QUIZ_ATTEMPTS:
                                    all_exam_done = False
                                    from models.course_state import CourseStatus
                                    fail_cnt = self._exam_fail_counts.get(c_id, 0)
                                    _emit_course_state(c, CourseStatus.QUIZ, f"測驗未達及格標準（已嘗試 {fail_cnt}/3 次）", "準備重新進入測驗補考")
                                    break
                                else:
                                    # 已達 3 次不及格上限，列為待人工處理清單，本次不再重試
                                    self._mark_exam_manual_review(c, "測驗連續不及格已達 3 次上限")
                                    self._completed_in_session.add(c_id)
                                    from models.course_state import CourseStatus
                                    _emit_course_state(c, CourseStatus.MANUAL_REVIEW, "測驗連續不及格已達 3 次上限", "請至平台手動查看題目或題庫解析", needs_man=True)
                                    try:
                                        from utils.security import global_quota_tracker
                                        from utils.course_dashboard import render_course_completion_card
                                        api_after = global_quota_tracker.get_stats().get("used", 0)
                                        course_api = self._course_api_calls.get(c_id, 0)
                                        s_mode = "ai" if course_api > 0 else "manual"
                                        card = render_course_completion_card(
                                            course_name=c.get('caption', ''),
                                            has_quiz=True,
                                            quiz_passed=False,
                                            survey_completed=False,
                                            course_completed=False,
                                            solve_mode=s_mode,
                                            course_api_calls=course_api,
                                            today_api_calls=api_after,
                                            daily_limit=global_quota_tracker.daily_limit,
                                            session_completed=self._session_completed_count,
                                            session_quiz_passed=getattr(self, "_session_quiz_passed_count", getattr(self, "_session_passed_count", 0)),
                                            session_quiz_total=getattr(self, "_session_quiz_total_count", self._session_completed_count),
                                        )
                                        logger.info("\n" + card)
                                    except Exception as e:
                                        logger.warning(f"⚠️ 課程結案摘要產生失敗，不影響課程完成流程：{e}")



                        if not self.running:
                            break

                        # 若全部達標課程都處理完，且無 pending，則全部完成
                        if all_exam_done and not pending:
                            break

                        # 💡 主動定期 Session 保養：每連續研習/處理滿指定時數，在批次結算後自動刷新 Cookie 與 Session
                        refresh_hours = float(self.config.get("session_refresh_hours", 5.0))
                        if (
                            self.running
                            and refresh_hours > 0
                            and (time.time() - self._last_session_refresh_time) >= (refresh_hours * 3600)
                        ):
                            self._proactive_session_refresh()

                    # ── 第二步：處理時數未達標的課程（上課）──
                    # 若有考試還在重試中（all_exam_done=False），優先重考，不去上課
                    if pending and all_exam_done:
                        self.total_courses = len(pending) + (self.current_idx)
                        self.current_idx += 1
                        from models.course_state import CourseStatus
                        _emit_course_state(pending[0], CourseStatus.LEARNING, "時數尚未達標，正在進入教室累積時數", "觀看教材並保持連線直到時數達標")
                        res = self.study_process(pending[0])

                        if res == "STOP":
                            logger.info("🛑 使用者已停止程式")
                            break

                        if res == "LOGGED_OUT":
                            c_id = str(pending[0].get("course_id", ""))
                            logout_counts = self.__dict__.setdefault("_course_logout_counts", {})
                            logout_counts[c_id] = logout_counts.get(c_id, 0) + 1
                            if logout_counts[c_id] > 3:
                                reason = "同一門課研習中反覆被平臺登出"
                                logger.warning(f"⚠️ 課程「{pending[0].get('caption', c_id)}」{reason}，自動略過以避免無限循環。")
                                self._mark_exam_manual_review(pending[0], reason)
                                self._completed_in_session.add(c_id)
                                from models.course_state import CourseStatus
                                _emit_course_state(pending[0], CourseStatus.MANUAL_REVIEW, reason, "請確認帳號登入狀態後再重新執行", needs_man=True)
                                continue
                            if not self.recover_login_session("研習期間被平臺登出（閒置逾時）"):
                                break
                            logger.info("🔄 已重新登入，重試當前課程...")
                            self.current_idx -= 1
                            continue

                        if res == "RELOGIN":
                            c_id = str(pending[0].get("course_id", ""))
                            self._course_relogin_counts[c_id] = self._course_relogin_counts.get(c_id, 0) + 1
                            if self._course_relogin_counts[c_id] >= 2:
                                logger.warning(
                                    f"⚠️ 課程「{pending[0].get('caption', c_id)}」連續觸發重新登入異常（平臺跳轉或頁面失效），自動略過以避免無限循環。"
                                )
                                self._mark_exam_manual_review(pending[0], "連續觸發重登異常（平臺頁面跳轉失敗）")
                                self._completed_in_session.add(c_id)
                                from models.course_state import CourseStatus
                                _emit_course_state(pending[0], CourseStatus.MANUAL_REVIEW, "連續觸發重登異常（平臺頁面跳轉失敗）", "請檢查登入狀態與課程頁面權限", needs_man=True)
                                continue
                            # 閒置登出後已重新登入，重試當前課程（退回 index）
                            logger.info("🔄 重新進入教室，重試當前課程...")
                            self.sync_session()  # 確保 http_session 用最新 cookie
                            self.current_idx -= 1
                            continue

                        if res == "DRIVER_LOST":
                            if not self._try_auto_healing("瀏覽器視窗已關閉或連線中斷"):
                                break
                            self.current_idx -= 1
                            continue
                        if res == "STALLED":
                            logger.warning("🚀 偵測到停滯，正在重新啟動輔助引擎...")
                            self._close_driver_only()
                            if not self.safe_sleep(5):
                                break
                            if not self.init_engine() or not self.login():
                                logger.error("❌ 引擎重啟或登入失敗，無法繼續。")
                                break
                            self.current_idx -= 1
                        elif res == "SKIP":
                            # 永久性無法上課（如「您非本門課的學生」），排除此課程
                            c_id = str(pending[0].get("course_id", ""))
                            if c_id:
                                self._completed_in_session.add(c_id)
                            from models.course_state import CourseStatus
                            _emit_course_state(pending[0], CourseStatus.SKIPPED, "無法上課或非本門課學生", "本輪永久略過", is_comp=False)
                            logger.info("⏭️ 已永久跳過課程，繼續下一門...")
                        elif res == "ERROR":
                            logger.info("⏳ 發生研習異常，稍後嘗試下一門課程...")
                            from models.course_state import CourseStatus
                            _emit_course_state(pending[0], CourseStatus.ERROR, "研習過程中遭遇例外", "將在下一輪或稍後重試", is_comp=False)
                            time.sleep(5)
                        elif res == "SUCCESS":
                            from models.course_state import CourseStatus
                            _emit_course_state(
                                pending[0],
                                CourseStatus.COMPLETED,
                                "研習流程已完成",
                                "已完成本課程，接續下一門",
                                is_comp=True,
                            )

                        # 💡 主動定期 Session 保養：每連續研習滿指定時數（預設 5 小時），在課程結算後自動刷新 Cookie 與 Session
                        refresh_hours = float(self.config.get("session_refresh_hours", 5.0))
                        if (
                            self.running
                            and refresh_hours > 0
                            and (time.time() - self._last_session_refresh_time) >= (refresh_hours * 3600)
                        ):
                            self._proactive_session_refresh()

                except Exception as e:
                    logger.error(f"⚠️ 核心迴圈發生錯誤: {e}")
                    # 偵測 WebDriver session 失效或視窗被關閉（Chrome crash / no such window / HTTPConnectionPool）
                    err_str = str(e)
                    if _is_driver_disconnect_error(err_str):
                        if not self._try_auto_healing(err_str):
                            break
                        continue
                    else:
                        self.safe_sleep(10)

            unavailable = self.__dict__.get("_unavailable_in_session") or {}
            if unavailable:
                unavail_previews = "、".join(
                    f"{item['caption'][:18]}（{item['reason']}）"
                    for item in unavailable.values()
                )
                logger.info(
                    f"ℹ️ 本次略過 {len(unavailable)} 門平臺已下架／非開課期間課程：{unavail_previews}"
                )

            if self._exam_manual_review:
                previews = "、".join(
                    f"{item['caption'][:18]}（{item['reason']}）"
                    for item in self._exam_manual_review.values()
                )
                logger.warning(
                    f"⚠️ 本次尚有 {len(self._exam_manual_review)} 門課程測驗待處理：{previews}；"
                    "不宣告所有任務完成。"
                )
            else:
                logger.info(f"🏆 {Fore.GREEN}所有任務圓滿達成！{Style.RESET_ALL}")
            if sys.stdin:
                input(f"\n{Fore.GREEN}✓ 程式執行完畢，按 Enter 關閉。{Style.RESET_ALL}")

        except KeyboardInterrupt:
            print(
                f"\n{Fore.YELLOW}⚠️ 使用者中斷（Ctrl+C），正在安全退出...{Style.RESET_ALL}"
            )

        except Exception as e:
            logger.critical(f"🔥 程式發生致命錯誤: {e}")
            if sys.stdin:
                input(
                    f"\n{Fore.RED}❌ 發生嚴重錯誤，請查看 debug.log 並按 Enter 退出...{Style.RESET_ALL}"
                )
        finally:
            ThreadBoundUILogHandler.unregister(tid)
            self._cleanup()


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="行政效能領航員 自動化工具")
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="強制以 headless（背景）模式執行，不顯示瀏覽器視窗",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="強制以有視窗模式執行（可覆蓋 config.json 設定）",
    )
    # 讓 argparse 只解析已知參數，避免因其他 argv 而報錯
    args, _ = parser.parse_known_args()

    override = {}
    # 只有明確傳入 --headless 或 --no-headless 時才覆蓋 config.json
    if "--headless" in sys.argv:
        override["headless"] = True
    elif "--no-headless" in sys.argv:
        override["headless"] = False

    AdminEfficiencyPilot(config_override=override if override else None).run()
