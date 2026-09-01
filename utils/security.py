import collections
import hashlib
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


AI_PROVIDER_HOSTS = {
    "OpenAI": frozenset({"api.openai.com"}),
    "Gemini": frozenset({"generativelanguage.googleapis.com"}),
    "Claude": frozenset({"api.anthropic.com"}),
    "Groq": frozenset({"api.groq.com"}),
}


def validate_ai_base_url(provider: str, base_url: str) -> str:
    """驗證 AI API 網址，避免將金鑰送往非預期主機。"""
    value = str(base_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("API Base URL 不可為空白")

    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https":
        raise ValueError("API Base URL 必須使用 HTTPS")
    if not parsed.hostname:
        raise ValueError("API Base URL 缺少有效主機名稱")
    if parsed.username or parsed.password:
        raise ValueError("API Base URL 不可包含帳號或密碼")
    if parsed.query or parsed.fragment:
        raise ValueError("API Base URL 不可包含查詢參數或片段")

    hostname = parsed.hostname.lower().rstrip(".")
    allowed_hosts = AI_PROVIDER_HOSTS.get(provider)
    if allowed_hosts and hostname not in allowed_hosts:
        expected = "、".join(sorted(allowed_hosts))
        raise ValueError(f"{provider} 僅允許連線至官方網域：{expected}")
    if provider not in AI_PROVIDER_HOSTS and provider != "自訂":
        raise ValueError(f"不支援的 AI 服務：{provider}")

    netloc = hostname if not parsed.port else f"{hostname}:{parsed.port}"
    return urlunsplit(("https", netloc, parsed.path.rstrip("/"), "", ""))


def verify_file_sha256(path: str | Path, expected_digest: str) -> bool:
    """以 SHA-256 驗證已下載檔案，僅接受完整的 64 碼雜湊。"""
    expected = str(expected_digest or "").lower().removeprefix("sha256:").strip()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        return False

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


class RateLimiter:
    """線程安全的滑動窗口速率限制器（防止超出 API 免費額度）。"""

    def __init__(self, max_requests: int = 5, window_seconds: float = 60.0):
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1.0, float(window_seconds))
        self.timestamps: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 60.0) -> bool:
        """等待直到取得請求配額，若超時則回傳 False。"""
        deadline = time.time() + timeout
        while time.time() <= deadline:
            with self._lock:
                now = time.time()
                while self.timestamps and (now - self.timestamps[0]) >= self.window_seconds:
                    self.timestamps.popleft()
                if len(self.timestamps) < self.max_requests:
                    self.timestamps.append(now)
                    return True
                wait_time = self.window_seconds - (now - self.timestamps[0]) + 0.05
            time.sleep(min(wait_time, 0.5))
        return False



# 全域 AI API 速率限制器（預設每分鐘最多 5 次請求）
global_ai_rate_limiter = RateLimiter(max_requests=5, window_seconds=60.0)



def mask_api_key(key: str | None) -> str:
    """將 API Key 進行安全遮罩，例如 'AIzaSy...1234' 轉為 'AIzaSy***1234'。"""
    raw = str(key or "").strip()
    if not raw:
        return ""
    if len(raw) <= 8:
        return "***"
    return f"{raw[:6]}***{raw[-4:]}"


