"""安全相關的共用驗證工具。"""

from __future__ import annotations

import hashlib
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
