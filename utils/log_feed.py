"""執行日誌整理器：把臺北E大（print 輸出）與 e等公務園（logging 輸出）兩種格式統一成同一種事件。

- 研習進度／進入單元這類每 77 秒一次的心跳訊息不再逐行堆疊，改為更新「目前研習」即時卡片，
  只在跨過 25% 里程碑時留下一筆紀錄。
- 逐題作答、DOM 診斷等細節標為 detail，只在「全部」與「測驗問卷」篩選中淡色顯示。
- 純 Python、不依賴 Qt，方便單元測試。
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime
import re

# key: (中文標籤, 圖示)
CATEGORIES = {
    "login": ("登入", "🔑"),
    "course": ("課程", "📖"),
    "study": ("研習", "⏱"),
    "quiz": ("測驗", "📝"),
    "survey": ("問卷", "📋"),
    "bank": ("題庫", "📚"),
    "system": ("系統", "⚙"),
}

# key: (按鈕文字, 說明)
FILTERS = {
    "all": ("全部", "所有紀錄（含逐題作答細節）"),
    "key": ("⭐ 重點", "課程切換、完成、警告與錯誤"),
    "study": ("⏱ 研習", "研習里程碑與課程切換"),
    "quiz": ("📝 測驗問卷", "測驗、問卷與題庫"),
    "system": ("⚙ 登入系統", "登入、Session 與系統訊息"),
}

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_STAMPED = re.compile(r"^(\d{2}:\d{2}:\d{2}) \[(\w+)\] ?(.*)$", re.S)
_SEPARATOR = re.compile(r"^[-=─━┌┐└┘├┤│\s]{6,}$")
_HEADER = re.compile(r"^={2,}\s*(.+?)\s*={2,}$")
_TAG = re.compile(r"^\[(題庫|測驗|成績\d*|模組|掃描|config|Alert|驗證碼|AI批次|AI|登入失敗|錯誤|警告|DOM)\]\s*")
_PROGRESS = re.compile(r"研習進度\s*[:：]\s*(\d{1,2}:\d{2}:\d{2})\s*/\s*(\d{1,2}:\d{2}:\d{2}).*?([\d.]+)\s*%")
_UNIT = re.compile(r"進入單元\s*[:：]\s*(.*?)(?:\.\.\.)?$")
_COURSE_START = (
    re.compile(r"^處理\s*[:：]\s*(.+)$"),
    re.compile(r"^📖\s*\[(\d+)/(\d+)\]\s*正在協助研習\s*[:：]\s*(.+)$"),
)
_QUIZ_DETAIL = re.compile(r"^(✓ \[|\? \[猜\]|📝 作答進度|\[DOM\])")
_DETAIL = re.compile(r"^(SCORM URL:|Player URL:|captcha \[|▶️ (進入|點擊|正式提交)|✅ 單元已完成|\(No symbol\)|Stacktrace|GetHandleVerifier|0x[0-9a-f]+|\w+ \[0x)")
_TAG_CATEGORY = {
    "題庫": "bank", "測驗": "quiz", "成績": "quiz", "模組": "course", "掃描": "course",
    "config": "system", "Alert": "system", "驗證碼": "login", "AI批次": "quiz", "AI": "quiz",
    "登入失敗": "login", "DOM": "quiz",
}
_KEYWORDS = (
    ("survey", ("問卷", "滿意度")),
    ("quiz", ("測驗", "作答", "成績", "及格", "考試", "交卷", "繳交", "Gemini", "AI ")),
    ("bank", ("題庫", "GAS")),
    ("login", ("登入", "session", "Session", "SSO", "驗證碼", "Cookie")),
    ("study", ("研習", "單元", "時數", "SCORM", "教材", "上課", "教室", "章節", "點擊失敗")),
    ("course", ("課程", "待上", "API 回傳")),
)
_SUCCESS_MARKS = ("✅", "🎉", "🏆", "成功", "通過", "已完成", "完成！")


@dataclass
class LogEntry:
    time: str
    level: str          # INFO / WARNING / ERROR / DEBUG
    category: str       # CATEGORIES 的 key
    kind: str           # event / detail / header / card / milestone
    text: str
    repeat: int = 1     # 連續相同訊息合併後的次數

    @property
    def is_success(self) -> bool:
        return self.level == "INFO" and any(m in self.text for m in _SUCCESS_MARKS)

    @property
    def plain(self) -> str:
        label = CATEGORIES.get(self.category, ("", ""))[0]
        suffix = f" ×{self.repeat}" if self.repeat > 1 else ""
        return f"{self.time} [{label}] {self.text}{suffix}"


@dataclass
class LiveProgress:
    course: str = ""
    elapsed: str = ""
    target: str = ""
    pct: float = 0.0
    unit: str = ""
    updated: str = ""

    @property
    def active(self) -> bool:
        return bool(self.target)


@dataclass
class FeedUpdate:
    entry: object       # LogEntry 或 None（心跳訊息只更新即時卡片）
    message: str        # 去掉時間與等級後的原始訊息，供狀態列解析
    live_changed: bool
    merged: bool = False  # True 表示與上一筆相同，只更新上一筆的次數


def _category_for(text, default="system"):
    for key, words in _KEYWORDS:
        if any(w in text for w in words):
            return key
    return default


def _guess_level(text):
    if "❌" in text or "錯誤" in text:
        return "ERROR"
    if "⚠️" in text or "警告" in text or "失敗" in text:
        return "WARNING"
    return "INFO"


def matches_filter(entry, key):
    if key == "all":
        return True
    if key == "key":
        return entry.kind in ("header", "card") or entry.level in ("WARNING", "ERROR", "CRITICAL") or (
            entry.kind == "event" and entry.is_success
        )
    if entry.kind == "detail" and key != "quiz":
        return False
    if key == "study":
        return entry.category == "study" or entry.kind == "header"
    if key == "quiz":
        return entry.category in ("quiz", "survey", "bank") or entry.kind == "card"
    if key == "system":
        return entry.category in ("login", "system")
    return True


class LogFeed:
    """保存最近的整理後紀錄與目前研習狀態。"""

    MILESTONE_STEP = 25

    def __init__(self, max_entries=1500):
        self.entries = deque(maxlen=max_entries)
        self.live = LiveProgress()
        self._milestone = -1
        self.issue_count = 0

    def clear(self):
        self.entries.clear()
        self.live = LiveProgress()
        self._milestone = -1
        self.issue_count = 0

    def add(self, raw):
        """解析一行原始日誌；回傳 FeedUpdate，空白或分隔線回傳 None。"""
        text = _ANSI.sub("", str(raw or "")).rstrip()
        m = _STAMPED.match(text)
        if m:
            stamp, level, msg = m.group(1), m.group(2).upper(), m.group(3)
        else:
            stamp, level, msg = datetime.now().strftime("%H:%M:%S"), "", text
        msg = msg.strip()
        if not msg or _SEPARATOR.match(msg):
            return None
        if level == "WARN":
            level = "WARNING"

        entry = self._classify(stamp, level, msg)
        live_changed = False

        progress = _PROGRESS.search(msg)
        unit = _UNIT.search(msg)
        if progress:
            elapsed, target, pct = progress.group(1), progress.group(2), float(progress.group(3))
            self.live.elapsed, self.live.target, self.live.pct, self.live.updated = elapsed, target, pct, stamp
            live_changed = True
            bucket = int(min(pct, 100) // self.MILESTONE_STEP)
            if bucket > self._milestone:
                first = self._milestone < 0
                self._milestone = bucket
                label = f"開始研習：{elapsed} / {target}（{pct:.1f}%）" if first else f"研習里程碑 {bucket * self.MILESTONE_STEP}%：{elapsed} / {target}"
                entry = LogEntry(stamp, "INFO", "study", "milestone", label)
            else:
                entry = None
        elif unit:
            self.live.unit, self.live.updated = unit.group(1).strip(), stamp
            live_changed = True
            entry = None

        if entry is not None and entry.kind == "header" and entry.category == "course":
            course = entry.text.split("：", 1)[-1]
            self.live = LiveProgress(course=course)
            self._milestone = -1
            live_changed = True

        if entry is not None:
            last = self.entries[-1] if self.entries else None
            if last is not None and (last.text, last.kind, last.level) == (entry.text, entry.kind, entry.level):
                last.repeat += 1
                last.time = entry.time
                return FeedUpdate(last, msg, live_changed, merged=True)
            if entry.level in ("WARNING", "ERROR", "CRITICAL"):
                self.issue_count += 1
            self.entries.append(entry)
        return FeedUpdate(entry, msg, live_changed)

    def _classify(self, stamp, level, msg):
        text = msg
        if text.startswith("│"):
            body = text.strip("│| ").strip()
            if not body or _SEPARATOR.match(body):
                return None
            return LogEntry(stamp, level or _guess_level(body), "course", "card", body)

        header = _HEADER.match(text)
        if header:
            title = header.group(1)
            return LogEntry(stamp, level or "INFO", _category_for(title, "system"), "header", title)

        for pattern in _COURSE_START:
            cm = pattern.match(text)
            if cm:
                name = cm.groups()[-1].strip()
                prefix = f"[{cm.group(1)}/{cm.group(2)}] " if len(cm.groups()) == 3 else ""
                return LogEntry(stamp, level or "INFO", "course", "header", f"{prefix}開始處理：{name}")

        category = None
        tag = _TAG.match(text)
        if tag:
            name = re.sub(r"\d+$", "", tag.group(1))
            category = _TAG_CATEGORY.get(name)
            if name not in ("DOM",):
                text = text[tag.end():].strip() or text

        if _QUIZ_DETAIL.match(msg):
            kind, category = "detail", category or "quiz"
        else:
            kind = "detail" if _DETAIL.match(msg) else "event"
        category = category or _category_for(text)
        return LogEntry(stamp, level or _guess_level(text), category, kind, text)
