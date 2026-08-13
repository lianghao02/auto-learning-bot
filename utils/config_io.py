"""設定檔安全讀寫工具。"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomically(path: str | Path, data: Any) -> None:
    """安全寫入 JSON，保留上一版並避免中斷時毀損原檔。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None

    try:
        fd, raw_temp_path = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temp_path = Path(raw_temp_path)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=4)
            handle.flush()
            os.fsync(handle.fileno())

        if target.exists():
            shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def get_db_connection(db_path: str | Path = "questions.db", timeout: float = 30.0) -> sqlite3.Connection:
    """取得設定好的 SQLite 資料庫連線（啟用 WAL 模式與超時保護）。"""
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn
