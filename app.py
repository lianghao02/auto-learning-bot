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
from utils.config_io import get_db_connection, write_json_atomically
from utils.app_paths import app_dir, ensure_seeded_database, log_path, user_data_path

# 強制 stdout/stderr 使用 UTF-8，避免在 cp950 環境下因 emoji 崩潰
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

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
)
from utils.security import validate_ai_base_url
from utils.webdriver_mgr import download_best_chromedriver

GLOBAL_DB_LOCK = threading.Lock()

# 降低 Selenium 自身的冗長日誌
logging.getLogger("selenium").setLevel(logging.ERROR)
logger = get_logger()


def _normalize_q(text: str) -> str:
    """題目正規化：小寫、去空白、只保留中文/英數字。
    用於 _answer_map 的 key 和 difflib fuzzy 比對。
    """
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    # 只保留中文字、英文字母、數字（去掉標點、空白、特殊符號）
    text = re.sub(r"[^\w\u4e00-\u9fff\u3400-\u4dbf]", "", text)
    return text


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
        if pilot and pilot.ui_handler:
            pilot.ui_handler.emit(record)


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


class AdminEfficiencyPilot:
    VERSION = _read_local_version()
    CHANGELOG = (
        "V3.2.0 Gemini 2.0 Flash 批次極速作答與跳過測驗自動補填問卷\n"
        "• Google Gemini 2.0 Flash 批次極速作答引擎：10 題合一發送，1 秒內 JSON 結構化解析並自動寫入本機 SQLite 題庫\n"
        "• 人機協同助理彈窗升級：新增「✨ Gemini 1 秒智慧作答」專屬按鈕，開啟時自動將 Prompt 複製至剪貼簿\n"
        "• 跳過測驗自動補填問卷機制：跳過測驗後自動檢查並完成滿意度問卷提交，完課進度零遺漏\n"
        "• 免費額度滑動窗口安全限速器（5 RPM）與 API Key 日誌遮罩脫敏防護\n"
        "• 延續 V3.1.1 的動態及格門檻多重判定與 V3.1.0 的 5 小時主動定期 Session 保養機制"
    )


    def __init__(
        self,
        config_path=None,
        log_callback=None,
        config_override=None,
        progress_callback=None,
        quiz_interactive_callback=None,
    ):
        self.progress_callback = progress_callback
        self.quiz_interactive_callback = quiz_interactive_callback
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
            fallback_path = os.path.join(base_dir, "answer.json")
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
        self._completed_in_session = (
            set()
        )  # course_id → 本次已成功處理（考試通過+問卷完成）
        self._exam_manual_review = {}  # course_id → 無法開啟測驗，待下次重新嘗試或人工確認
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

        # 初始化日誌檔案 (每次覆蓋)
        self.log_file = str(log_path(f"debug_{self.config.get('login_type', 'default')}.log"))

        if not any(isinstance(h, logging.FileHandler) for h in self.log_instance.handlers):
            fh = logging.FileHandler(self.log_file, mode="w", encoding="utf-8")
            fh.setFormatter(
                logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            )
            self.log_instance.addHandler(fh)

        # 無論怎麼結束（Ctrl+C、關視窗、正常結束）都會清理
        atexit.register(self._cleanup)
        signal.signal(signal.SIGTERM, lambda *_: self._cleanup())
        try:
            signal.signal(
                signal.SIGBREAK, lambda *_: self._cleanup()
            )  # Windows Ctrl+Break
        except (AttributeError, OSError):
            pass

        # GAS 題庫靜默背景同步（啟動時）
        _t = threading.Thread(target=self._update_db_from_gas, daemon=True, name="GAS-DB-Sync")
        _t.start()

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

    def _cleanup(self):
        """統一清理入口，重複呼叫安全（atexit/signal/finally 都指向這裡）。"""
        self.running = False
        self._stop_keep_awake()
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
        if getattr(self, "ui_handler", None):
            try:
                logger.removeHandler(self.ui_handler)
                self.ui_handler = None
            except Exception:
                pass
        self._kill_managed_processes()

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

    @staticmethod
    def _clean_answer(ans: str) -> str:
        """去除答案的數字前綴（如 '2.唾液' → '唾液'）及 || 後綴"""
        import re as _re

        # 去除 '1.', '2. ', '3、' 等數字前綴（保留純數字答案如 '0.74'）
        ans = _re.sub(r"^\d+[.\uff0e\u3001]\s*(?=[^\d])", "", ans).strip()
        # 去除 '||' 後綴（標注符號）
        ans = _re.sub(r"\s*\|\|.*$", "", ans).strip()
        return ans

    def _find_answer(self, question_text):
        """在題庫中查詢答案。

        策略（依優先順序）：
        1. normalize 後精準比對 _answer_map
        2. difflib fuzzy 比對（cutoff=0.82）
        3. 都找不到 → None

        回傳 str（答案文字）或 None。
        """
        if not question_text or len(question_text.strip()) < 4:
            return None
        q_norm = _normalize_q(question_text.strip())
        if not q_norm or len(q_norm) < 4:
            return None

        # 1. 精準比對
        row = self._answer_map.get(q_norm)
        if row:
            return self._clean_answer(row["answer"])

        # 2. difflib fuzzy（只在有 key list 時執行，避免空集合 warning）
        if self._answer_keys:
            matches = get_close_matches(q_norm, self._answer_keys, n=1, cutoff=0.82)
            if matches:
                row = self._answer_map[matches[0]]
                logger.debug(f"   🔍 fuzzy match: {row['question'][:30]!r}")
                return self._clean_answer(row["answer"])

        # 3. 向後相容：舊 self.answers list 雙向包含比對（只在未從 DB 載入時有資料）
        if self.answers:
            q = question_text.strip()
            MIN_LEN = 12
            for keyword, ans in self.answers:
                if keyword in q:
                    if len(keyword) >= MIN_LEN and len(q) >= MIN_LEN:
                        return self._clean_answer(ans)
                elif q in keyword:
                    if len(q) >= MIN_LEN:
                        return self._clean_answer(ans)

        return None

    def _ai_find_answer(self, question_text: str, option_texts: list):
        """題庫找不到答案時，呼叫 AI API 協助選答。
        支援 OpenAI / Gemini / Groq（Bearer）及 Claude（x-api-key）。
        自動 fallback：先用便宜模型，失敗再升級。
        """
        # 各服務的 fallback 鏈（便宜 → 貴）
        _FALLBACK = {
            "OpenAI": ["gpt-4o-mini", "gpt-4o"],
            "Gemini": ["gemini-3.1-flash-lite", "gemini-3.5-flash"],
            "Claude": ["claude-haiku-4-5", "claude-sonnet-4-6"],
            "Groq":   ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"],
        }

        provider = self.config.get("ai_provider", "Gemini")
        ai_keys  = self.config.get("ai_keys", {})
        api_key  = ai_keys.get(provider) or self.config.get("ai_api_key", "")
        if not api_key or not option_texts:
            return None
        try:
            base_url = validate_ai_base_url(
                provider,
                self.config.get("ai_base_url", "https://generativelanguage.googleapis.com/v1beta/openai"),
            )
        except ValueError as exc:
            self.logger.error(f"❌ AI API 網址遭安全規則拒絕：{exc}")
            return None

        # 使用者設定的模型優先；若為已廢棄之舊版模型自動無痛升級
        configured_model = self.config.get("ai_model", "gemini-3.1-flash-lite")
        if provider == "Gemini" and ("gemini-2.0" in configured_model or "gemini-1.5" in configured_model or "gemini-2.5" in configured_model):
            configured_model = "gemini-3.1-flash-lite"

        chain = _FALLBACK.get(provider, [configured_model])
        # 從使用者設定的模型開始，忽略前面更便宜的（尊重使用者選擇）
        if configured_model in chain:
            chain = chain[chain.index(configured_model):]
        else:
            chain = [configured_model] + chain


        cleaned_options = [
            str(opt).strip() if str(opt).strip() else f"選項{i + 1}"
            for i, opt in enumerate(option_texts)
        ]
        options_str = "\n".join(
            [f"{i + 1}. {opt}" for i, opt in enumerate(cleaned_options)]
        )
        prompt = (
            "你是考試作答助手。請從以下選項中選出正確答案。\n"
            "務必只回覆一個選項編號，例如 1、2、3、4。\n"
            "不要回覆選項文字，不要解釋，不要加前後綴。\n\n"
            f"題目：{question_text}\n\n"
            f"選項：\n{options_str}\n\n"
            "正確答案選項編號："
        )

        # 若本階段已經觸發過 429 熔斷，直接秒級返回 None（使用本地題庫速答）
        if getattr(self, "_ai_circuit_broken", False):
            return None

        for model in chain:
            try:
                if provider == "Claude":
                    resp = requests.post(
                        f"{base_url}/messages",
                        headers={
                            "x-api-key":         api_key,
                            "anthropic-version": "2023-06-01",
                            "Content-Type":      "application/json",
                        },
                        json={
                            "model":    model,
                            "max_tokens": 150,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                        timeout=20,
                    )
                else:
                    resp = requests.post(
                        f"{base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type":  "application/json",
                        },
                        json={
                            "model":       model,
                            "messages":    [{"role": "user", "content": prompt}],
                            "max_tokens":  150,
                            "temperature": 0,
                        },
                        timeout=20,
                    )

                # 🛡️ 429 配額耗盡：開啟熔斷機制，當次執行階段不再重試，自動降級為純本地題庫速答
                if resp.status_code == 429:
                    if not getattr(self, "_ai_circuit_broken", False):
                        self._ai_circuit_broken = True
                        self.logger.warning(
                            "⚠️ 偵測到 Gemini API 超出限額 (429)，本工作階段自動暫停 AI 呼叫，切換為『純本地 2503 題庫速答』模式"
                        )
                    return None

                if resp.status_code in (500, 502, 503, 504):
                    logger.debug(f"   ⚠️ AI [{model}] 回傳 {resp.status_code}，嘗試下一個模型")
                    continue

                resp.raise_for_status()

                if provider == "Claude":
                    answer = resp.json()["content"][0]["text"].strip()
                else:
                    answer = resp.json()["choices"][0]["message"]["content"].strip()

                logger.info(f"   🤖 AI 補充答案（{model}）：{answer!r}")
                return answer

            except Exception as e:
                logger.warning(f"   ⚠️ AI [{model}] 呼叫失敗: {e}")
                continue

        logger.warning("   ⚠️ 所有 AI 模型均失敗，放棄補答")
        return None

    def _save_answers_to_db(self, answers: dict, source: str = ""):
        """將 {題目: 答案} dict upsert 進 questions.db 並同步記憶體。
        answers: {q_text: ans_str}
        source:  用於 log 標注來源（如 'AI' / 'harvest'）
        """
        if not answers:
            return
        import sys as _sys
        _base = (
            os.path.dirname(_sys.executable)
            if getattr(_sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__))
        )
        db_path = str(ensure_seeded_database())
        try:
            with GLOBAL_DB_LOCK:
                conn = get_db_connection(db_path, timeout=30.0)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS questions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        question TEXT UNIQUE NOT NULL,
                        option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
                        answer TEXT
                    )
                """)
                added = 0
                for q_text, ans_str in answers.items():
                    cur = conn.execute(
                        "SELECT id FROM questions WHERE question = ?", (q_text,)
                    ).fetchone()
                    if cur:
                        conn.execute(
                            "UPDATE questions SET answer = ? WHERE question = ?",
                            (ans_str, q_text),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO questions (question, answer) VALUES (?, ?)",
                            (q_text, ans_str),
                        )
                        added += 1
                    # 同步記憶體（不論新增或更新都要覆蓋，避免記憶體留有舊錯誤答案）
                    nk = _normalize_q(q_text)
                    if nk:
                        if nk not in self._answer_map:
                            self._answer_keys.append(nk)
                        self._answer_map[nk] = {"answer": ans_str, "options": [], "question": q_text}
                conn.commit()
                conn.close()
            tag = f"（{source}）" if source else ""
            logger.info(f"   💾 已同步 {len(answers)} 題到 questions.db{tag}（新增 {added} 題）")
        except Exception as e:
            logger.warning(f"   ⚠️ 寫入 questions.db 失敗: {e}")

    def toggle_chrome_visibility(self, show: bool):
        """控制 Chrome 視窗顯示與隱藏"""
        self._is_chrome_hidden = not show
        if hasattr(self, "driver") and self.driver:
            set_driver_window_visibility(self.driver, show)

    def _auto_hide_popups_if_needed(self, *, settle: bool = False):
        """若目前處於隱藏模式，自動連同新開的考試與問卷彈出視窗一併無痕隱藏"""
        if getattr(self, "_is_chrome_hidden", False) and hasattr(self, "driver") and self.driver:
            try:
                if settle:
                    maintain_driver_windows_hidden(self.driver)
                else:
                    set_driver_window_visibility(self.driver, False)
            except Exception:
                pass

    def _try_auto_healing(self, reason_msg: str) -> bool:
        """全自動靜默修復 (Auto-Healing) 網絡與 WebDriver 連線異常，防護網最多重試 3 次"""
        if getattr(self, "_auto_healing_count", 0) >= 3:
            logger.error(f"❌ 已達到 Auto-Healing 最大自動修復重連上限 (3 次)，自動安全暫停以保護資源。原因：{reason_msg}")
            return False

        self._auto_healing_count = getattr(self, "_auto_healing_count", 0) + 1
        logger.warning(f"🔄 偵測到連線異常（{reason_msg}），正在啟動全自動靜默修復 (Auto-Healing 第 {self._auto_healing_count}/3 次)...")

        try:
            # 1. 徹底清理舊死 Driver 資源
            self._cleanup()
            time.sleep(2)

            # 2. 重新初始化 WebDriver 引擎
            if not self.init_engine():
                logger.error("❌ Auto-Healing：引擎重建失敗")
                return False

            # 3. 自動重新登入
            if not self.login():
                logger.error("❌ Auto-Healing：重新登入失敗")
                return False

            logger.info("✅ Auto-Healing：瀏覽器連線已成功靜默修復，恢復修課流程！")
            return True
        except Exception as e:
            logger.error(f"❌ Auto-Healing 過程發生例外: {e}")
            return False

    # ── GAS 題庫同步 URL（送出缺題 + 下載更新共用同一個 endpoint）──
    _GAS_DB_URL = "https://script.google.com/macros/s/AKfycbzYUNM--zLlS8El6YR6lIiKerBIz1M6rL2gM8nTGicmEjfh_1TNiBo12YcVsb37J7Cl/exec"
    _GAS_PATCH_URL = "https://raw.githubusercontent.com/waynelord0628-beep/auto-learning-bot/main/patches/questions_patch.json"

    def _update_db_from_gas(self):
        """啟動時靜默背景同步：從 GitHub Raw 直接下載 questions_patch.json 並 upsert 進本地 questions.db。

        格式：[{"question":"...","answer":"...","options":["A","B","C","D"],...}, ...]
        """
        try:
            logger.info("📥 正在從雲端同步最新題庫（背景）...")
            resp = requests.get(
                self._GAS_PATCH_URL,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or len(data) == 0:
                logger.info("📥 GAS 回傳題庫為空或格式不符，略過")
                return

            import sys as _sys
            _base = (
                os.path.dirname(_sys.executable)
                if getattr(_sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__))
            )
            db_path = str(ensure_seeded_database())
            conn = get_db_connection(db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT UNIQUE NOT NULL,
                    option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
                    answer TEXT
                )
            """)
            added = 0
            updated = 0
            for item in data:
                q = (item.get("question") or "").strip()
                a = (item.get("answer") or "").strip()
                if not q or not a:
                    continue
                # 支援 options:[] 格式（questions_patch.json）與 option_a/b/c/d 格式（GAS doGet）
                opts = item.get("options") or []
                oa = (opts[0] if len(opts) > 0 else item.get("option_a") or "").strip()
                ob = (opts[1] if len(opts) > 1 else item.get("option_b") or "").strip()
                oc = (opts[2] if len(opts) > 2 else item.get("option_c") or "").strip()
                od = (opts[3] if len(opts) > 3 else item.get("option_d") or "").strip()
                existing = conn.execute(
                    "SELECT id, answer FROM questions WHERE question = ?", (q,)
                ).fetchone()
                if existing:
                    if existing[1] != a:
                        conn.execute(
                            "UPDATE questions SET answer=?, option_a=?, option_b=?, option_c=?, option_d=? WHERE question=?",
                            (a, oa, ob, oc, od, q),
                        )
                        updated += 1
                else:
                    conn.execute(
                        "INSERT INTO questions (question, option_a, option_b, option_c, option_d, answer) VALUES (?,?,?,?,?,?)",
                        (q, oa, ob, oc, od, a),
                    )
                    added += 1
                # 同步記憶體 _answer_map
                nk = _normalize_q(q)
                if nk:
                    if nk not in self._answer_map:
                        self._answer_keys.append(nk)
                    self._answer_map[nk] = {
                        "answer": a,
                        "options": [o for o in [oa, ob, oc, od] if o],
                        "question": q,
                    }
            conn.commit()
            conn.close()
            logger.info(
                f"📥 GAS 題庫同步完成：新增 {added} 題，更新 {updated} 題"
                f"，記憶體共 {len(self._answer_map)} 題"
            )
        except Exception as e:
            logger.warning(f"📥 GAS 題庫同步失敗（不影響本機題庫）: {e}")

    def _accept_alert(self):
        """若有 alert/confirm 對話框則點確定，無則跳過"""
        try:
            WebDriverWait(self.driver, 3).until(EC.alert_is_present())
            self.driver.switch_to.alert.accept()
            return True
        except Exception:
            return False

    def _harvest_correct_answers(self, view_result_url: str) -> dict:
        """
        從 view_result.php 頁面讀取正確答案。
        流程：
          1. 取得 queryStr 和 isReadAnswer（JS 變數）
          2. 若 isReadAnswer != '1'，用 http_session GET set_see_question_result.php
          3. reload 後，找每題 span[style*='background-color: green'] input → 取 value
          4. 回傳 {題目關鍵字: 答案value} dict（可能為空）
        """
        result = {}
        try:
            # 確認在正確視窗
            time.sleep(1)
            query_str = self.driver.execute_script(
                "try { return typeof queryStr !== 'undefined' ? queryStr : null; } catch(e) { return null; }"
            )
            is_read = self.driver.execute_script(
                "try { return typeof isReadAnswer !== 'undefined' ? isReadAnswer : '0'; } catch(e) { return '0'; }"
            )
            if not query_str:
                logger.debug("   harvest: 無法取得 queryStr，放棄")
                return result

            logger.info(f"   📖 嘗試讀取正確答案（isReadAnswer={is_read}）")

            if is_read != "1":
                # 呼叫 set_see_question_result.php
                base_url = view_result_url.split("/learn/")[0]
                api_url = (
                    f"{base_url}/learn/exam/set_see_question_result.php?{query_str}"
                )
                ua = self.driver.execute_script("return navigator.userAgent;")
                # 同步 cookie 到 http_session
                for c in self.driver.get_cookies():
                    self.http_session.cookies.set(
                        c["name"], c["value"], domain=c["domain"]
                    )
                resp = self.http_session.get(
                    api_url,
                    headers={"User-Agent": ua, "Referer": view_result_url},
                    timeout=10,
                )
                logger.debug(
                    f"   set_see_question_result: {resp.status_code} / {resp.text[:50]!r}"
                )
                if resp.text.strip() == "1":
                    self.driver.refresh()
                    time.sleep(3)
                else:
                    logger.warning(
                        f"   ⚠️ set_see_question_result 無法公布答案（server 回應：{resp.text.strip()[:50]!r}），此課程可能不開放答案"
                    )
                    return result

            # 讀取每題的正確答案（span[style*=green] input）+ 選項文字
            q_data = self.driver.execute_script(
                """
                var result = [];
                var rows = document.querySelectorAll('tr.bg03.font01, tr.bg04.font01');
                for (var i = 0; i < rows.length; i++) {
                    var row = rows[i];
                    var p = row.querySelector('p');
                    var qText = p ? p.innerText.trim() : '';
                    if (!qText) continue;
                    // 找 background-color: green 的 span 裡的 input
                    var spans = row.querySelectorAll('span');
                    var correctVals = [];
                    var correctTexts = [];
                    for (var j = 0; j < spans.length; j++) {
                        var bg = spans[j].style.backgroundColor;
                        if (bg === 'green' || bg === 'rgb(0, 128, 0)') {
                            var inp = spans[j].querySelector('input');
                            if (inp) correctVals.push(inp.value);
                            // 取選項文字（span 內去掉 input 的文字）
                            var spanText = spans[j].innerText || spans[j].textContent || '';
                            spanText = spanText.replace(/^[\\s\\d.]+/, '').trim();
                            if (spanText) correctTexts.push(spanText);
                        }
                    }
                    if (correctVals.length > 0) {
                        result.push({q: qText, ans: correctVals, texts: correctTexts});
                    }
                }
                return result;
                """
            )

            if not q_data:
                logger.warning("   ⚠️ 未讀到任何正確答案（可能頁面未更新或格式不符）")
                return result

            # 轉換格式並寫入 answers.json（優先用選項文字，其次用 value）
            for item in q_data:
                q_text = item["q"]
                ans_vals = item["ans"]
                ans_texts = item.get("texts", [])
                # 去掉題號前綴（如 "1. " "（1）" 等），與 auto_exam 的題目文字一致
                q_text_clean = re.sub(r"^[\d０-９]+[.．、。）)\s]+", "", q_text).strip()
                # 保留題目全文作為 key（不截 30 字，避免碰撞）
                key = q_text_clean.strip()
                # 優先用選項文字作為答案，多選以「、」合併為一個字串
                if ans_texts:
                    ans_str = (
                        "、".join(ans_texts) if len(ans_texts) > 1 else ans_texts[0]
                    )
                else:
                    # fallback: 用 input value
                    ans_str = (
                        "、".join(ans_vals)
                        if len(ans_vals) > 1
                        else (ans_vals[0] if ans_vals else "")
                    )
                result[key] = ans_str
                logger.debug(f"   harvest: {key!r} => {ans_str!r}")

            logger.info(f"   📖 讀到 {len(result)} 題正確答案")

            # 寫入 answers.json（list 格式 [{"題目": ..., "答案": ...}]）
            try:
                answers_path = str(user_data_path("answers.json"))
                existing_list = []
                if os.path.exists(answers_path):
                    with open(answers_path, encoding="utf-8") as f:
                        existing_list = json.load(f)
                # 建立題目全文→index 的快速查找（雙向比對以找到相同題目）
                existing_keys = {}
                for idx_e, entry in enumerate(existing_list):
                    ek = entry.get("題目", "").strip()
                    existing_keys[ek] = idx_e
                # 更新或新增
                added = 0
                for key, ans_str in result.items():
                    # 先嘗試精確匹配，再嘗試雙向包含
                    matched_idx = None
                    if key in existing_keys:
                        matched_idx = existing_keys[key]
                    else:
                        for ek, idx_e in existing_keys.items():
                            if (
                                key
                                and ek
                                and len(key) >= 8
                                and len(ek) >= 8
                                and (key in ek or ek in key)
                            ):
                                matched_idx = idx_e
                                break
                    if matched_idx is not None:
                        # 更新現有條目
                        existing_list[matched_idx]["答案"] = ans_str
                    else:
                        existing_list.append({"題目": key, "答案": ans_str})
                        added += 1
                with open(answers_path, "w", encoding="utf-8") as f:
                    json.dump(existing_list, f, ensure_ascii=False, indent=2)
                logger.info(
                    f"   ✅ 已將 {len(result)} 題答案寫入 answers.json（新增 {added} 題，共 {len(existing_list)} 題）"
                )
                # 更新記憶體中的 answers（list of (題目, 答案)）
                for key, ans_str in result.items():
                    self.answers.append((key, ans_str))
            except Exception as e:
                logger.warning(f"   ⚠️ 寫入 answers.json 失敗: {e}")

            # 同步寫入 questions.db（複用 _save_answers_to_db）
            self._save_answers_to_db(result, source="harvest")

        except Exception as e:
            logger.debug(f"   harvest_correct_answers 失敗: {e}")

        return result

    def _read_exam_result(self, course, _ai_answered=None):
        """讀取測驗繳交後的成績與通過狀態並記錄日誌。依據每門課程之 criteria_exam_score 精確核定通過與否。"""
        course_id = str(course.get("course_id", ""))
        course_name = course.get("caption", course_id)
        passed = False
        time.sleep(3)

        # 取得課程專屬及格門檻（動態支援 60、70、75、80、100 分等各平臺門檻）
        pass_score = 60.0
        for f in [
            "criteria_exam_score",
            "criteria_score",
            "pass_score",
            "exam_pass_score",
            "criteria_test_score",
        ]:
            val = course.get(f)
            if val is not None and str(val).strip() not in ("", "--", "None", "null", "0", "0.0"):
                try:
                    pass_score = float(val)
                    break
                except Exception:
                    pass

        try:
            body_text = self.driver.execute_script(
                "return document.body ? document.body.innerText : '';"
            ) or ""
            try:
                iframe_text = self.driver.execute_script(
                    """
                    var f = document.querySelector('[name="submitTarget"], #submitTarget, iframe[name="submitTarget"]');
                    if (f && f.contentDocument) return f.contentDocument.body.innerText;
                    return '';
                    """
                )
                if iframe_text:
                    body_text += " " + iframe_text
            except Exception:
                pass

            # 擷取分數
            score_match = re.search(r"(?:成績|得分|分數|總分)[：:\s]*([0-9]+(?:\.[0-9]+)?)", body_text)
            score_val = float(score_match.group(1)) if score_match else None
            score_str = f"【得分：{score_val} 分 / 門檻：{pass_score} 分】" if score_val is not None else f"【門檻：{pass_score} 分】"

            if score_val is not None:
                if score_val >= pass_score:
                    logger.info(f"   🎉 測驗結果：達標及格 {score_str}！")
                    passed = True
                    self._exam_fail_counts.pop(course_id, None)
                    if _ai_answered:
                        self._save_answers_to_db(_ai_answered, source="AI")
                else:
                    self._exam_fail_counts[course_id] = self._exam_fail_counts.get(course_id, 0) + 1
                    fail_now = self._exam_fail_counts[course_id]
                    logger.warning(f"   ❌ 測驗結果：未達門檻 {score_str}（已累計未達標 {fail_now} 次）")
                    passed = False
            elif "\u4e0d\u53ca\u683c" in body_text or "未通過" in body_text:
                self._exam_fail_counts[course_id] = self._exam_fail_counts.get(course_id, 0) + 1
                fail_now = self._exam_fail_counts[course_id]
                logger.warning(f"   ❌ 測驗結果：不及格 / 未通過 {score_str}（已累計不及格 {fail_now} 次）")
                passed = False
            elif "\u53ca\u683c" in body_text or "通過" in body_text:
                logger.info(f"   🎉 測驗結果：及格 / 通過 {score_str}！")
                passed = True
                self._exam_fail_counts.pop(course_id, None)
                if _ai_answered:
                    self._save_answers_to_db(_ai_answered, source="AI")
            else:
                logger.info(f"   📝 測驗已送出 {score_str}（請至學習紀錄查核狀態）")
                passed = False
        except Exception as e:
            logger.debug(f"讀取測驗成績失敗: {e}")
            passed = False

        return passed

    def auto_exam(self, course):
        """時數達標後，自動進入測驗並作答。回傳 True=通過, False=未通過/失敗"""
        ai_keys = self.config.get("ai_keys", {})
        ai_keys = ai_keys if isinstance(ai_keys, dict) else {}
        ai_provider = self.config.get("ai_provider", "OpenAI")
        ai_enabled = bool(ai_keys.get(ai_provider) or self.config.get("ai_api_key", ""))

        if (
            not self.config.get("interactive_quiz_for_session")
            and not self._answer_map
            and not self.answers
            and not ai_enabled
        ):
            logger.info("   📝 未設定題庫或 AI，且未啟用人機協同模式，跳過自動作答")
            return False

        course_id = str(course.get("course_id", ""))

        # 不及格超過 3 次，跳過此課程
        fail_count = self._exam_fail_counts.get(course_id, 0)
        if fail_count >= 3:
            logger.warning(
                f"   ⚠️ 課程「{course.get('caption', course_id)}」已不及格 {fail_count} 次，跳過，請使用者自行完成測驗"
            )
            return False

        logger.info("   📝 開始自動作答流程...")
        # 收集本場 AI 補答的題目，考試通過後寫入 db
        _ai_answered = {}
        # 僅在已設定有效 Key 時，重測才以 AI 覆核；否則維持純題庫模式。
        force_ai = fail_count >= 1 and ai_enabled
        if not ai_enabled:
            logger.info("   📚 未設定 API Key，啟用純題庫模式，不呼叫 AI 補答。")
        # 以「目前所在視窗」為課程教室主視窗（不論從哪條路徑進入）
        main_window = self.driver.current_window_handle

        try:
            # ── 1. 切回教室主視窗，點左側 sidebar「測驗/考試」──
            # sidebar 在 mooc_sysbar frame（<frame name="mooc_sysbar">）
            self.driver.switch_to.window(main_window)
            self.driver.switch_to.default_content()

            # 💡 若仍在 /info/ 課程介紹頁面，先檢查是否已通過，或點擊「上課去」進入教室介面
            if "/info/" in self.driver.current_url:
                try:
                    info_text = (
                        self.driver.execute_script(
                            "return document.body ? document.body.innerText : '';"
                        )
                        or ""
                    )
                    if (
                        "通過狀態" in info_text
                        and "已通過" in info_text
                        and ("測驗" in info_text and ("100" in info_text or "及格" in info_text))
                    ) or (
                        "您已完成此課程" in info_text and "無法重複取得時數" in info_text
                    ):
                        logger.info(
                            f"   🎉 課程「{course.get('caption', '')}」平臺顯示測驗已通過／已完成，免再次測驗。"
                        )
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        return True

                    clicked_in = self.driver.execute_script("""
                        var modalBtns = document.querySelectorAll('.modal button, .dialog button, div[role="dialog"] button, button.btn-primary, button.btn-confirm');
                        for (var m = 0; m < modalBtns.length; m++) {
                            var mt = (modalBtns[m].innerText || modalBtns[m].textContent || '').trim();
                            if (mt === '確定' || mt === '確認') {
                                modalBtns[m].click();
                                return '確定（彈窗）';
                            }
                        }
                        var btns = document.querySelectorAll('button, a.btn, a, input[type="button"], input[type="submit"]');
                        for (var i = 0; i < btns.length; i++) {
                            var t = (btns[i].innerText || btns[i].value || btns[i].textContent || '').trim();
                            if (['認證', '進行測驗', '開始測驗', '參加測驗', '前往測驗', '測驗', '上課去', '進入課程', '開始上課', '前往教室', '繼續學習', '觀看影片', '前往研習'].some(k => t.indexOf(k) !== -1)) {
                                btns[i].click();
                                return t;
                            }
                        }
                        return null;
                    """)
                    if clicked_in:
                        logger.info(f"   📝 已點擊「{clicked_in}」進入教室/測驗介面")
                        time.sleep(4)
                        if len(self.driver.window_handles) > 1:
                            main_window = self.driver.window_handles[-1]
                            self.driver.switch_to.window(main_window)
                            self._auto_hide_popups_if_needed(settle=True)
                except Exception:
                    pass

            clicked_exam = False
            try:
                self.driver.switch_to.frame("mooc_sysbar")
                exam_link = self.driver.find_element(
                    By.CSS_SELECTOR, "a[href*='exam/exam_list.php'], a[href*='exam']"
                )
                self.driver.execute_script("arguments[0].click();", exam_link)
                self._auto_hide_popups_if_needed(settle=True)
                logger.info("   📝 已點擊「測驗/考試」")
                clicked_exam = True
            except Exception:
                pass

            if not clicked_exam:
                self.driver.switch_to.default_content()
                try:
                    exam_btn = self.driver.find_element(
                        By.CSS_SELECTOR,
                        "a[href*='exam_list'], a[href*='exam'], button[onclick*='exam'], a[onclick*='exam'], .btn-warning, a.btn[href*='quiz'], input[value*='測驗'], input[value*='認證'], a.btn[href*='cert']"
                    )
                    self.driver.execute_script("arguments[0].click();", exam_btn)
                    self._auto_hide_popups_if_needed(settle=True)
                    logger.info("   📝 已從主頁面點擊「測驗/認證」")
                    clicked_exam = True
                except Exception as e:
                    logger.warning(f"   ⚠️ 找不到測驗連結（可能為平台已下架或無測驗介面課程）: {e}")
                    self._mark_exam_manual_review(course, "找不到測驗入口，尚未確認測驗已通過")
                    return False

            time.sleep(2)

            # ── 2. 切到 s_main frame（frameset 結構，非 iframe）──
            self.driver.switch_to.default_content()
            try:
                self.driver.switch_to.frame("s_main")
            except Exception:
                logger.warning("   ⚠️ 無法切換到 s_main frame")
                return False

            time.sleep(1)

            # ── 2a. 檢查是否已通過（綠色「已通過」div 或已公布答案文字）──
            try:
                # 方法1：找 div.process-btn 內含「已通過」span（來自截圖結構）
                passed_els = self.driver.find_elements(
                    By.XPATH,
                    "//div[contains(@class,'process-btn')]//span[contains(text(),'已通過')]",
                )
                # 方法2：找「已選擇公布答案，不得再進行測驗」提示文字
                if not passed_els:
                    passed_els = self.driver.find_elements(
                        By.XPATH, "//*[contains(text(),'已選擇公布答案')]"
                    )
                if passed_els:
                    logger.info("   ✅ 測驗已通過（先前已完成），跳過作答")
                    return True
            except Exception:
                pass

            # ── 3. 點「進行測驗」──
            try:
                pay_btn = self.driver.find_element(
                    By.CSS_SELECTOR, "div.process-btn.pay.active"
                )
                self.driver.execute_script("arguments[0].click();", pay_btn)
                self._auto_hide_popups_if_needed(settle=True)
                logger.info("   📝 已點擊「進行測驗」")
            except Exception as e:
                logger.warning(f"   ⚠️ 找不到「進行測驗」按鈕: {e}")
                return False

            time.sleep(3)

            # ── 4. 切換到新跳出的考試視窗 ──
            all_handles = self.driver.window_handles
            exam_window = next((h for h in all_handles if h != main_window), None)
            if not exam_window:
                logger.warning("   ⚠️ 未偵測到考試視窗")
                return False

            self.driver.switch_to.window(exam_window)
            self._auto_hide_popups_if_needed(settle=True)
            logger.info("   📝 已切換至考試視窗")

            # 等待考試頁面載入完成（最多 15 秒）
            try:
                WebDriverWait(self.driver, 15).until(
                    lambda d: d.execute_script(
                        'var inputs = document.querySelectorAll(\'input[type="button"], input[type="submit"]\');'
                        "for(var i=0;i<inputs.length;i++){var v=inputs[i].value||''; if(v.indexOf('\u958b\u59cb')!==-1||v.indexOf('\u4f5c\u7b54')!==-1) return true;}"
                        "return inputs.length > 0;"
                    )
                )
            except Exception:
                # timeout 了，繼續往下嘗試（舊版 fallback）
                pass

            # 記錄 exam_start URL（含 course_id+attempt+token）供步驟10推算 view_result URL
            exam_start_url = self.driver.current_url

            # ── 5. 點「開始作答」 ──
            # 用 JS 點擊（避免 StaleElementReferenceException）
            # 頁面有 type=button 的「開始作答」，是第一個 input[type=button]
            try:
                clicked = self.driver.execute_script(
                    """
                    var inputs = document.querySelectorAll('input');
                    for (var i = 0; i < inputs.length; i++) {
                        var v = inputs[i].value || '';
                        // 「開始作答」Unicode: \u958b\u59cb\u4f5c\u7b54
                        if (v.indexOf('\u958b\u59cb') !== -1) {
                            inputs[i].click();
                            return v;
                        }
                    }
                    // fallback：點第一個 type=button
                    var btn = document.querySelector('input[type="button"]');
                    if (btn) { btn.click(); return btn.value; }
                    return null;
                    """
                )
                if clicked:
                    logger.info(f"   📝 已點擊開始按鈕：{clicked!r}")
                else:
                    logger.warning("   ⚠️ 找不到開始作答按鈕")
                    return False
            except Exception as e:
                logger.warning(f"   ⚠️ 點擊開始作答失敗: {e}")
                return False

            time.sleep(2)

            # ── 6. 逐題作答 ──
            answered = 0
            skipped = 0
            _missing = []  # 題庫無答案的題目，考試後回報 GAS

            rows = self.driver.find_elements(
                By.CSS_SELECTOR, "tr.bg03.font01, tr.bg04.font01"
            )

            # ── DOM 診斷（首次執行時印出） ──
            try:
                iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                frames = self.driver.find_elements(By.TAG_NAME, "frame")
                logger.info(
                    f"   [DOM] iframe 數量: {len(iframes)}, frame 數量: {len(frames)}"
                )
                logger.info(
                    f"   [DOM] iframe names: {[f.get_attribute('name') or f.get_attribute('id') or '?' for f in iframes]}"
                )
                logger.info(f"   [DOM] rows 數量: {len(rows)}")
                if rows:
                    first_html = self.driver.execute_script(
                        "return arguments[0].outerHTML;", rows[0]
                    )
                    logger.info(
                        f"   [DOM] 第一個row HTML (前1000字): {first_html[:1000]}"
                    )
                else:
                    # rows 為空，印出整個 table body 的 HTML 幫助診斷
                    page_sample = self.driver.execute_script(
                        "var t = document.querySelector('table'); return t ? t.outerHTML.substring(0,2000) : document.body.innerHTML.substring(0,2000);"
                    )
                    logger.info(
                        f"   [DOM] rows 為空，頁面 table HTML (前2000字): {page_sample}"
                    )
            except Exception as _dom_e:
                logger.info(f"   [DOM] 診斷略過: {_dom_e}")

            # ── 6a. 檢查是否啟用人機協同作答助理（彈窗複製題目／回貼答案） ──
            if self.config.get("interactive_quiz_for_session") and self.quiz_interactive_callback:
                questions_data = []
                for q_idx, row in enumerate(rows):
                    try:
                        q_text = (
                            self.driver.execute_script(
                                """
                            var tds = arguments[0].querySelectorAll('td');
                            var td = null;
                            for (var j = 0; j < tds.length; j++) {
                                if (tds[j].querySelector('ol, ul, input')) {
                                    td = tds[j];
                                    break;
                                }
                            }
                            if (!td) {
                                var candidates = arguments[0].querySelectorAll('td[align="left"]');
                                for (var k = 0; k < candidates.length; k++) {
                                    if (!candidates[k].hasAttribute('nowrap')) {
                                        td = candidates[k];
                                        break;
                                    }
                                }
                            }
                            if (!td) td = arguments[0].querySelector('td');
                            if (!td) return '';
                            var text = '';
                            for (var i = 0; i < td.childNodes.length; i++) {
                                var n = td.childNodes[i];
                                if (n.nodeType === 3) {
                                    text += n.textContent;
                                } else if (n.nodeName === 'P' || n.nodeName === 'STRONG' || n.nodeName === 'SPAN') {
                                    text += n.innerText || n.textContent;
                                    break;
                                } else if (n.nodeName === 'OL' || n.nodeName === 'UL') {
                                    break;
                                }
                            }
                            text = text.trim();
                            text = text.replace(/^[\\d]+[.\\s]+/, '').trim();
                            return text;
                            """,
                                row,
                            )
                            or ""
                        )
                        if not q_text:
                            try:
                                q_el = row.find_element(By.TAG_NAME, "p")
                                q_text = q_el.text.strip()
                            except Exception:
                                q_text = row.text.strip().split("\n")[0]

                        opt_texts = (
                            self.driver.execute_script(
                                """
                            var tds = arguments[0].querySelectorAll('td');
                            var td = null;
                            for (var j = 0; j < tds.length; j++) {
                                if (tds[j].querySelector('ol, ul, input')) {
                                    td = tds[j];
                                    break;
                                }
                            }
                            if (!td) {
                                var candidates = arguments[0].querySelectorAll('td[align="left"]');
                                for (var k = 0; k < candidates.length; k++) {
                                    if (!candidates[k].hasAttribute('nowrap')) {
                                        td = candidates[k];
                                        break;
                                    }
                                }
                            }
                            if (!td) td = arguments[0].querySelector('td');
                            if (!td) return [];
                            var items = td.querySelectorAll('ol li, ul li');
                            var texts = [];
                            for (var i = 0; i < items.length; i++) {
                                var li = items[i];
                                var text = '';
                                for (var k = 0; k < li.childNodes.length; k++) {
                                    var cn = li.childNodes[k];
                                    if (cn.nodeType === 3) {
                                        text += cn.textContent;
                                    } else if (cn.nodeName !== 'INPUT' && cn.nodeName !== 'SPAN') {
                                        text += cn.innerText || cn.textContent || '';
                                    } else if (cn.nodeName === 'SPAN') {
                                        for (var m = 0; m < cn.childNodes.length; m++) {
                                            if (cn.childNodes[m].nodeType === 3) {
                                                text += cn.childNodes[m].textContent;
                                            }
                                        }
                                    }
                                }
                                texts.push(text.trim());
                            }
                            return texts;
                            """,
                                row,
                            )
                            or []
                        )

                        radios = row.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                        checkboxes = row.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
                        is_multiple = len(checkboxes) > 0
                        q_type = "多選" if is_multiple else ("是非" if len(radios) == 2 else "單選")

                        options = []
                        if opt_texts:
                            for o_idx, ot in enumerate(opt_texts):
                                label = chr(65 + o_idx)
                                options.append({"label": label, "text": ot})
                        elif len(radios) == 2:
                            options = [
                                {"label": "A", "text": "⭕ (是/正確)"},
                                {"label": "B", "text": "❌ (否/錯誤)"},
                            ]
                        else:
                            count = len(radios) or len(checkboxes)
                            for o_idx in range(count):
                                label = chr(65 + o_idx)
                                options.append({"label": label, "text": f"選項 {label}"})

                        questions_data.append({
                            "index": q_idx + 1,
                            "type": q_type,
                            "q_text": q_text,
                            "options": options,
                            "is_multiple": is_multiple,
                        })
                    except Exception as e:
                        logger.debug(f"萃取題目 {q_idx + 1} 失敗: {e}")

                if questions_data:
                    logger.info(f"   📝 正在啟動「人機協同作答助理」互動視窗（{INTERACTIVE_QUIZ_TIMEOUT_SECONDS} 秒倒數）...")
                    interactive_ans_map = self.quiz_interactive_callback(
                        course.get("caption", "公務員測驗"),
                        questions_data,
                        timeout_sec=INTERACTIVE_QUIZ_TIMEOUT_SECONDS,
                    )

                    if isinstance(interactive_ans_map, dict) and interactive_ans_map:
                        logger.info(
                            f"   🚀 已收到回貼答案（共 {len(interactive_ans_map)} 題），正在自動勾選網頁選項..."
                        )
                        for q_idx, row in enumerate(rows):
                            q_num = q_idx + 1
                            if q_num not in interactive_ans_map:
                                continue
                            selected_labels = interactive_ans_map[q_num]

                            radios = row.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                            checkboxes = row.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
                            inputs = checkboxes if checkboxes else radios

                            for lbl in selected_labels:
                                opt_idx = ord(lbl.upper()) - 65
                                if 0 <= opt_idx < len(inputs):
                                    try:
                                        self.driver.execute_script("arguments[0].click();", inputs[opt_idx])
                                    except Exception as e:
                                        logger.debug(f"勾選選項 {lbl} 失敗: {e}")

                        logger.info("   ✅ 選項勾選完成，正在送出考卷...")
                        time.sleep(1)
                        try:
                            self.driver.execute_script(
                                """
                                var btns = document.querySelectorAll('input[type="submit"]');
                                for (var i = 0; i < btns.length; i++) {
                                    var b = btns[i];
                                    var formName = b.form ? (b.form.name || b.form.id || '') : '';
                                    if (formName === 'responseForm') {
                                        b.click();
                                        return true;
                                    }
                                }
                                if (btns.length > 0) { btns[0].click(); return true; }
                                return false;
                                """
                            )
                        except Exception:
                            pass

                        time.sleep(1)
                        self._accept_alert()
                        passed = self._read_exam_result(course)
                        # 人機協同答案只用於本次作答，不寫回本機題庫。
                        if not passed:
                            time.sleep(1)
                            try:
                                cur_exam_url = self.driver.current_url
                                if "view_result" in cur_exam_url:
                                    self._harvest_correct_answers(cur_exam_url)
                            except Exception:
                                pass
                        try:
                            self.driver.switch_to.window(main_window)
                        except Exception:
                            pass
                        return passed
                    elif interactive_ans_map == "STOP_ALL":
                        logger.info("🛑 使用者於測驗逾時對話框選擇【結束本次執行】。")
                        self.running = False
                        try:
                            self.driver.close()
                            self.driver.switch_to.window(main_window)
                        except Exception:
                            pass
                        return False
                    elif interactive_ans_map == "DIALOG_ERROR":
                        self._mark_exam_manual_review(
                            course, "人機協同測驗視窗無法顯示，尚未執行跳過指令"
                        )
                        try:
                            self.driver.close()
                            self.driver.switch_to.window(main_window)
                        except Exception:
                            pass
                        return False
                    else:
                        logger.info(f"   ⏩ 使用者選擇跳過課程【{course.get('caption', '')}】之測驗，繼續下一門。")
                        try:
                            self.driver.close()
                            self.driver.switch_to.window(main_window)
                        except Exception:
                            pass
                        return False

            parsed_items = []
            for q_idx, row in enumerate(rows):
                try:
                    # ── 題目文字擷取 ──
                    try:
                        q_text = (
                            self.driver.execute_script(
                                """
                            var tds = arguments[0].querySelectorAll('td');
                            var td = null;
                            for (var j = 0; j < tds.length; j++) {
                                if (tds[j].querySelector('ol, ul, input')) {
                                    td = tds[j];
                                    break;
                                }
                            }
                            if (!td) {
                                var candidates = arguments[0].querySelectorAll('td[align="left"]');
                                for (var k = 0; k < candidates.length; k++) {
                                    if (!candidates[k].hasAttribute('nowrap')) {
                                        td = candidates[k];
                                        break;
                                    }
                                }
                            }
                            if (!td) td = arguments[0].querySelector('td');
                            if (!td) return '';
                            var text = '';
                            for (var i = 0; i < td.childNodes.length; i++) {
                                var n = td.childNodes[i];
                                if (n.nodeType === 3) {
                                    text += n.textContent;
                                } else if (n.nodeName === 'P' || n.nodeName === 'STRONG' || n.nodeName === 'SPAN') {
                                    text += n.innerText || n.textContent;
                                    break;
                                } else if (n.nodeName === 'OL' || n.nodeName === 'UL') {
                                    break;
                                }
                            }
                            text = text.trim();
                            text = text.replace(/^[\\d]+[.\\s]+/, '').trim();
                            return text;
                            """,
                                row,
                            )
                            or ""
                        )
                    except Exception:
                        q_text = ""
                    if not q_text:
                        try:
                            q_el = row.find_element(By.TAG_NAME, "p")
                            q_text = q_el.text.strip()
                        except Exception:
                            q_text = row.text.strip().split("\n")[0]

                    ans = self._find_answer(q_text)
                    radios = row.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                    checkboxes = row.find_elements(
                        By.CSS_SELECTOR, "input[type='checkbox']"
                    )

                    try:
                        option_texts = (
                            self.driver.execute_script(
                                """
                            var tds = arguments[0].querySelectorAll('td');
                            var td = null;
                            for (var j = 0; j < tds.length; j++) {
                                if (tds[j].querySelector('ol, ul, input')) {
                                    td = tds[j];
                                    break;
                                }
                            }
                            if (!td) {
                                var candidates = arguments[0].querySelectorAll('td[align="left"]');
                                for (var k = 0; k < candidates.length; k++) {
                                    if (!candidates[k].hasAttribute('nowrap')) {
                                        td = candidates[k];
                                        break;
                                    }
                                }
                            }
                            if (!td) td = arguments[0].querySelector('td');
                            if (!td) return [];
                            var items = td.querySelectorAll('ol li, ul li');
                            var texts = [];
                            for (var i = 0; i < items.length; i++) {
                                var li = items[i];
                                var text = '';
                                for (var k = 0; k < li.childNodes.length; k++) {
                                    var cn = li.childNodes[k];
                                    if (cn.nodeType === 3) {
                                        text += cn.textContent;
                                    } else if (cn.nodeName !== 'INPUT' && cn.nodeName !== 'SPAN') {
                                        text += cn.innerText || cn.textContent || '';
                                    } else if (cn.nodeName === 'SPAN') {
                                        for (var m = 0; m < cn.childNodes.length; m++) {
                                            if (cn.childNodes[m].nodeType === 3) {
                                                text += cn.childNodes[m].textContent;
                                            }
                                        }
                                    }
                                }
                                texts.push(text.trim());
                            }
                            return texts;
                            """,
                                row,
                            )
                            or []
                        )
                    except Exception:
                        option_texts = []

                    parsed_items.append({
                        "idx": q_idx,
                        "row": row,
                        "q_text": q_text,
                        "option_texts": option_texts,
                        "radios": radios,
                        "checkboxes": checkboxes,
                        "ans": ans,
                    })
                except Exception as e:
                    logger.warning(f"   ⚠️ 解析第 {q_idx + 1} 題失敗：{e}")

            # ⚡ 10 題合一整卷 AI 批次作答（僅發送 1 次 API 請求，節省 90% 額度）
            items_needing_ai = [item for item in parsed_items if item["ans"] is None or force_ai]
            if ai_enabled and items_needing_ai:
                batch_questions = []
                opt_labels = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]
                for item in items_needing_ai:
                    opts_list = []
                    radios_count = len(item["radios"])
                    ai_options = item["option_texts"] if any(item["option_texts"]) else (
                        ["正確（是）", "錯誤（否）"] if radios_count == 2 else []
                    )
                    for o_idx, o_txt in enumerate(ai_options):
                        label = opt_labels[o_idx] if o_idx < len(opt_labels) else str(o_idx + 1)
                        opts_list.append({"label": label, "text": o_txt, "val": str(o_idx + 1)})

                    is_tf = len(opts_list) == 2 and any(k in item["q_text"] or k in "".join(o["text"] for o in opts_list) for k in ["是非", "是否", "對錯", "○", "╳", "⭕", "❌"])
                    q_type = "是非" if is_tf else ("多選" if item["checkboxes"] else "單選")
                    batch_questions.append({
                        "index": item["idx"] + 1,
                        "name": f"q_{item['idx'] + 1}",
                        "type": q_type,
                        "is_multiple": bool(item["checkboxes"]),
                        "q_text": item["q_text"],
                        "options": opts_list,
                        "raw_item": item,
                    })

                try:
                    from quiz_bank import ai_batch_solve_quiz
                    batch_res = ai_batch_solve_quiz(course.get('caption', 'e等公務員測驗'), batch_questions, self.config)
                    if batch_res.get("success") and batch_res.get("answers"):
                        for b_q in batch_questions:
                            q_num = str(b_q["index"])
                            ans_choice = batch_res["answers"].get(q_num) or batch_res["answers"].get(int(q_num))
                            if ans_choice:
                                item = b_q["raw_item"]
                                matched_opt = next((o for o in b_q["options"] if o["label"].upper() == str(ans_choice).upper() or o["val"] == str(ans_choice)), None)
                                if matched_opt:
                                    item["ans"] = matched_opt["val"]
                                    _ai_answered[item["q_text"]] = matched_opt["val"]
                                else:
                                    item["ans"] = str(ans_choice)
                                    _ai_answered[item["q_text"]] = str(ans_choice)
                                logger.info(f"   🤖 AI 批次解答 [{q_num}/{len(rows)} 題]：{item['ans']!r}")
                    else:
                        # 降級備援：個別呼叫 _ai_find_answer
                        for item in items_needing_ai:
                            if item["ans"] is None:
                                radios_count = len(item["radios"])
                                ai_options = item["option_texts"] if any(item["option_texts"]) else (
                                    ["正確（是）", "錯誤（否）"] if radios_count == 2 else []
                                )
                                if ai_options:
                                    item["ans"] = self._ai_find_answer(item["q_text"], ai_options)
                                    if item["ans"]:
                                        _ai_answered[item["q_text"]] = item["ans"]
                except Exception as batch_err:
                    logger.warning(f"   ⚠️ AI 批次作答失敗，切換為逐題備援：{batch_err}")
                    for item in items_needing_ai:
                        if item["ans"] is None:
                            radios_count = len(item["radios"])
                            ai_options = item["option_texts"] if any(item["option_texts"]) else (
                                ["正確（是）", "錯誤（否）"] if radios_count == 2 else []
                            )
                            if ai_options:
                                item["ans"] = self._ai_find_answer(item["q_text"], ai_options)
                                if item["ans"]:
                                    _ai_answered[item["q_text"]] = item["ans"]

            for item in parsed_items:
                q_idx = item["idx"]
                row = item["row"]
                q_text = item["q_text"]
                option_texts = item["option_texts"]
                radios = item["radios"]
                checkboxes = item["checkboxes"]
                ans = item["ans"]

                try:
                    logger.debug(f"   題目: {q_text[:50]!r}")
                    logger.debug(f"   選項: {[t[:20] for t in option_texts]!r}")
                    logger.debug(f"   答案: {ans!r}")
                    logger.info(f"   📝 作答進度：[{q_idx + 1}/{len(rows)} 題] 已填答")

                    if checkboxes:
                        if ans is not None:
                            ans_text = (
                                ans
                                if isinstance(ans, str)
                                else (ans[0] if isinstance(ans, list) else str(ans))
                            )
                            ans_norm = ans_text.strip()
                            # 多選答案以「、」分隔，拆成清單分別比對
                            ans_parts = [
                                p.strip() for p in ans_norm.split("、") if p.strip()
                            ]
                            if not ans_parts:
                                ans_parts = [ans_norm]
                            # 「以上皆是/以上皆可/以上皆正確/以上皆對/all of the above」→ 全選
                            ALL_ABOVE_PATTERNS = [
                                "以上皆是",
                                "以上皆可",
                                "以上皆正確",
                                "以上皆對",
                                "all of the above",
                                "ll of the above",
                            ]
                            is_all_above = any(
                                p in ans_norm for p in ALL_ABOVE_PATTERNS
                            )
                            if is_all_above:
                                for cb in checkboxes:
                                    self.driver.execute_script(
                                        "arguments[0].click();", cb
                                    )
                                logger.debug(
                                    f"   ✅ 全選（以上皆是）：{q_text[:20]}..."
                                )
                            else:
                                # 先嘗試 value 比對（向後相容 1/2/3/4/a/b/c/d）
                                letter_to_num = {
                                    "a": "1",
                                    "b": "2",
                                    "c": "3",
                                    "d": "4",
                                    "e": "5",
                                    "f": "6",
                                    "g": "7",
                                    "h": "8",
                                }
                                ans_list = ans if isinstance(ans, list) else ans_parts
                                ans_list_norm = [a.lower() for a in ans_list]
                                value_matched = False
                                for cb in checkboxes:
                                    cb_val = (cb.get_attribute("value") or "").lower()
                                    cb_letter = {
                                        v: k for k, v in letter_to_num.items()
                                    }.get(cb_val, cb_val)
                                    if (
                                        cb_val in ans_list_norm
                                        or cb_letter in ans_list_norm
                                    ):
                                        self.driver.execute_script(
                                            "arguments[0].click();", cb
                                        )
                                        value_matched = True
                                # fallback: 用答案文字比對選項文字（支援多選拆分）
                                if not value_matched:
                                    for i, cb in enumerate(checkboxes):
                                        opt_text = (
                                            option_texts[i].strip()
                                            if i < len(option_texts)
                                            else ""
                                        )
                                        if opt_text:
                                            # 任一答案部分與選項文字雙向包含即命中
                                            for part in ans_parts:
                                                if part and (
                                                    part in opt_text or opt_text in part
                                                ):
                                                    self.driver.execute_script(
                                                        "arguments[0].click();", cb
                                                    )
                                                    break
                        else:
                            # 無答案：隨機勾 2~3 個 checkbox
                            n = len(checkboxes)
                            pick_count = min(n, random.randint(2, max(2, n - 1)))
                            picks = random.sample(checkboxes, pick_count)
                            for pick in picks:
                                self.driver.execute_script(
                                    "arguments[0].click();", pick
                                )
                            logger.debug(
                                f"   🎲 多選隨機作答({pick_count}/{n})：{q_text[:20]}..."
                            )
                        answered += 1

                    elif radios:
                        idx = None
                        if ans is not None:
                            ans_str = (
                                ans
                                if isinstance(ans, str)
                                else (ans[0] if isinstance(ans, list) else str(ans))
                            )
                            ans_norm = ans_str.strip()
                            ans_lower = ans_norm.lower()

                            # AI 新格式會只回 1/2/3/4；題庫也可能存 A/B/C/D 或「2. 答案」。
                            m = re.search(r"(?<!\d)(\d+)(?!\d)", ans_norm)
                            if m:
                                n = int(m.group(1))
                                if 1 <= n <= len(radios):
                                    idx = n - 1

                            if idx is None:
                                letter_map = {chr(ord("a") + i): i for i in range(len(radios))}
                                token = re.sub(r"[^a-zA-Z]", "", ans_norm).lower()
                                if token in letter_map:
                                    idx = letter_map[token]

                            if idx is None and len(radios) == 2:
                                ans_upper = ans_norm.upper()
                                if ans_upper in ("O", "T", "TRUE", "A"):
                                    idx = 0
                                elif ans_upper in ("X", "F", "FALSE", "B"):
                                    idx = 1
                                else:
                                    true_words = ["對", "是", "正確", "true"]
                                    false_words = ["錯", "否", "不正確", "錯誤", "false", "非"]
                                    if any(w in ans_lower for w in true_words):
                                        idx = 0
                                    elif any(w in ans_lower for w in false_words):
                                        idx = 1

                            if idx is None and option_texts:
                                def _choice_key(value):
                                    value = unicodedata.normalize("NFKC", str(value or "")).lower()
                                    # 去除選項前綴與所有標點空白，只保留可比對的中英數。
                                    value = re.sub(r"^[\s\(\[]*[a-zA-Z0-9一二三四五六七八九十]+[\s\)\]\.、:：-]+", "", value)
                                    return "".join(ch for ch in value if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")

                                ans_key = _choice_key(ans_norm)
                                ans_compact = re.sub(r"\s+", "", ans_norm)
                                for i, opt_text in enumerate(option_texts[: len(radios)]):
                                    opt_clean = str(opt_text).strip()
                                    opt_key = _choice_key(opt_clean)
                                    opt_compact = re.sub(r"\s+", "", opt_clean)
                                    if (
                                        ans_compact
                                        and opt_compact
                                        and (ans_compact in opt_compact or opt_compact in ans_compact)
                                    ) or (
                                        ans_key
                                        and opt_key
                                        and (ans_key in opt_key or opt_key in ans_key)
                                    ):
                                        idx = i
                                        break

                            if idx is None and len(radios) == 2:
                                idx = 0
                                logger.debug(
                                    f"   ⚠️ 是非題答案無法比對，預設選第一個：{q_text[:30]!r} ans={ans_norm!r}"
                                )
                        else:
                            if len(radios) == 2:
                                idx = 0
                                logger.info(
                                    f"   🎲 是非題無答案，預設猜正確：{q_text[:30]!r}"
                                )
                                _missing.append({"type": "是非", "question": q_text, "options": option_texts})
                            else:
                                idx = random.randrange(len(radios))
                                logger.info(
                                    f"   🎲 單選題隨機作答（無資料，稍後回報）：{q_text[:30]!r}"
                                )
                                _missing.append({"type": "單選", "question": q_text, "options": option_texts})

                        if idx is None and ans is not None and len(radios) > 2:
                            ans_compact = _normalize_q(ans_norm)
                            for i, opt_text in enumerate(option_texts):
                                opt_clean = (opt_text or "").strip()
                                opt_compact = _normalize_q(opt_clean)
                                if ans_norm and opt_clean and (
                                    ans_norm in opt_clean
                                    or opt_clean in ans_norm
                                    or (
                                        ans_compact
                                        and opt_compact
                                        and (
                                            ans_compact in opt_compact
                                            or opt_compact in ans_compact
                                        )
                                    )
                                ):
                                    idx = i
                                    break

                        if idx is not None and idx < len(radios):
                            self.driver.execute_script(
                                "arguments[0].click();", radios[idx]
                            )
                            answered += 1
                        else:
                            logger.debug(
                                f"   ⚠️ 單選答案無法比對，略過：{q_text[:30]!r} ans={ans!r} options={option_texts!r}"
                            )
                            skipped += 1

                except Exception as e:
                    logger.debug(f"   ⚠️ 作答某題時發生錯誤: {e}")
                    skipped += 1

            logger.info(f"   📝 作答完成：{answered} 題已答，{skipped} 題略過")

            # ── 6b. 傳送缺題通知到 GAS Relay → Telegram（背景執行，不阻擋主流程）──
            if _missing:
                # 去重（同一次考試同一題可能出現多次）
                _seen = set()
                _missing_dedup = []
                for _m in _missing:
                    _key = _m.get("question", "")
                    if _key not in _seen:
                        _seen.add(_key)
                        _missing_dedup.append(_m)

                _GAS_URL = self.config.get(
                    "gas_url",
                    "https://script.google.com/macros/s/AKfycbzYUNM--zLlS8El6YR6lIiKerBIz1M6rL2gM8nTGicmEjfh_1TNiBo12YcVsb37J7Cl/exec"
                )
                _course_name = course.get("caption", "未知課程")
                _username = (
                    self.config.get("name")
                    or self.config.get("account")
                    or "匿名"
                )
                _payload = {
                    "course": _course_name,
                    "username": _username,
                    "missing": _missing_dedup,
                }

                import threading as _threading
                import requests as _req

                def _post_gas(url, payload):
                    try:
                        _req.post(url, json=payload, timeout=20)
                        logger.info(f"   📨 已回報 {len(payload['missing'])} 題缺題（{payload['username']}）")
                    except Exception as _e:
                        logger.debug(f"   缺題回報失敗: {_e}")

                _threading.Thread(
                    target=_post_gas, args=(_GAS_URL, _payload), daemon=True
                ).start()
                logger.info(f"   📨 缺題回報已背景送出（{len(_missing_dedup)} 題）")

            # ── 7. 點「送出答案，結束測驗」──
            # 頁面有兩個 submit 按鈕：
            #   - form[name='responseForm']（save_answer.php，target='submitTarget'）
            #     點擊後會出現 alert，接受後整頁跳轉到 view_result.php
            #   - form[name='buttonLine']（exam_start.php，target=''）→ 退出考試按鈕，不送答案
            # 需要點 responseForm 的按鈕。
            time.sleep(1)
            try:
                # 明確切回考試視窗（以防 step 6 中 JS click 意外改變了 focus）
                try:
                    self.driver.switch_to.window(exam_window)
                except Exception:
                    pass

                cur_url = self.driver.current_url
                logger.info(f"   📝 送出前 URL: {cur_url}")

                result = self.driver.execute_script(
                    """
                    var btns = document.querySelectorAll('input[type="submit"]');
                    var info = [];
                    var clicked = null;
                    // 優先找 form[name='responseForm'] 的 submit（送出答案）
                    for (var i = 0; i < btns.length; i++) {
                        var b = btns[i];
                        var style = window.getComputedStyle(b);
                        var hidden = (style.display === 'none' || style.visibility === 'hidden');
                        var formName = b.form ? (b.form.name || b.form.id || '') : '';
                        info.push({i: i, value: b.value, display: style.display, formName: formName, hidden: hidden});
                        if (!hidden && formName === 'responseForm' && clicked === null) {
                            b.click();
                            clicked = 'btn_' + i + '_responseForm';
                        }
                    }
                    // fallback: 點第一個非 hidden 的 submit
                    if (clicked === null) {
                        for (var j = 0; j < btns.length; j++) {
                            var b2 = btns[j];
                            var style2 = window.getComputedStyle(b2);
                            if (style2.display !== 'none' && style2.visibility !== 'hidden') {
                                b2.click();
                                clicked = 'btn_' + j + '_fallback';
                                break;
                            }
                        }
                    }
                    return {total: btns.length, info: info, clicked: clicked};
                    """
                )
                if result is None:
                    # None 通常表示 click 觸發了頁面跳轉（form submit 成功），繼續執行
                    logger.info(
                        "   📝 execute_script 返回 None（頁面已跳轉，推測 submit 成功）"
                    )
            except Exception as e:
                logger.warning(f"   ⚠️ 送出按鈕處理失敗: {e}")
                return False

            # ── 8. 處理「你確定要繳交嗎？」alert ──
            time.sleep(1)
            if self._accept_alert():
                logger.info("   📝 已確認繳交")
            else:
                logger.warning("   ⚠️ 未出現繳交確認框")

            # 等待結果頁載入
            time.sleep(3)

            # ── 9. 讀取成績，判斷是否通過 ──
            passed = self._read_exam_result(course, _ai_answered=_ai_answered)

            # ── 10. 不及格時嘗試讀取正確答案 ──
            # 考試 form submit 後，exam_window 已整頁跳轉到 view_result.php。
            # 直接對當前視窗呼叫 _harvest_correct_answers。
            # 若當前頁面不是 view_result.php，從 exam_start_url 推算後再 navigate。
            if not passed:
                time.sleep(1)
                try:
                    self.driver.switch_to.window(exam_window)
                    cur_exam_url = self.driver.current_url
                    # 若已在 view_result.php，直接讀取
                    if "view_result" in cur_exam_url:
                        self._harvest_correct_answers(cur_exam_url)
                    else:
                        # 從 exam_start_url 推算 view_result URL
                        # exam_start.php?{course_id}+{attempt}+{token}+0
                        # → view_result.php?{course_id}+{attempt}+{token}
                        m = re.search(r"exam_start\.php\?(.+?)\+0$", exam_start_url)
                        if m:
                            base = exam_start_url.split("/learn/")[0]
                            vr_url = f"{base}/learn/exam/view_result.php?{m.group(1)}"
                            logger.debug(f"   步驟10 推算 view_result URL: {vr_url!r}")
                            self.driver.get(vr_url)
                            time.sleep(2)
                            self._harvest_correct_answers(vr_url)
                        else:
                            logger.debug(
                                f"   步驟10 無法從 exam_start URL 推算 view_result（格式不符）: {exam_start_url!r}"
                            )
                except Exception as e:
                    logger.debug(f"   步驟10 公布答案失敗: {e}")

            return passed

        except Exception as e:
            logger.error(f"   ❌ 自動作答發生錯誤: {e}")
            return False

        finally:
            # 關閉所有多餘視窗（考試視窗、查看結果視窗），切回主視窗
            try:
                for h in list(self.driver.window_handles):
                    if h != main_window:
                        try:
                            self.driver.switch_to.window(h)
                            self.driver.close()
                        except Exception:
                            pass
            except Exception:
                pass
            try:
                self.driver.switch_to.window(main_window)
            except Exception:
                pass
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass

    def auto_questionnaire(self, course):
        """考試通過後，自動填寫問卷/評價。回傳 True=完成, False=失敗/跳過"""
        # 💡 防呆檢查：若該課程已填寫問卷（fill == "1"），直接跳過不重複送出
        if str(course.get("fill", "0")) == "1":
            logger.info(f"   ✅ 「{course.get('caption', '')}」問卷先前已完成，直接跳過。")
            return True
        if not course.get("write_questionnaire") and str(course.get("criteria_survey", "0")) in ("0", "", "False"):
            logger.info(f"   ℹ️ 「{course.get('caption', '')}」無問卷要求，直接跳過。")
            return True

        logger.info("   📋 開始自動填寫問卷流程...")
        main_window = self.driver.current_window_handle

        try:
            # ── 1. 切回主視窗，點左側 sidebar「問卷/評價」──
            self.driver.switch_to.window(main_window)
            self.driver.switch_to.default_content()

            clicked_q = False
            try:
                self.driver.switch_to.frame("mooc_sysbar")
                q_link = self.driver.find_element(
                    By.CSS_SELECTOR,
                    "a[href*='questionnaire/questionnaire_list.php']",
                )
                self.driver.execute_script("arguments[0].click();", q_link)
                logger.info("   📋 已點擊「問卷/評價」")
                clicked_q = True
            except Exception:
                # 嘗試在 default_content 尋找問卷連結
                self.driver.switch_to.default_content()
                try:
                    q_link = self.driver.find_element(
                        By.CSS_SELECTOR,
                        "a[href*='questionnaire'], a[href*='survey'], a[href*='feedback'], a[onclick*='questionnaire'], a[onclick*='survey']"
                    )
                    self.driver.execute_script("arguments[0].click();", q_link)
                    logger.info("   📋 已點擊「問卷/評價」")
                    clicked_q = True
                except Exception as e:
                    logger.warning(f"   ⚠️ 找不到問卷連結: {e}")
                    return False

            time.sleep(2)

            # ── 2. 切到 s_main frame（若為舊版架構） ──
            self.driver.switch_to.default_content()
            try:
                self.driver.switch_to.frame("s_main")
            except Exception:
                pass  # 若無 s_main，直接在 default_content 尋找按鈕

            time.sleep(1)

            # ── 2a. 檢查是否已填過（沒有「填寫問卷」按鈕則視為已完成）──
            pay_btns = self.driver.find_elements(
                By.CSS_SELECTOR, "div.process-btn.pay.active"
            )
            if not pay_btns:
                logger.info("   📋 無可填寫的問卷（已完成或不需填寫）")
                return True

            # ── 3. 點「填寫問卷」──
            self.driver.execute_script("arguments[0].click();", pay_btns[0])
            self._auto_hide_popups_if_needed(settle=True)
            logger.info("   📋 已點擊「填寫問卷」")
            time.sleep(3)

            # ── 4. 切換到新跳出的問卷視窗 ──
            all_handles = self.driver.window_handles
            q_window = next((h for h in all_handles if h != main_window), None)
            if not q_window:
                logger.warning("   ⚠️ 未偵測到問卷視窗")
                return False

            self.driver.switch_to.window(q_window)
            self._auto_hide_popups_if_needed(settle=True)
            logger.info("   📋 已切換至問卷視窗")
            time.sleep(2)

            # ── 5. 填寫問卷（radio 選 value=1，checkbox 選第一個，textarea 跳過）──
            rows = self.driver.find_elements(
                By.CSS_SELECTOR, "tr.bg03.font01, tr.bg04.font01"
            )
            answered = 0
            for row in rows:
                try:
                    # checkbox：勾選第一個（value="1"）
                    checkboxes = row.find_elements(
                        By.CSS_SELECTOR, "input[type='checkbox']"
                    )
                    if checkboxes:
                        self.driver.execute_script(
                            "arguments[0].click();", checkboxes[0]
                        )
                        answered += 1
                        continue

                    # radio：選第一個選項
                    radios = row.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                    if radios:
                        self.driver.execute_script("arguments[0].click();", radios[0])
                        answered += 1
                        continue

                    # textarea：跳過

                except Exception as e:
                    logger.debug(f"   ⚠️ 填寫某題時發生錯誤: {e}")

            logger.info(f"   📋 問卷填寫完成：{answered} 題已填")

            # ── 6. 點「確定繳交」──
            time.sleep(1)
            try:
                # 先嘗試精確 value 匹配，fallback 用 JS click 任何可見 submit
                submitted_q = self.driver.execute_script(
                    """
                    var btns = document.querySelectorAll('input[type="submit"]');
                    for (var i = 0; i < btns.length; i++) {
                        var style = window.getComputedStyle(btns[i]);
                        if (style.display !== 'none' && style.visibility !== 'hidden') {
                            btns[i].click();
                            return btns[i].value || 'btn_' + i;
                        }
                    }
                    return null;
                    """
                )
                if submitted_q:
                    logger.info(
                        f"   📋 已點擊「確定繳交」（{submitted_q!r}），等待確認框..."
                    )
                elif submitted_q is None:
                    # None = page navigated during click (submit succeeded)
                    logger.info("   📋 問卷已送出（頁面已跳轉）")
                else:
                    logger.warning("   ⚠️ 找不到「確定繳交」按鈕")
                    return False
            except Exception as e:
                logger.warning(f"   ⚠️ 找不到「確定繳交」按鈕: {e}")
                return False

            # ── 7. 處理「你確定要繳交嗎？」alert ──
            time.sleep(1)
            if self._accept_alert():
                logger.info("   📋 已確認繳交")
            else:
                logger.warning("   ⚠️ 未出現繳交確認框")

            # ── 8. 處理「更新完畢。」alert ──
            time.sleep(2)
            if self._accept_alert():
                logger.info("   📋 問卷已完成（更新完畢）")
            else:
                logger.warning("   ⚠️ 未出現「更新完畢」確認框")

            return True

        except Exception as e:
            logger.error(f"   ❌ 自動填寫問卷發生錯誤: {e}")
            return False

        finally:
            # 關閉問卷視窗，切回主視窗
            try:
                if self.driver.current_window_handle != main_window:
                    self.driver.close()
            except Exception:
                pass
            try:
                self.driver.switch_to.window(main_window)
            except Exception:
                pass

    def _get_driver_path(self):
        """取得 ChromeDriver 路徑，子類可覆寫此方法實作不同策略。"""
        return os.path.abspath(download_best_chromedriver())

    def init_engine(self):
        self.kill_orphan_drivers()
        try:
            driver_path = self._get_driver_path()
            if not os.path.exists(driver_path):
                logger.error(f"找不到驅動程式檔案: {driver_path}")
                return False

            logger.info("🚀 正在啟動輔助引擎...")
            options = Options()
            options.add_argument("--mute-audio")
            # 加速啟動
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-background-networking")
            options.add_argument("--disable-sync")
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")
            options.add_argument("--disable-default-apps")

            # ⭐ 關鍵：從 self.config 直接讀取
            headless_mode = self.config.get("headless", True)
            self._is_chrome_hidden = bool(headless_mode)

            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-background-timer-throttling")
            options.add_argument("--disable-backgrounding-occluded-windows")
            options.add_argument("--disable-renderer-backgrounding")

            if headless_mode:
                logger.info("⚙️ 使用無痕背景模式（背景執行，可隨時點擊「👁️ 顯示瀏覽器」查看）")
            else:
                logger.info("🖥️ 使用桌面顯示模式（視窗保持可見）")

            self._driver_service = Service(driver_path)
            if sys.platform == "win32":
                import subprocess
                self._driver_service.creation_flags = subprocess.CREATE_NO_WINDOW

            self.driver = webdriver.Chrome(
                service=self._driver_service, options=options
            )
            if self._driver_service.process:
                self._managed_pids.add(self._driver_service.process.pid)

            if headless_mode and sys.platform == "win32":
                set_driver_window_visibility(self.driver, False)

            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            self.wait = WebDriverWait(self.driver, 30)
            logger.info(f"✅ 引擎就緒：{Fore.GREEN}{self.version}{Style.RESET_ALL}")
            return True
        except Exception as e:
            logger.error(f"引擎初始化失敗: {e}")
            return False

    def sync_session(self) -> bool:
        if not self.driver:
            logger.error("sync_session: driver 尚未初始化，無法同步 session")
            return False
        try:
            self.http_session.cookies.clear()
            for cookie in self.driver.get_cookies():
                self.http_session.cookies.set(
                    cookie["name"], cookie["value"], domain=cookie["domain"]
                )

            # 動態獲取 User-Agent 並移除 Headless 標記
            raw_ua = self.driver.execute_script("return navigator.userAgent")
            clean_ua = raw_ua.replace("HeadlessChrome", "Chrome")

            self.http_session.headers.update(
                {
                    "User-Agent": clean_ua,
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Origin": "https://elearn.hrd.gov.tw",
                    "Referer": self.stat_url,
                }
            )
            return True
        except Exception as e:
            logger.error(f"sync_session 失敗: {e}")
            return False

    def _proactive_session_refresh(self) -> bool:
        """🧹 主動定期 Session 保養與全新登入：清除積累之髒污 Cookie，獲取全新 SSO 憑證。"""
        logger.info("🧹 執行主動定期 Session 保養：清理全站 Cookie 並重新登入...")
        try:
            if self.driver:
                try:
                    handles = list(self.driver.window_handles)
                    if len(handles) > 1:
                        for h in handles[1:]:
                            self.driver.switch_to.window(h)
                            self.driver.close()
                        self.driver.switch_to.window(handles[0])
                except Exception:
                    pass
                try:
                    self.driver.delete_all_cookies()
                except Exception:
                    pass

            self.http_session.cookies.clear()
            login_ok = self.login()
            if login_ok:
                self.sync_session()
                self._last_session_refresh_time = time.time()
                self._course_relogin_counts.clear()
                logger.info("✅ 主動 Session 保養與全新登入完成，憑證已刷新。")
                return True
            else:
                logger.warning("⚠️ 主動 Session 保養重登失敗，稍後將依常規機制重試。")
                return False
        except Exception as e:
            logger.warning(f"⚠️ 主動 Session 保養發生異常: {e}")
            return False

    @staticmethod
    def _is_logout_text(text) -> bool:
        text = str(text or "")
        if not text:
            return False
        # 排除正常的 MOOCs 課程/首頁路徑
        if "mooc/index.php" in text and "login" not in text.lower() and "clogin" not in text.lower():
            return False
        return any(kw in text for kw in ("帳號閒置", "系統閒置", "重新登入", "請先登入", "請登入", "登入後再學習", "登入會員", "clogin.aspx", "sys_login.php", "/login.php"))

    def _accept_alert_if_present(self) -> str:
        try:
            alert = self.driver.switch_to.alert
            alert_text = alert.text
            alert.accept()
            return alert_text or ""
        except NoAlertPresentException:
            return ""
        except Exception as e:
            return str(e)

    def fetch_course_list(self, year=None):
        cur_year = year or time.strftime("%Y")
        courses_map = {}
        # 💡 查詢所有課程類型：包含單門(single)、MOOCs(mooc/moocs)、開放式(open)、微學習(micro)、組裝(package)、直播(live)與不限類型("")
        # 同時涵蓋當前年度與跨年度("")課程，確保所有已選修之 MOOCs 與一般課程皆 100% 納入
        type_list = ["", "mooc", "moocs", "single", "open", "micro", "package", "live"]
        year_list = [cur_year, ""]

        for y in year_list:
            for c_type in type_list:
                for page in range(1, 35):
                    payload = f"year={y}&keyword=&course_type={c_type}&page={page}&orderby=&sort="
                    try:
                        resp = self.http_session.post(
                            self.api_url, data=payload, timeout=10
                        )
                        data = resp.json().get("data", [])
                        if not data or len(data) == 0:
                            break
                        for item in data:
                            cid = str(item.get("course_id", "") or item.get("id", ""))
                            key = cid or item.get("caption", "")
                            if key and key not in courses_map:
                                courses_map[key] = item
                    except Exception as e:
                        logger.debug(f"讀取 [y={y}, type={c_type}] 第 {page} 頁課程: {e}")
                        break
        return list(courses_map.values())

    def fetch_course_list_checked(self, year=None):
        courses = self.fetch_course_list(year)
        count = len(courses)
        should_retry = 0 < count < 5
        if self._last_course_count and 0 < count < self._last_course_count:
            should_retry = True

        if should_retry:
            logger.warning(
                f"⚠️ 課程 API 只回 {count} 筆"
                + (
                    f"（前次 {self._last_course_count} 筆）"
                    if self._last_course_count
                    else ""
                )
                + "，先同步 session 後重抓。"
            )
            try:
                self.sync_session()
            except Exception:
                pass
            time.sleep(2)
            try:
                retry_courses = self.fetch_course_list(year)
            except Exception:
                retry_courses = courses
            if len(retry_courses) > count:
                logger.info(f"✅ 課程 API 重抓成功：{count} → {len(retry_courses)} 筆")
                courses = retry_courses
                count = len(courses)

        if count > self._last_course_count:
            self._last_course_count = count
        return courses

    def _is_open_course(self, course):
        course_type = str(course.get("course_type", "") or "").strip().lower()
        if course_type:
            return any(k in course_type for k in [
                "開放式", "單門課程", "微學習", "組合課程", "單門",
                "組裝課程", "套裝課程", "直播課程", "直播", "隨選視訊",
                "mooc", "moocs", "磨課師", "一般課程"
            ])
        course_type_cd = str(course.get("course_type_cd", "") or "").strip().lower()
        if course_type_cd:
            return any(k in course_type_cd for k in [
                "single", "open", "micro", "package", "live", "broadcast", "mooc", "moocs"
            ])
        return True

    def _is_playable_course(self, course):
        """檢查是否為具有實體播放時數之單門/微學習/直播課程（排除純組裝套裝容器本身）。"""
        course_type = str(course.get("course_type", "") or "").strip()
        course_type_cd = str(course.get("course_type_cd", "") or "").strip().lower()
        if course_type in {"組裝課程", "套裝課程"} or course_type_cd == "package":
            return False
        return True

    def _is_exam_passed(self, c):
        """檢查該課程之測驗是否已達到及格標準。"""
        # 1. 取得通過狀態文字與標記
        pass_status = str(
            c.get("exam_pass_status", "")
            or c.get("pass_status", "")
            or c.get("status_text", "")
            or ""
        ).strip().lower()

        # 若平臺明確標註未通過/不及格/未達標，必定為未通過（如臺灣藍碳 60 分未達 75 分門檻）
        if any(w in pass_status for w in ["未通過", "不及格", "fail"]):
            return False

        # 2. 取得及格門檻標準（預設 60 分，支援 criteria_exam_score, criteria_score, pass_score 等欄位）
        pass_score = 60.0
        for f in [
            "criteria_exam_score",
            "criteria_score",
            "pass_score",
            "exam_pass_score",
            "criteria_test_score",
        ]:
            val = c.get(f)
            if val is not None and str(val).strip() not in ("", "--", "None", "null", "0", "0.0"):
                try:
                    pass_score = float(val)
                    break
                except Exception:
                    pass

        # 3. 若有測驗分數，比對是否達到及格門檻
        score_val = c.get("exam_score")
        if score_val is not None and str(score_val).strip() not in ("", "--", "None", "null", "未填", "未測驗"):
            try:
                score_num = float(score_val)
                if score_num < pass_score:
                    return False
                return True
            except Exception:
                pass

        # 4. 明確測驗通過標記
        if pass_status in ["1", "pass", "passed", "已通過", "及格"]:
            return True

        # 5. 若無測驗分數且有測驗要求（criteria_exam_score > 0 或 write_exam == 1 或 exam_exists == 1）
        has_exam_req = (
            (c.get("criteria_exam_score") and str(c.get("criteria_exam_score")).strip() not in ("", "0", "0.0", "--"))
            or str(c.get("write_exam", "0")) == "1"
            or str(c.get("exam_exists", "0")) == "1"
        )
        if has_exam_req:
            return False

        # 無任何測驗要求之課程視為測驗通過
        return True

    def _is_course_completed(self, c) -> bool:
        """檢查課程是否已由平臺確認全數修畢（時數達標且通過，或時數/測驗/問卷全數完成）。"""
        rss_sec = to_sec(c.get("rss", "00:00:00"))
        crit_sec = to_sec(c.get("criteria_content_hour", "00:00:00"))

        # 1. 基礎閱讀時數必須達標 100%
        if crit_sec > 0 and rss_sec < crit_sec:
            return False

        # 2. 若平臺明確標註未通過/不及格
        pass_status = str(
            c.get("exam_pass_status", "")
            or c.get("pass_status", "")
            or c.get("status_text", "")
            or ""
        ).strip().lower()
        if any(w in pass_status for w in ["未通過", "不及格", "fail"]):
            return False

        # 3. 若有測驗要求，測驗必須及格（不可只依賴 status=1 報名狀態）
        if not self._is_exam_passed(c):
            return False

        # 4. 若有問卷要求，問卷必須已填寫
        q_req = bool(c.get("write_questionnaire", ""))
        if q_req and str(c.get("fill", "0")) != "1":
            return False

        return True

    def _mark_exam_manual_review(self, course, reason):
        """記錄本次無法完成的測驗，避免重複卡住且禁止宣告全部完成。"""
        course_id = str(course.get("course_id", ""))
        if course_id:
            self._exam_manual_review[course_id] = {
                "caption": course.get("caption", course_id),
                "reason": reason,
            }
        logger.warning(f"   ⚠️ 測驗待處理：{course.get('caption', course_id)}｜{reason}")

    def auto_enroll_package_subcourses(self, courses) -> bool:
        """組裝課程子課程缺漏時的手動修復備援；正常執行流程不會自動呼叫。"""
        if not self.driver or not self.running:
            return False
        if getattr(self, "_package_preflight_completed", False):
            return False

        packages_dict = {}
        dashboard_completed_ids = set()

        # 優先從「我的課程儀表板 -> 組裝課程 (tab=4)」遍歷所有分頁掃描進行中之組裝課程
        try:
            self.driver.get("https://elearn.hrd.gov.tw/mooc/user/learn_dashboard.php?tab=4")
            self.safe_sleep(3)
            for dash_page in range(1, 31):
                if not self.running:
                    break
                logger.info(f"   🔎 組裝課程儀表板掃描：第 {dash_page} 頁")
                pkg_cards = self.driver.execute_script("""
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
                """)
                if pkg_cards:
                    for pc in pkg_cards:
                        pid = str(pc.get("id", ""))
                        if not pid:
                            continue
                        if pc.get("is100"):
                            dashboard_completed_ids.add(pid)
                            logger.info(f"   ⏩ 組裝課程【{pc.get('title')}】進度已達 100%（全數修畢），直接略過。")
                        elif pid not in self._expanded_packages:
                            packages_dict[pid] = pc.get("title") or pid

                has_next = self.driver.execute_script("""
                    var nextBtns = document.querySelectorAll(
                        '.pagination a, .pagination button, .pagination input, .pagination span, .page-link, a.next, li.next a, [aria-label="Next"], [aria-label="下一頁"], [rel="next"], [class*="next"], [class*="Next"]'
                    );
                    for (var i = 0; i < nextBtns.length; i++) {
                        var btn = nextBtns[i];
                        var t = (btn.innerText || btn.value || btn.textContent || '').trim();
                        var label = (btn.getAttribute('aria-label') || btn.getAttribute('title') || '').trim();
                        var className = String(btn.className || '') + ' ' + String(btn.parentElement ? btn.parentElement.className : '');
                        var hasRightIcon = !!btn.querySelector('.fa-angle-right, .fa-chevron-right, .glyphicon-chevron-right, .icon-right, .fa-step-forward, .fa-forward');
                        var disabled = btn.classList.contains('disabled') ||
                                       (btn.parentElement && btn.parentElement.classList.contains('disabled')) || btn.disabled ||
                                       btn.getAttribute('aria-disabled') === 'true';
                        if (!disabled && (
                            t === '>' || t === '>|' || t === '›' || t === '»' || t.indexOf('下一頁') !== -1 || t.indexOf('Next') !== -1 ||
                            label.indexOf('下一頁') !== -1 || label.indexOf('Next') !== -1 ||
                            /(^|\\s)(next|pagination-next)(\\s|$)/i.test(className) ||
                            hasRightIcon || t === String(arguments[0] + 1)
                        )) {
                            btn.click();
                            return {clicked: true, text: t || label || '圖示下一頁'};
                        }
                    }
                    return {clicked: false, text: ''};
                """, dash_page)
                if not has_next or not has_next.get("clicked"):
                    break
                logger.info(f"   ➡️ 已切換組裝課程儀表板下一頁：{has_next.get('text')}")
                self.safe_sleep(2)
        except Exception as e:
            logger.debug(f"組裝課程儀表板 (tab=4) 掃描略過: {e}")

        # 無論儀表板掃到幾筆，一律與 API 回傳的組裝課程聯集去重，避免漏課。
        for c in courses:
            c_id = str(c.get("course_id", "") or c.get("id", ""))
            c_caption = str(c.get("caption", ""))
            c_type = str(c.get("course_type", ""))
            c_type_cd = str(c.get("course_type_cd", "")).lower()

            if (
                c_type_cd == "package"
                or any(k in c_type for k in ["組裝", "套裝", "組合"])
                or any(k in c_caption for k in ["組裝", "套裝", "組合"])
            ) and c_id and c_id not in dashboard_completed_ids and c_id not in self._expanded_packages:
                packages_dict.setdefault(c_id, c_caption or c_id)

        if not packages_dict:
            self._package_preflight_completed = True
            return False

        expanded_any = False
        for pkg_id, pkg_name in list(packages_dict.items()):
            if not self.running:
                break
            if pkg_id in self._expanded_packages:
                continue

            try:
                # ── 步驟 A：進入母套裝頁面 ──
                pkg_url = f"https://elearn.hrd.gov.tw/info/{pkg_id}"
                self.driver.get(pkg_url)
                self.safe_sleep(3)

                logger.info(f"📦 【母課程】ID={pkg_id}｜{pkg_name}，正在展開內部子課程...")

                # ── 步驟 B：切換至「課程資訊」頁籤 ──
                switched_tab = self.driver.execute_script("""
                    var tabs = document.querySelectorAll('a, li, button, span, .nav-tabs li');
                    for (var i = 0; i < tabs.length; i++) {
                        var t = (tabs[i].innerText || tabs[i].textContent || '').trim();
                        if (t.indexOf('課程資訊') !== -1) {
                            tabs[i].click();
                            return true;
                        }
                    }
                    return false;
                """)
                if switched_tab:
                    logger.info("   📑 已切換至「課程資訊」頁籤")
                self.safe_sleep(2)

                # ── 步驟 C：萃取「課程清單」中所有子課程連結（排除右側推薦） ──
                sub_courses = self.driver.execute_script("""
                    var pkgId = arguments[0];
                    var results = [];
                    var seen = {};

                    var mainArea = document.querySelector('.course-list, .tab-content, #tab2, #collapseList, .content-container, .main-content') || document.body;
                    var links = mainArea.querySelectorAll('a');

                    for (var i = 0; i < links.length; i++) {
                        var a = links[i];
                        var href = a.href || '';
                        var text = (a.innerText || a.textContent || '').trim();

                        var inSidebar = a.closest('.sidebar, .recommend, .col-md-4, .col-lg-3, .col-sm-4, #recommend, .side-bar');
                        if (inSidebar) continue;

                        if (href && (href.indexOf('/info/') !== -1 || href.indexOf('course_id=') !== -1)) {
                            if (pkgId && href.indexOf('/info/' + pkgId) !== -1) continue;
                            if (!seen[href]) {
                                seen[href] = true;
                                results.push({href: href, text: text});
                            }
                        }
                    }
                    return results;
                """, pkg_id)

                if sub_courses:
                    logger.info(f"   📋 【子課程清單】母課程 ID={pkg_id}，共 {len(sub_courses)} 門。")
                    processed_subcourses = 0
                    for s_idx, sub in enumerate(sub_courses):
                        if not self.running:
                            break
                        sub_url = sub.get("href", "")
                        sub_text = sub.get("text", f"子課程 {s_idx + 1}")
                        logger.info(f"   👉 【子課程 {s_idx + 1}/{len(sub_courses)}】{sub_text[:35]}")

                        try:
                            self.driver.get(sub_url)
                            self.safe_sleep(2)
                            result = self.driver.execute_script("""
                                var statusBox = document.querySelector('.course-status, [class*="status"], .sidebar, .col-md-4, .col-lg-3, div[class*="sidebar"]') || document.body;
                                var statusText = statusBox.innerText || '';

                                // 1. 檢查右側狀態欄是否顯示「通過狀態：已通過」
                                if (
                                    statusText.indexOf('通過狀態：已通過') !== -1 ||
                                    statusText.indexOf('通過狀態: 已通過') !== -1 ||
                                    (statusText.indexOf('已通過') !== -1 && statusText.indexOf('閱讀時數') !== -1)
                                ) {
                                    return {action: 'already_passed', text: '已通過'};
                                }

                                // 2. 優先尋找「報名課程」按鈕
                                var btns = document.querySelectorAll('button, a.btn, a, input[type="button"], input[type="submit"]');
                                for (var i = 0; i < btns.length; i++) {
                                    var t = (btns[i].innerText || btns[i].value || btns[i].textContent || '').trim();
                                    if (
                                        t === '報名課程' ||
                                        t === '我要報名' ||
                                        t === '確認報名' ||
                                        t === '選課' ||
                                        t === '加入課程' ||
                                        (t.indexOf('報名') !== -1 && t.indexOf('名額') === -1)
                                    ) {
                                        btns[i].click();
                                        return {action: 'enrolled', text: t};
                                    }
                                }

                                // 3. 檢查是否已在學習中（顯示「上課去」）
                                for (var i = 0; i < btns.length; i++) {
                                    var t = (btns[i].innerText || btns[i].value || btns[i].textContent || '').trim();
                                    if (['上課去', '進入課程', '開始上課'].indexOf(t) !== -1) {
                                        return {action: 'in_progress', text: t};
                                    }
                                }

                                return {action: 'none', text: ''};
                            """)
                            self.safe_sleep(1.5)
                            self._accept_alert_if_present()

                            if not result:
                                logger.info("      ℹ️ 子課程已在研習清單中或已自動選入")
                            elif result.get("action") == "already_passed":
                                processed_subcourses += 1
                                logger.info(f"      ✅ 子課程【{sub_text[:30]}】已取得認證（通過狀態：已通過），跳過。")
                            elif result.get("action") == "enrolled":
                                logger.info(f"      📝 報名前狀態：{result.get('text')}；正在回讀平台狀態確認。")
                                self.driver.get(sub_url)
                                self.safe_sleep(2)
                                post_result = self.driver.execute_script("""
                                    var bodyText = document.body ? document.body.innerText : '';
                                    var btns = document.querySelectorAll('button, a.btn, a, input[type="button"], input[type="submit"]');
                                    var labels = [];
                                    for (var i = 0; i < btns.length; i++) {
                                        var t = (btns[i].innerText || btns[i].value || btns[i].textContent || '').trim();
                                        if (t) labels.push(t);
                                    }
                                    var inProgress = labels.some(function(t) {
                                        return ['上課去', '進入課程', '開始上課'].indexOf(t) !== -1;
                                    });
                                    var stillEnroll = labels.some(function(t) {
                                        return t === '報名課程' || t === '我要報名' || t === '確認報名' || t === '選課' || t === '加入課程';
                                    });
                                    var passed = bodyText.indexOf('通過狀態：已通過') !== -1 ||
                                                 bodyText.indexOf('通過狀態: 已通過') !== -1;
                                    return {in_progress: inProgress, still_enrollable: stillEnroll, passed: passed, buttons: labels.slice(0, 12)};
                                """)
                                if post_result.get("in_progress") or post_result.get("passed"):
                                    processed_subcourses += 1
                                    logger.info("      ✅ 報名後驗證成功：已轉為可上課／已通過狀態。")
                                else:
                                    logger.warning(
                                        f"      ⚠️ 報名後未確認成功（仍可報名={post_result.get('still_enrollable')}，按鈕={post_result.get('buttons')}），保留供下一輪重試。"
                                    )
                            elif result.get("action") == "in_progress":
                                processed_subcourses += 1
                                logger.info(f"      ℹ️ 子課程已在研習清單中（{result.get('text')}），進行中。")
                            else:
                                logger.warning("      ⚠️ 無法判斷子課程目前狀態，保留供下一輪重試。")

                        except Exception as sub_e:
                            logger.warning(f"      ⚠️ 子課程登記異常: {sub_e}")

                    if processed_subcourses == len(sub_courses):
                        self._expanded_packages.add(pkg_id)
                        expanded_any = True
                        logger.info(f"   ✅ 母課程 ID={pkg_id} 已處理 {processed_subcourses}/{len(sub_courses)} 門子課程，本次不再重複展開。")
                    else:
                        logger.warning(f"   ⚠️ 母課程 ID={pkg_id} 僅處理 {processed_subcourses}/{len(sub_courses)} 門子課程，保留供下一輪重試。")

                else:
                    logger.warning(f"   ⚠️ 未能從套裝 {pkg_name} 課程資訊中解析出子課程連結，保留供下一輪重試。")

                # ── 步驟 D：返回母套裝頁面點擊「上課去」確保整體啟動 ──
                try:
                    self.driver.get(pkg_url)
                    self.safe_sleep(2)
                    self.driver.execute_script("""
                        var btns = document.querySelectorAll('button, a.btn, a');
                        for (var i = 0; i < btns.length; i++) {
                            var t = (btns[i].innerText || btns[i].textContent || '').trim();
                            if (['上課去', '進入課程', '報名'].some(k => t.indexOf(k) !== -1)) {
                                btns[i].click();
                                break;
                            }
                        }
                    """)
                    self.safe_sleep(2)
                    self._accept_alert_if_present()
                except Exception:
                    pass

            except Exception as e:
                logger.warning(f"⚠️ 展開組裝課程 {pkg_name} 時發生異常: {e}")

        # 展開完畢後返回統計頁並同步 session
        if expanded_any:
            try:
                self.driver.get(self.stat_url)
                self.safe_sleep(2)
                self.sync_session()
            except Exception:
                pass

        self._package_preflight_completed = True
        logger.info("📦 組裝課程前置檢查完成；本次執行不再重複掃描。")
        return expanded_any

    def recover_login_session(self, reason="session 失效") -> bool:
        logger.warning(f"🔄 {reason}，嘗試重新登入並同步 API session...")
        try:
            self._accept_alert_if_present()
        except Exception:
            pass
        try:
            self.driver.get(self.stat_url)
            self.safe_sleep(2)
        except Exception:
            pass
        if not self.login():
            logger.error("❌ 重新登入失敗，無法恢復 API session。")
            return False
        if not self.sync_session():
            logger.error("❌ 重新登入後 session 同步失敗。")
            return False
        logger.info("✅ 重新登入並同步 session 完成。")
        return True

    def _resolve_hahow_device_sessions(self) -> bool:
        """若外購平臺 Hahow 遇到登入裝置數量上限（device_sessions），自動登出舊裝置並點擊『繼續』"""
        if not self.driver:
            return False
        curr_h = None
        try:
            curr_h = self.driver.current_window_handle
        except Exception:
            pass

        try:
            for handle in list(self.driver.window_handles):
                try:
                    self.driver.switch_to.window(handle)
                    url = self.driver.current_url or ""
                    if "hahow.in" in url:
                        handled = self.driver.execute_script("""
                            var text = document.body ? document.body.innerText : '';
                            if (location.href.indexOf('device_sessions') !== -1 || text.indexOf('登入數量上限') !== -1 || text.indexOf('登出下面其中') !== -1) {
                                var logoutBtns = document.querySelectorAll('button, a.btn');
                                for (var i = 0; i < logoutBtns.length; i++) {
                                    var t = (logoutBtns[i].innerText || logoutBtns[i].textContent || '').trim();
                                    if (t === '登出') {
                                        logoutBtns[i].click();
                                        break;
                                    }
                                }
                                return true;
                            }
                            return false;
                        """)
                        if handled:
                            time.sleep(1.5)
                            self.driver.execute_script("""
                                var continueBtns = document.querySelectorAll('button, a.btn');
                                for (var j = 0; j < continueBtns.length; j++) {
                                    var ct = (continueBtns[j].innerText || continueBtns[j].textContent || '').trim();
                                    if (ct === '繼續' && !continueBtns[j].disabled) {
                                        continueBtns[j].click();
                                        break;
                                    }
                                }
                            """)
                            logger.info("   🔓 偵測到 Hahow 裝置數量上限，已自動排除舊裝置並點擊「繼續」進入平臺！")
                            time.sleep(2)
                            return True
                except Exception:
                    continue
        finally:
            if curr_h:
                try:
                    self.driver.switch_to.window(curr_h)
                except Exception:
                    pass
        return False

    def find_classroom_window(self):
        """Return the browser window that owns the course frame tree or MOOCs/Hahow player."""
        if not self.driver:
            return None
        self._resolve_hahow_device_sessions()
        try:
            handles = list(self.driver.window_handles)
        except Exception:
            return None

        # 1. 第一優先：尋找傳統 frameset 教室（s_catalog / pathtree）
        for handle in reversed(handles):
            try:
                self.driver.switch_to.window(handle)
                self.driver.switch_to.default_content()
                self.driver.switch_to.frame("s_catalog")
                self.driver.switch_to.frame("pathtree")
                self.driver.switch_to.default_content()
                return handle
            except Exception:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
                continue

        # 2. 第二優先：尋找外購平臺 / 現代播放器視窗（如 Hahow, /learn/, /controllers/, 具備 <video> 或播放器之獨立分頁）
        for handle in reversed(handles):
            try:
                self.driver.switch_to.window(handle)
                self.driver.switch_to.default_content()
                url = self.driver.current_url or ""
                # 排除純登入頁、首頁或學習概況/儀表板總覽頁與純介紹頁（/info/）
                if any(k in url for k in ["Clogin.aspx", "egov_login.php", "learn_stat.php", "learn_dashboard.php", "mooc/index.php", "/info/"]):
                    continue
                # 若 URL 包含課程相關路徑（hahow、learn、course、controllers）或頁面含有播放器特徵
                is_player_url = any(k in url for k in ["hahow.in", "/learn/", "/course/", "/controllers/", "player"])
                has_player_or_units = self.driver.execute_script("""
                    return !!(
                        document.querySelector('video, audio, .video-js, #player, .player, [class*="unit"], [class*="chapter"], [class*="lecture"], [class*="LectureItem"], [class*="node"], a[onclick*="play"]') ||
                        window.API || window.LMSCommit
                    );
                """)
                if is_player_url or has_player_or_units:
                    return handle
            except Exception:
                continue

        # 3. 第三優先：若有多個視窗且非 stat/首頁/登入/介紹頁面，回傳最後開啟之視窗作為 fallback
        if len(handles) > 1:
            for handle in reversed(handles):
                try:
                    self.driver.switch_to.window(handle)
                    url = self.driver.current_url or ""
                    if not any(
                        k in url
                        for k in [
                            "learn_stat.php",
                            "learn_dashboard.php",
                            "mooc/index.php",
                            "Clogin.aspx",
                            "egov_login.php",
                            "/info/",
                        ]
                    ):
                        return handle
                except Exception:
                    pass

        # 4. 保底：若只有 1 個視窗且非 stat/首頁/登入/介紹頁面
        if len(handles) == 1:
            try:
                self.driver.switch_to.window(handles[0])
                url = self.driver.current_url or ""
                if not any(
                    k in url
                    for k in [
                        "learn_stat.php",
                        "learn_dashboard.php",
                        "mooc/index.php",
                        "Clogin.aspx",
                        "egov_login.php",
                        "/info/",
                    ]
                ):
                    return handles[0]
            except Exception:
                pass

        return None

    def _wait_for_redirect_and_sync(
        self, success_msg: str, check_no_login: bool = False
    ) -> bool:
        """等待重新導向至 elearn.hrd.gov.tw 後同步 session（登入共用邏輯）"""
        for _ in range(60):
            if not self.running:
                logger.info("🛑 使用者手動停止（登入中）")
                return False
            try:
                url = self.driver.current_url
            except UnexpectedAlertPresentException:
                alert_text = self._accept_alert_if_present()
                if alert_text:
                    logger.info(f"ℹ️ 登入提示：{alert_text}")
                time.sleep(0.5)
                continue
            url_ok = "elearn.hrd.gov.tw" in url and (
                not check_no_login or "login" not in url
            )
            if url_ok:
                logger.info(success_msg)
                self.driver.get(self.stat_url)
                if not self.safe_sleep(5):
                    return False
                self.sync_session()
                return True
            time.sleep(0.5)
        return False

    def login(self):
        login_type = self.config.get("login_type", "ecpa")

        if login_type == "egov":
            return self.login_egov()
        else:
            return self.login_ecpa()

    def login_ecpa(self):
        try:
            logger.info("🔑 正在對接 eCPA 登入系統...")
            self.driver.get(self.ecpa_url)
            self.wait.until(EC.presence_of_element_located((By.ID, "aliasid")))

            user_f = self.driver.find_element(By.ID, "aliasid")
            pass_f = self.driver.find_element(By.ID, "pas")

            for c in self.config["account"]:
                user_f.send_keys(c)
                time.sleep(random.uniform(0.01, 0.03))

            for c in self.config["password"]:
                pass_f.send_keys(c)
                time.sleep(random.uniform(0.01, 0.03))

            self.driver.execute_script(
                "document.querySelector('#idarea button').click();"
            )

            return self._wait_for_redirect_and_sync(
                "✅ 系統身分驗證成功！", check_no_login=True
            )

        except Exception as e:
            logger.error(f"登入異常: {e}")
            return False

    def login_egov(self):
        try:
            logger.info("🔑 使用我的E政府登入...")

            self.driver.get(
                "https://www.cp.gov.tw/portal/Clogin.aspx?ReturnUrl=https://elearn.hrd.gov.tw/egov_login.php&ver=Simple&Level=1"
            )
            time.sleep(2)

            # 💡 檢查點：若已經自動完成 SSO 導回 elearn.hrd.gov.tw，直接同步 Session
            cur_url = self.driver.current_url
            if "elearn.hrd.gov.tw" in cur_url and "egov_login" not in cur_url and "mooc/index.php" not in cur_url:
                logger.info("✅ 偵測到 E政府已具備有效 SSO 授權，直接同步 Session。")
                return self.sync_session()

            # 多重防禦性定位帳號欄位（給予最多 12 秒等待政府入口網載入）
            user_f = None
            user_selectors = [
                (By.ID, "AccountPassword_simple_txt_account"),
                (By.CSS_SELECTOR, "input[placeholder*='帳號']"),
                (By.CSS_SELECTOR, "input[type='text']"),
                (By.CSS_SELECTOR, "input[id*='account']"),
            ]
            for by_type, val in user_selectors:
                try:
                    user_f = WebDriverWait(self.driver, 12).until(EC.presence_of_element_located((by_type, val)))
                    if user_f and user_f.is_displayed():
                        break
                except Exception:
                    pass

            # 多重防禦性定位密碼欄位
            pass_f = None
            pass_selectors = [
                (By.ID, "AccountPassword_simple_txt_password"),
                (By.CSS_SELECTOR, "input[type='password']"),
                (By.CSS_SELECTOR, "input[placeholder*='密碼']"),
                (By.CSS_SELECTOR, "input[id*='password']"),
            ]
            for by_type, val in pass_selectors:
                try:
                    pass_f = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((by_type, val)))
                    if pass_f and pass_f.is_displayed():
                        break
                except Exception:
                    pass

            if not user_f or not pass_f:
                # 若仍找不到且已在 elearn 平台，再次嘗試同步
                if "elearn.hrd.gov.tw" in self.driver.current_url:
                    return self.sync_session()
                logger.error(f"❌ 找不到我的E政府帳號或密碼輸入框（當前頁面: {self.driver.current_url}）")
                return False

            user_f.clear()
            user_f.send_keys(str(self.config["account"]))
            time.sleep(0.5)

            pass_f.clear()
            pass_f.send_keys(str(self.config["password"]))
            time.sleep(0.5)

            # 登入按鈕多重定位
            login_btn = None
            btn_selectors = [
                (By.ID, "AccountPassword_simple_btn_LoginHandler"),
                (By.CSS_SELECTOR, "input[type='submit']"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.CSS_SELECTOR, "a.btn-login"),
                (By.XPATH, "//a[contains(text(), '登入')]"),
                (By.XPATH, "//button[contains(text(), '登入')]"),
                (By.XPATH, "//input[@value='登入']"),
            ]
            for by_type, val in btn_selectors:
                try:
                    btns = self.driver.find_elements(by_type, val)
                    for b in btns:
                        if b.is_displayed():
                            login_btn = b
                            break
                    if login_btn:
                        break
                except Exception:
                    pass

            if login_btn:
                try:
                    login_btn.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", login_btn)
            else:
                pass_f.submit()

            return self._wait_for_redirect_and_sync("✅ E政府登入成功")

        except Exception as e:
            logger.error(f"E政府登入失敗: {e}")
            return False

    def get_progress_api(self, course_id):
        cache_key = str(course_id)
        now = time.time()
        cached = getattr(self, "_progress_cache", {})
        if cache_key in cached:
            result, ts = cached[cache_key]
            if now - ts < 30:
                return result
        try:
            current_year = time.strftime("%Y")
            # 多頁查詢，避免課程在 page>1 時查不到進度
            for _page in range(1, 21):
                payload = f"year={current_year}&keyword=&course_type=single&page={_page}&orderby=&sort="
                resp = self.http_session.post(
                    self.api_url, data=payload, timeout=10
                )
                data = resp.json().get("data", [])
                for c in data:
                    if str(c.get("course_id")) == str(course_id):
                        cur_s = to_sec(c.get("rss", "00:00:00"))
                        target_s = to_sec(
                            c.get("criteria_content_hour", "00:30:00")
                        ) * self.config.get("target_percentage", 1.0)
                        result = {
                            "cur_str": sec_to_str(cur_s),
                            "target_str": sec_to_str(target_s),
                            "cur_sec": cur_s,
                            "target_sec": target_s,
                        }
                        if not hasattr(self, "_progress_cache"):
                            self._progress_cache = {}
                        self._progress_cache[cache_key] = (result, now)
                        return result
                if len(data) < 50:
                    break  # 最後一頁，不再繼續
        except Exception as e:
            logger.debug(f"進度查詢失敗: {e}")
        return None

    def study_process(self, course):
        if not self._is_open_course(course) or not self._is_playable_course(course):
            logger.info(
                f"⏭️ 略過非播放/組裝容器課程：{course.get('caption', course.get('course_id', '未知課程'))}"
            )
            return "SKIP"

        logger.info(
            f"📖 [{self.current_idx}/{self.total_courses}] 正在協助研習：{Fore.YELLOW}{course['caption']}{Style.RESET_ALL}"
        )
        session_start = time.time()
        last_prog_sec = -1
        last_prog_time = time.time()

        try:
            # ⭐ 檢查點 1
            if not self.running:
                logger.info("🛑 使用者手動停止（study_process 開始）")
                return "STOP"

            # 確保 driver 在 stat_url（gotoCourse 函式只在該頁面定義）
            self.driver.get(self.stat_url)
            self._auto_hide_popups_if_needed(settle=True)
            if not self.safe_sleep(3):
                return "STOP"

            orig_handles = list(self.driver.window_handles)
            self.driver.execute_script(f"gotoCourse({course['course_id']})")
            self._auto_hide_popups_if_needed(settle=True)
            if not self.safe_sleep(4):
                return "STOP"

            # ⭐ 進入課程後先攔截 alert（如「您非本門課的學生」、「尚未上架且非上課期間」等）
            try:
                WebDriverWait(self.driver, 3).until(EC.alert_is_present())
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                alert.accept()
                logger.warning(f"⚠️ gotoCourse 後偵測到 Alert：{alert_text}")
                if any(
                    kw in alert_text
                    for kw in [
                        "非本門課",
                        "無法上課",
                        "無權限",
                        "不開放",
                        "未選課",
                        "尚未上架",
                        "已下架",
                        "直播已結束",
                        "尚未開始",
                        "非上課期間",
                        "非開放期間",
                        "無法進入教室",
                    ]
                ):
                    logger.warning(f"⚠️ 此課程無法進入（{alert_text}），永久跳過。")
                    self._completed_in_session.add(str(course.get("course_id", "")))
                    return "SKIP"
                elif any(kw in alert_text for kw in ["閒置", "重新登入", "登出"]):
                    return "RELOGIN"
            except Exception:
                pass  # 無 alert，正常繼續

            # ⭐ 檢查點 2
            if not self.running:
                logger.info("🛑 使用者手動停止（進入課程）")
                return "STOP"

            # 若 gotoCourse 開啟了新分頁，切換過去
            new_handles = list(self.driver.window_handles)
            if len(new_handles) > len(orig_handles):
                self.driver.switch_to.window(new_handles[-1])
                self._auto_hide_popups_if_needed(settle=True)

            cur_u = self.driver.current_url or ""
            # 💡 若未直接進入教室且非介紹頁（例如停留在首頁 mooc/index.php 或統計頁），強制導航至 /info/{course_id}
            is_classroom_url = any(
                k in cur_u for k in ["/learn/", "/course/", "/controllers/", "hahow.in"]
            )
            if not is_classroom_url and "/info/" not in cur_u:
                logger.info(
                    f"   🧭 導航至課程資訊頁：https://elearn.hrd.gov.tw/info/{course['course_id']}"
                )
                self.driver.get(f"https://elearn.hrd.gov.tw/info/{course['course_id']}")
                self._auto_hide_popups_if_needed(settle=True)
                self.safe_sleep(3)
                info_alert = self._accept_alert_if_present()
                if info_alert:
                    logger.warning(f"   ⚠️ 課程頁面提示：{info_alert}")
                    if any(
                        kw in info_alert
                        for kw in [
                            "尚未上架",
                            "已下架",
                            "非上課期間",
                            "非開放期間",
                            "無法進入",
                            "不開放",
                            "無法上課",
                        ]
                    ):
                        logger.warning(
                            f"   ⏩ 「{course.get('caption', '')}」尚未上架或非上課期間，自動永久略過。"
                        )
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        return "SKIP"
                cur_u = self.driver.current_url or ""

            # 若停留在 /info/ 介紹頁，先檢查是否平臺已標註修畢/通過
            if "/info/" in cur_u:
                info_text = ""
                try:
                    info_text = (
                        self.driver.execute_script(
                            "return document.body ? document.body.innerText : '';"
                        )
                        or ""
                    )
                except Exception:
                    pass
                if any(
                    kw in info_text
                    for kw in ["您已完成此課程", "無法重複取得時數", "已完成此課程"]
                ) or ("通過狀態" in info_text and "已通過" in info_text):
                    logger.info(
                        f"   🎉 課程「{course.get('caption', '')}」平臺已記錄為已修畢（無法重複取得時數），自動標記完成並略過。"
                    )
                    self._completed_in_session.add(str(course.get("course_id", "")))
                    return "SKIP"

                before_handles = list(self.driver.window_handles)
                clicked = self.driver.execute_script("""
                    var modalBtns = document.querySelectorAll('.modal button, .dialog button, div[role="dialog"] button, button.btn-primary, button.btn-confirm');
                    for (var m = 0; m < modalBtns.length; m++) {
                        var mt = (modalBtns[m].innerText || modalBtns[m].textContent || '').trim();
                        if (mt === '確定' || mt === '確認') {
                            modalBtns[m].click();
                            return '確定（彈窗）';
                        }
                    }
                    var btns = document.querySelectorAll('button, a.btn, a, input[type="button"], input[type="submit"]');
                    for (var i = 0; i < btns.length; i++) {
                        var t = (btns[i].innerText || btns[i].value || btns[i].textContent || '').trim();
                        if (['上課去', '進入課程', '開始上課', '前往教室', '繼續學習', '觀看影片', '前往研習', '報名課程', '我要報名', '加入課程', '確認報名'].some(k => t.indexOf(k) !== -1)) {
                            btns[i].click();
                            return t;
                        }
                    }
                    return null;
                """)
                if clicked:
                    logger.info(f"   📝 已點擊「{clicked}」進入課程教室")

                # 💡 攔截點擊後彈出的外購平臺提示 Alert（如「本課程為外購Hahow平臺課程...」）
                time.sleep(1)
                info_alert = self._accept_alert_if_present()
                if info_alert:
                    logger.info(f"   ℹ️ 課程平台轉址提示：{info_alert}")
                    if any(k in info_alert for k in ["外購", "Hahow", "外部平臺"]):
                        logger.warning(f"   ⏩ 「{course.get('caption', '')}」為外購平臺課程，自動略過並優先研習本平臺課程。")
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        try:
                            for h in list(self.driver.window_handles):
                                if orig_handles and h != orig_handles[0]:
                                    self.driver.switch_to.window(h)
                                    self.driver.close()
                            if orig_handles:
                                self.driver.switch_to.window(orig_handles[0])
                        except Exception:
                            pass
                        return "SKIP"

                self.safe_sleep(4)
                try:
                    after_handles = list(self.driver.window_handles)
                    if len(after_handles) > len(before_handles):
                        self.driver.switch_to.window(after_handles[-1])
                        self._auto_hide_popups_if_needed(settle=True)
                except Exception:
                    pass

            for _ in range(10):
                if not self.running:  # ⭐ 檢查點 4
                    logger.info("🛑 使用者手動停止（等待教室載入）")
                    return "STOP"
                time.sleep(1)

            classroom_h = self.find_classroom_window()
            if not classroom_h:
                logger.warning(
                    f"   ⚠️ 課程「{course.get('caption', '')}」無法載入有效教室介面（停留在介紹頁或首頁），自動略過並標記為待查核。"
                )
                self._mark_exam_manual_review(course, "未能成功載入教室或播放器（停留在介紹/首頁）")
                self._completed_in_session.add(str(course.get("course_id", "")))
                return "SKIP"
            self.driver.switch_to.window(classroom_h)
            self._auto_hide_popups_if_needed(settle=True)

            attempted = set()
            frame_fail_count = 0

            while self.running:
                self._auto_hide_popups_if_needed()
                # 1. 檢查單次累計時數是否超過 2 小時 (7200秒)
                if time.time() - session_start > 7200:
                    logger.warning(
                        "   ⚠️ 單一課程研習已達 2 小時，為避免異常，將切換課程。"
                    )
                    break

                prog = self.get_progress_api(course["course_id"])
                if prog:
                    logger.info(
                        f"   📊 研習進度：{prog['cur_str']} / {prog['target_str']} {draw_bar(prog['cur_sec'], prog['target_sec'])}"
                    )

                    if prog["cur_sec"] > last_prog_sec:
                        last_prog_sec = prog["cur_sec"]
                        last_prog_time = time.time()
                    elif time.time() - last_prog_time > 600:
                        logger.error(
                            "   🛑 進度停滯超過 10 分鐘，正在強制執行重啟救回機制。"
                        )
                        return "STALLED"
                    elif time.time() - last_prog_time > 300:
                        logger.warning("   ⚠️ 進度已停滯 5 分鐘，請注意連線狀態。")

                    if prog["cur_sec"] >= prog["target_sec"]:
                        logger.info(f"   ✨ {Fore.GREEN}時數已達標！{Style.RESET_ALL}")
                        break

                # ⭐ 檢查點 6（frame 操作前）
                if not self.running:
                    logger.info("🛑 使用者手動停止（frame 操作前）")
                    return "STOP"

                try:
                    self.driver.switch_to.window(classroom_h)
                    self.driver.switch_to.default_content()
                except Exception:
                    new_classroom_h = self.find_classroom_window()
                    if new_classroom_h:
                        classroom_h = new_classroom_h
                        self.driver.switch_to.window(classroom_h)
                        self.driver.switch_to.default_content()

                is_traditional_frame = False
                try:
                    self.driver.switch_to.frame("s_catalog")
                    self.driver.switch_to.frame("pathtree")
                    is_traditional_frame = True
                    frame_fail_count = 0
                except Exception:
                    try:
                        self.driver.switch_to.default_content()
                    except Exception:
                        pass

                if is_traditional_frame:
                    all_links = [
                        link
                        for link in self.driver.find_elements(By.TAG_NAME, "a")
                        if link.text.strip()
                    ]
                    links = [
                        link for link in all_links
                        if link.text.strip() not in self.config["blacklist"]
                    ]
                    if not links:
                        all_texts = [link.text.strip() for link in all_links]
                        logger.warning(f"   ⚠️ pathtree 無可選單元，原始清單({len(all_texts)}筆): {all_texts[:20]}")
                    target = next(
                        (link for link in links if link.text not in attempted),
                        random.choice(links) if links else None,
                    )
                    if target is None and links:
                        logger.info("   🔄 所有單元已輪完，重置重新輪...")
                        attempted.clear()
                        target = random.choice(links)

                    if target:
                        if not self.running:
                            logger.info("🛑 使用者手動停止（進入單元前）")
                            return "STOP"

                        u_name = target.text.strip()
                        attempted.add(u_name)
                        logger.info(f"   📍 進入單元：{u_name[:20]}...")
                        self.driver.execute_script("arguments[0].click();", target)

                        w_time = self.config.get("residence_time", 75)
                        st = time.time()
                        while time.time() - st < w_time:
                            if not self.running:
                                logger.info("🛑 使用者手動停止（停留中）")
                                return "STOP"

                            time.sleep(1)
                            self.driver.switch_to.window(classroom_h)
                            self.driver.execute_script(
                                "function deepCommit(win){ try{if(win.API)win.API.LMSCommit('');}catch(e){} if(win.frames){for(let i=0;i<win.frames.length;i++)deepCommit(win.frames[i]);}} deepCommit(window);"
                            )
                    else:
                        for _ in range(30):
                            if not self.running:
                                return "STOP"
                            time.sleep(1)
                else:
                    # ── MOOCs / HTML5 / 微學習單頁教室處理 ──
                    alert_text = self._accept_alert_if_present()
                    err_text = f"{alert_text}"
                    current_url = ""
                    page_src = ""
                    try:
                        current_url = self.driver.current_url or ""
                        page_src = self.driver.page_source or ""
                    except Exception:
                        pass

                    # 💡 檢查是否有瀏覽器重新導向過多 (ERR_TOO_MANY_REDIRECTS) 或網路/伺服器錯誤
                    if (
                        "ERR_TOO_MANY_REDIRECTS" in page_src
                        or "重新導向的次數過多" in page_src
                        or "ERR_TOO_MANY_REDIRECTS" in current_url
                        or "ERR_NAME_NOT_RESOLVED" in page_src
                    ):
                        logger.warning(
                            f"   ⚠️ 「{course.get('caption', '')}」平臺網頁異常（重新導向次數過多 ERR_TOO_MANY_REDIRECTS），自動跳過並優先研習其他課程。"
                        )
                        self._mark_exam_manual_review(course, "平臺網頁異常（ERR_TOO_MANY_REDIRECTS 重新導向過多）")
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        return "SKIP"

                    # 💡 檢查是否為已完成/無法重複取得時數之課程
                    if any(
                        kw in page_src
                        for kw in ["您已完成此課程", "無法重複取得時數", "已完成此課程"]
                    ) or ("通過狀態" in page_src and "已通過" in page_src):
                        logger.info(
                            f"   🎉 課程「{course.get('caption', '')}」平臺已記錄為已修畢（無法重複取得時數），自動標記完成並略過。"
                        )
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        return "SKIP"

                    if self._is_logout_text(err_text) or self._is_logout_text(current_url):
                        logger.warning("🔄 帳號閒置或被重導至首頁/登入頁，停止當前教室並立即觸發重新登入。")
                        return "RELOGIN"

                    # 💡 若跳轉回平臺首頁或統計頁（非教室），停止本課程並略過
                    if any(
                        k in current_url
                        for k in ["mooc/index.php", "learn_stat.php", "learn_dashboard.php"]
                    ):
                        logger.warning(
                            f"   ⚠️ 「{course.get('caption', '')}」教室已關閉或跳轉回平臺首頁，停止本課程並優先研習其他課程。"
                        )
                        self._mark_exam_manual_review(course, "教室未開啟或跳轉回平臺首頁")
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        return "SKIP"

                    frame_fail_count = 0

                    # 💡 若當前停留在 /info/ 介紹頁，嘗試點擊「上課去」進入真實教室
                    if "/info/" in current_url:
                        self.driver.execute_script("""
                            var btns = document.querySelectorAll('button, a.btn, a, input[type="button"], input[type="submit"]');
                            for (var i = 0; i < btns.length; i++) {
                                var t = (btns[i].innerText || btns[i].value || btns[i].textContent || '').trim();
                                if (['上課去', '進入課程', '開始上課', '前往教室', '繼續學習', '觀看影片', '前往研習'].some(k => t.indexOf(k) !== -1)) {
                                    btns[i].click();
                                    break;
                                }
                            }
                        """)

                    # 💡 若當前停留在 Hahow /home 首頁，自動點擊當前課程或進入「我的學習」
                    if "hahow.in" in current_url and "/home" in current_url:
                        c_caption = str(course.get("caption", ""))[:8]
                        self.driver.execute_script(f"""
                            var links = document.querySelectorAll('a, button, [role="button"], .card, [class*="item"]');
                            var found = false;
                            for (var i = 0; i < links.length; i++) {{
                                var t = (links[i].innerText || links[i].textContent || '').trim();
                                if ('{c_caption}' && t.indexOf('{c_caption}') !== -1) {{
                                    links[i].click();
                                    found = true;
                                    break;
                                }}
                            }}
                            if (!found) {{
                                for (var j = 0; j < links.length; j++) {{
                                    var txt = (links[j].innerText || links[j].textContent || '').trim();
                                    if (txt.indexOf('我的學習') !== -1) {{
                                        links[j].click();
                                        break;
                                    }}
                                }}
                            }}
                        """)

                    # 尋找真實課程章節單元連結（含 Hahow / MOOCs 現代播放器）
                    moocs_links = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "a.unit-item, .chapter-list a, .tree-node a, a[href*='node'], a[onclick*='play'], a[onclick*='read'], li.leaf a, .course-outline a, .outline a, a.list-group-item, .unit-title, a[href*='catalog'], [class*='unit'] a, [class*='chapter'] a, a[href*='lecture'], [class*='LectureItem'], [class*='lecture-item'], button[class*='lecture'], div[role='button'][class*='item']"
                    )
                    if not moocs_links:
                        moocs_links = self.driver.find_elements(
                            By.XPATH,
                            "//a[contains(@href, 'node') or contains(@href, 'play') or contains(@href, 'unit') or contains(@href, 'catalog') or contains(@href, 'lecture') or contains(@class, 'unit') or contains(@class, 'chapter') or contains(@class, 'lecture')]"
                        )

                    # 排除非課程內容的通用導覽標籤（無效導航）
                    ignored_keywords = [
                        "跳到主要內容", ":::", "網站導覽", "常見問題", "下載專區", "加盟機關",
                        "簡易操作", "隱私權", "安全政策", "版權聲明", "回首頁", "選課中心",
                        "個人資料", "學習概況", "帳號管理", "登出", "登入", "我的課程", "問卷", "測驗"
                    ]
                    filtered_links = []
                    for a in moocs_links:
                        try:
                            t = a.text.strip()
                            if not t or len(t) < 2:
                                continue
                            if any(k in t for k in ignored_keywords):
                                continue
                            if t in self.config.get("blacklist", []):
                                continue
                            filtered_links.append(a)
                        except Exception:
                            continue

                    target = next(
                        (l for l in filtered_links if l.text.strip() not in attempted),
                        random.choice(filtered_links) if filtered_links else None
                    )
                    if target is None and filtered_links:
                        attempted.clear()
                        target = random.choice(filtered_links)

                    if target:
                        u_name = target.text.strip()
                        attempted.add(u_name)
                        logger.info(f"   📍 進入單元（MOOCs/Hahow）：{u_name[:25]}...")
                        try:
                            self.driver.execute_script("arguments[0].click();", target)
                        except Exception:
                            pass
                    else:
                        logger.info("   📍 正在播放課程影音內容（MOOCs/Hahow）...")

                    # 嘗試播放影片與觸發播放器
                    try:
                        self.driver.execute_script("""
                            function playAllVideos(doc) {
                                try {
                                    var vs = doc.querySelectorAll('video');
                                    for (var i = 0; i < vs.length; i++) {
                                        vs[i].muted = true;
                                        if (vs[i].paused) vs[i].play().catch(function(){});
                                    }
                                    var pbtn = doc.querySelector('[aria-label*="Play"], [aria-label*="播放"], button.vjs-big-play-button, .vjs-play-control, [class*="PlayButton"]');
                                    if (pbtn) { pbtn.click(); }
                                } catch(e){}
                                try {
                                    var iframes = doc.querySelectorAll('iframe');
                                    for (var j = 0; j < iframes.length; j++) {
                                        playAllVideos(iframes[j].contentDocument);
                                    }
                                } catch(e){}
                            }
                            playAllVideos(document);
                        """)
                    except Exception:
                        pass

                    w_time = self.config.get("residence_time", 75)
                    st = time.time()
                    while time.time() - st < w_time:
                        if not self.running:
                            logger.info("🛑 使用者手動停止（停留中）")
                            return "STOP"

                        time.sleep(1)
                        self.driver.switch_to.window(classroom_h)
                        self.driver.execute_script("""
                            function deepCommit(win){
                                try{if(win.API)win.API.LMSCommit('');}catch(e){}
                                try{
                                    var v = win.document.querySelector('video');
                                    if (v && v.paused) { v.muted = true; v.play().catch(function(){}); }
                                }catch(e){}
                                if(win.frames){for(let i=0;i<win.frames.length;i++)deepCommit(win.frames[i]);}
                            }
                            deepCommit(window);
                        """)

            # ⭐ 檢查點 11（結束前）
            if not self.running:
                logger.info("🛑 使用者手動停止（課程結束前）")
                return "STOP"

            # 時數達標，嘗試自動作答測驗，通過後填寫問卷（若問卷未完成）
            if self.running:
                if self.config.get("skip_exam_for_session", False):
                    logger.warning("本次已選擇跳過測驗；時數已達標，改為嘗試填寫問卷。")
                    if str(course.get("fill", "0")) != "1":
                        q_ok = self.auto_questionnaire(course)
                        if not q_ok:
                            self._mark_exam_manual_review(course, "問卷填寫失敗，尚未確認完成")
                    else:
                        logger.info(f"   ✅ 「{course.get('caption', '')}」問卷先前已完成，跳過填寫。")
                else:
                    exam_passed = self.auto_exam(course)
                    if self.running and exam_passed:
                        if str(course.get("fill", "0")) != "1":
                            q_ok = self.auto_questionnaire(course)
                            if not q_ok:
                                self._mark_exam_manual_review(course, "問卷填寫失敗，尚未確認完成")
                        else:
                            logger.info(f"   ✅ 「{course.get('caption', '')}」問卷先前已完成，跳過填寫。")

            logger.info("   🔄 返回學習概況清單...")
            self.driver.get(self.stat_url)
            if not self.safe_sleep(5):
                return "STOP"
            self.sync_session()
            return "SUCCESS"

        except UnexpectedAlertPresentException as e:
            alert_text = ""
            try:
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                alert.accept()
                logger.info(f"ℹ️ 偵測並接受 Alert：{alert_text}")
            except Exception:
                alert_text = str(e)
            if "閒置" in alert_text or "重新登入" in alert_text or "登出" in alert_text:
                logger.warning("🔄 帳號閒置被登出，嘗試重新登入後繼續當前課程...")
                try:
                    self.driver.get(self.stat_url)
                except Exception:
                    pass
                time.sleep(3)
                if self.login():
                    logger.info("✅ 重新登入成功，將重試當前課程。")
                    return "RELOGIN"
                else:
                    logger.error("❌ 重新登入失敗，跳過當前課程。")
                    return "ERROR"
            elif any(kw in alert_text for kw in ["非本門課", "無法上課", "無權限", "不開放", "未選課", "尚未上架", "已下架", "直播已結束"]):
                logger.warning(f"⚠️ 此課程無法上課（{alert_text}），永久跳過。")
                self._completed_in_session.add(str(course.get("course_id", "")))
                try:
                    self.driver.get(self.stat_url)
                except Exception:
                    pass
                time.sleep(3)
                return "SKIP"
            elif any(kw in alert_text for kw in ["外購", "Hahow"]):
                logger.warning(f"   ⏩ 「{course.get('caption', '')}」為外購平臺課程（{alert_text}），自動略過並切換下一門課程。")
                self._completed_in_session.add(str(course.get("course_id", "")))
                try:
                    self.driver.get(self.stat_url)
                except Exception:
                    pass
                time.sleep(2)
                return "SKIP"
            elif any(kw in alert_text for kw in ["平臺", "平台", "閱讀", "磨課師", "提醒", "另開", "視窗", "即將進入"]):
                logger.info(f"   ℹ️ 外部平臺通知已自動確認（{alert_text}），重新進入教室...")
                return "RELOGIN"
            else:
                logger.warning(f"   ⚠️ 研習期間 Alert（{alert_text}），自動確認並重試...")
                return "RELOGIN"

        except Exception as e:
            logger.error(f"   ❌ 研習異常: {e}", exc_info=True)
            try:
                self.driver.get(self.stat_url)
            except Exception:
                pass
            time.sleep(5)
            return "ERROR"

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
            logger.info(f"🤖 AI 補答已啟用（model: {model}，endpoint: {base_url}）")
        else:
            logger.info("📖 AI 補答未啟用，僅使用本地題庫作答")
        try:
            if not self.init_engine():
                if sys.stdin:
                    input(
                        f"\n{Fore.RED}❌ 引擎啟動失敗，請檢查驅動程式後按 Enter 退出...{Style.RESET_ALL}"
                    )
                return

            if not self.login():
                login_type = self.config.get("login_type", "ecpa")
                if login_type == "egov":
                    msg = "❌ 登入失敗！請確認『我的E政府』帳密正確，或是否出現驗證碼。"
                else:
                    msg = "❌ 登入失敗！請確認 eCPA 帳密正確且無驗證碼要求。"
                if sys.stdin:
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
                                self._cleanup()
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
                        hours_done = to_sec(c.get("rss", "00:00:00")) >= to_sec(
                            c.get("criteria_content_hour", "00:00:00")
                        )
                        if not hours_done:
                            return False
                        # 考試未通過（且未達 3 次不及格上限）
                        exam_passed = self._is_exam_passed(c)
                        needs_exam = (not exam_passed) and (self._exam_fail_counts.get(c_id, 0) < 3)
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

                    # ── 第一步：先對時數已達標但考試/問卷未完成的課程執行 ──
                    # （初始使用者全部 pending 時，completed_hours 為空，此段直接跳過）
                    all_exam_done = True
                    if completed_hours:
                        all_exam_done = True
                        for c in completed_hours:
                            if not self.running:
                                break
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

                                # 若停留在 /info/ 介紹頁，先檢查是否平臺已標註修畢/通過
                                if "/info/" in self.driver.current_url:
                                    info_text = ""
                                    try:
                                        info_text = (
                                            self.driver.execute_script(
                                                "return document.body ? document.body.innerText : '';"
                                            )
                                            or ""
                                        )
                                    except Exception:
                                        pass
                                    if any(
                                        kw in info_text
                                        for kw in [
                                            "您已完成此課程",
                                            "無法重複取得時數",
                                            "已完成此課程",
                                        ]
                                    ) or ("通過狀態" in info_text and "已通過" in info_text):
                                        logger.info(
                                            f"   🎉 課程「{c.get('caption', '')}」平臺顯示已全數修畢（已通過），免重複執行。"
                                        )
                                        self._completed_in_session.add(c_id)
                                        continue

                                # 點「開始上課」/「進入課程」/「上課去」按鈕（如有）
                                try:
                                    clicked_entry = self.driver.execute_script("""
                                        var modalBtns = document.querySelectorAll('.modal button, .dialog button, div[role="dialog"] button, button.btn-primary, button.btn-confirm');
                                        for (var m = 0; m < modalBtns.length; m++) {
                                            var mt = (modalBtns[m].innerText || modalBtns[m].textContent || '').trim();
                                            if (mt === '確定' || mt === '確認') {
                                                modalBtns[m].click();
                                                return '確定（彈窗）';
                                            }
                                        }
                                        var btns = document.querySelectorAll('button, a.btn, a, input[type="button"], input[type="submit"]');
                                        for (var i = 0; i < btns.length; i++) {
                                            var t = (btns[i].innerText || btns[i].value || btns[i].textContent || '').trim();
                                            if (['認證', '進行測驗', '開始測驗', '參加測驗', '前往測驗', '測驗', '上課去', '進入課程', '開始上課', '前往教室', '繼續學習', '觀看影片', '前往研習'].some(k => t.indexOf(k) !== -1)) {
                                                btns[i].click();
                                                return t;
                                            }
                                        }
                                        return null;
                                    """)
                                    if clicked_entry:
                                        logger.info(f"   📝 已點擊「{clicked_entry}」進入教室/測驗介面")
                                    if not self.safe_sleep(5):
                                        break
                                    if len(self.driver.window_handles) > 1:
                                        self.driver.switch_to.window(self.driver.window_handles[-1])
                                        self._auto_hide_popups_if_needed(settle=True)
                                except Exception:
                                    pass
                                logger.info(
                                    f"   📝 目前頁面 URL: {self.driver.current_url}"
                                )
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
                                else:
                                    self._mark_exam_manual_review(c, "問卷填寫失敗，尚未確認完成")
                                continue

                            passed = self.auto_exam(c)
                            if passed and self.running:
                                q_ok = True
                                if str(c.get("fill", "0")) != "1":
                                    q_ok = self.auto_questionnaire(c)
                                else:
                                    logger.info(f"   ✅ 「{c.get('caption', '')}」問卷先前已完成，跳過填寫。")
                                if q_ok:
                                    self._completed_in_session.add(c_id)
                                else:
                                    self._mark_exam_manual_review(c, "問卷填寫失敗，尚未確認完成")
                            elif not passed:
                                # 若不及格次數未達上限，跳回迴圈頂部繼續重考
                                if self._exam_fail_counts.get(c_id, 0) < 3:
                                    all_exam_done = False
                                    break
                                else:
                                    # 已達 3 次不及格上限，列為待人工處理清單，本次不再重試
                                    self._mark_exam_manual_review(c, "測驗連續不及格已達 3 次上限")
                                    self._completed_in_session.add(c_id)

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
                        res = self.study_process(pending[0])

                        if res == "STOP":
                            logger.info("🛑 使用者已停止程式")
                            break

                        if res == "RELOGIN":
                            c_id = str(pending[0].get("course_id", ""))
                            self._course_relogin_counts[c_id] = self._course_relogin_counts.get(c_id, 0) + 1
                            if self._course_relogin_counts[c_id] >= 2:
                                logger.warning(
                                    f"⚠️ 課程「{pending[0].get('caption', c_id)}」連續觸發重新登入異常（平臺跳轉或頁面失效），自動略過以避免無限循環。"
                                )
                                self._mark_exam_manual_review(pending[0], "連續觸發重登異常（平臺頁面跳轉失敗）")
                                self._completed_in_session.add(c_id)
                                continue
                            # 閒置登出後已重新登入，重試當前課程（退回 index）
                            logger.info("🔄 閒置登出重新登入成功，重試當前課程...")
                            self.sync_session()  # 確保 http_session 用最新 cookie
                            self.current_idx -= 1
                            continue

                        if res == "STALLED":
                            logger.warning("🚀 偵測到停滯，正在重新啟動輔助引擎...")
                            self._cleanup()
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
                            logger.info("⏭️ 已永久跳過課程，繼續下一門...")
                        elif res == "ERROR":
                            logger.info("⏳ 發生研習異常，稍後嘗試下一門課程...")
                            time.sleep(5)

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
                    # 偵測 WebDriver session 失效（Chrome crash / HTTPConnectionPool）
                    err_str = str(e)
                    if (
                        "HTTPConnectionPool" in err_str
                        or "Failed to establish a new connection" in err_str
                        or "session" in err_str.lower()
                        or "WebDriver" in err_str
                        or "chrome not reachable" in err_str.lower()
                    ):
                        if not self._try_auto_healing(err_str):
                            break
                        continue
                    else:
                        self.safe_sleep(10)

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