class DailyQuotaTracker:
    """本機每日 AI API 配額追蹤器（跨重啟持久化保存）。"""

    def __init__(self, daily_limit: int = 1500, storage_path: Path | str | None = None):
        self.daily_limit = daily_limit
        self._storage_path = Path(storage_path) if storage_path else None
        self._lock = threading.Lock()

    def _get_file_path(self) -> Path:
        if self._storage_path:
            return self._storage_path
        from utils.app_paths import user_data_path
        return user_data_path("data/daily_quota.json")

    def record_usage(self, count: int = 1) -> dict:
        """記錄 API 消耗並回傳今日統計。"""
        with self._lock:
            path = self._get_file_path()
            today_str = time.strftime("%Y-%m-%d")
            data = {"date": today_str, "used": 0}
            if path.exists():
                try:
                    import json
                    with path.open("r", encoding="utf-8") as f:
                        saved = json.load(f)
                    if saved.get("date") == today_str:
                        data["used"] = int(saved.get("used", 0))
                except Exception:
                    pass
            data["used"] += count
            try:
                from utils.config_io import write_json_atomically
                write_json_atomically(path, data)
            except Exception:
                pass

            used = data["used"]
            remaining = max(0, self.daily_limit - used)
            pct = round((remaining / self.daily_limit) * 100, 1)
            return {
                "date": today_str,
                "used": used,
                "daily_limit": self.daily_limit,
                "remaining": remaining,
                "percentage": pct,
            }

    def get_stats(self) -> dict:
        """取得今日配額統計。"""
        with self._lock:
            path = self._get_file_path()
            today_str = time.strftime("%Y-%m-%d")
            used = 0
            if path.exists():
                try:
                    import json
                    with path.open("r", encoding="utf-8") as f:
                        saved = json.load(f)
                    if saved.get("date") == today_str:
                        used = int(saved.get("used", 0))
                except Exception:
                    pass
            remaining = max(0, self.daily_limit - used)
            pct = round((remaining / self.daily_limit) * 100, 1)
            return {
                "date": today_str,
                "used": used,
                "daily_limit": self.daily_limit,
                "remaining": remaining,
                "percentage": pct,
            }


# 全域每日配額追蹤實例
global_quota_tracker = DailyQuotaTracker(daily_limit=1500)


def format_batch_summary_card(
    session_courses: int,
    pass_count: int,
    bank_solved: int,
    ai_solved: int,
    ai_requests: int,
) -> str:
    """格式化階段性成果與每日額度摘要卡片。"""
    stats = global_quota_tracker.get_stats()
    pass_rate = round((pass_count / max(1, session_courses)) * 100, 1)
    status_icon = "🟢" if stats["remaining"] > 300 else ("🟡" if stats["remaining"] > 50 else "🔴")
    card = f"""
┌────────────────────────────────────────────────────────────┐
│ 📊 階段成效彙整（已累積完成 {session_courses} 門課程測驗）                   │
│                                                            │
│ • 測驗通過率：{pass_count} / {session_courses} 門（及格率 {pass_rate}%）                      │
│ • 本機題庫秒殺：{bank_solved} 題（0 耗額）                            │
│ • AI 批次解答：{ai_solved} 題（共發送 {ai_requests} 次請求）                │
│ ────────────────────────────────────────────────────────── │
│ 💳 Google Gemini API 呼叫統計（今日）：                     │
│ • 本日累計呼叫：{stats['used']} 次 ｜ 預估剩餘配額：{stats['remaining']} 次 / {stats['daily_limit']} 次    │
│ • 配額健康度：{status_icon} 充足（剩餘 {stats['percentage']}%，實際以官方為準）     │
└────────────────────────────────────────────────────────────┘"""
    return card.strip()


def format_course_dashboard_card(
    course_name: str,
    score_text: str,
    is_passed: bool,
    solve_mode_desc: str,
    feedback_status: str,
    session_completed: int,
    session_passed: int,
) -> str:
    """格式化每門課即時動態成果卡片。"""
    stats = global_quota_tracker.get_stats()
    pass_icon = "🎉" if is_passed else "⚠️"
    status_icon = "🟢" if stats["remaining"] > 300 else ("🟡" if stats["remaining"] > 50 else "🔴")
    pass_rate = round((session_passed / max(1, session_completed)) * 100, 1)

    card = f"""
┌────────────────────────────────────────────────────────────┐
│ 🎯 行政效能領航員 - 即時研習成效儀表板                        │
│ ────────────────────────────────────────────────────────── │
│ 📚 最新完成課程：【{course_name}】
│ 🏆 測驗通過成果：{pass_icon} {score_text} ｜ 問卷：{feedback_status}
│ ⚡ 本門作答方式：{solve_mode_desc}
│                                                            │
│ 📊 本次執行累計：已連續通過 {session_passed}/{session_completed} 門課程（及格率 {pass_rate}%）
│ 💳 今日 API 呼叫：已用 {stats['used']} 次 ｜ 預估剩餘 {stats['remaining']} 次 / {stats['daily_limit']} 次
│ {status_icon} 配額健康狀態：充足（剩餘 {stats['percentage']}%，實際以官方為準）
└────────────────────────────────────────────────────────────┘"""
    return card.strip()
