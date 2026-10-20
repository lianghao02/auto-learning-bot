"""共用課程狀態模型 (CourseState Model)

定義公務研習平台（臺北E大、e等公務園）統一輸出的課程狀態結構，
解耦平台內部 DOM 操作與工作台 UI 呈現。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class CourseStatus(Enum):
    """課程執行狀態列舉"""
    WAITING = "等待中"
    LEARNING = "研習中"
    QUIZ = "測驗中"
    SURVEY = "問卷中"
    COMPLETED = "已完成"
    SKIPPED = "已略過"
    MANUAL_REVIEW = "需人工確認"
    ERROR = "異常中"

    @property
    def badge_text(self) -> str:
        icons = {
            CourseStatus.WAITING: "○ 等待中",
            CourseStatus.LEARNING: "▶ 研習中",
            CourseStatus.QUIZ: "📝 測驗中",
            CourseStatus.SURVEY: "📋 問卷中",
            CourseStatus.COMPLETED: "✅ 已完成",
            CourseStatus.SKIPPED: "⏭️ 已略過",
            CourseStatus.MANUAL_REVIEW: "⚠️ 需人工確認",
            CourseStatus.ERROR: "❌ 異常中",
        }
        return icons.get(self, self.value)

    @property
    def color_hex(self) -> str:
        """狀態語意色彩；於任務板白、奶黃、淡綠、淡紅列底上皆達 WCAG 4.5:1 以上。"""
        colors = {
            CourseStatus.WAITING: "#4E5A62",        # 石板灰
            CourseStatus.LEARNING: "#2F5866",       # 深石板青
            CourseStatus.QUIZ: "#8A5A12",           # 深琥珀
            CourseStatus.SURVEY: "#4F5E3A",         # 深灰綠
            CourseStatus.COMPLETED: "#2F5E42",      # 深森林綠
            CourseStatus.SKIPPED: "#5F5A52",        # 深暖灰
            CourseStatus.MANUAL_REVIEW: "#A2402F",  # 深珊瑚紅
            CourseStatus.ERROR: "#9E2F2A",          # 深磚紅
        }
        return colors.get(self, "#6B777F")


@dataclass
class CourseState:
    """單門課程結構化狀態資料類別"""
    course_id: str
    course_name: str
    platform: str                           # "taipei_eda" 或 "egov"
    status: CourseStatus = CourseStatus.WAITING
    progress_pct: float = 0.0               # 0.0 ~ 100.0
    current_time_str: str = "00:00:00"      # 目前累積時數
    required_time_str: str = "00:00:00"     # 規定門檻時數
    exam_score: Optional[float] = None      # 測驗得分
    pass_score: Optional[float] = None      # 及格標準
    reason: str = ""                        # 處於目前狀態的原因
    next_step: str = ""                     # 系統或使用者下一步動作
    is_completed: bool = False              # 是否全數修畢
    needs_manual: bool = False              # 是否需要人工介入
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def formatted_study_progress(self) -> str:
        """研習時數字串格式化"""
        if self.required_time_str and self.required_time_str != "00:00:00":
            return f"{self.current_time_str} / {self.required_time_str} ({self.progress_pct:.1f}%)"
        return f"{self.current_time_str} ({self.progress_pct:.1f}%)"

    @property
    def status_summary(self) -> str:
        """狀態重點摘要"""
        msg = f"【{self.status.badge_text}】"
        if self.reason:
            msg += f" 原因: {self.reason}"
        if self.next_step:
            msg += f" ➜ 下一步: {self.next_step}"
        return msg
