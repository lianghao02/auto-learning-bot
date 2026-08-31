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

