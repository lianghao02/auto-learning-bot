"""課程結案儀表板 Presenter 模組。

職責僅負責純文字排版呈現，不修改任何業務統計、不讀寫非必要全域狀態。
"""

def render_course_completion_card(
    *,
    course_name: str,
    has_quiz: bool,
    quiz_passed: bool | None,        # True=及格, False=未及格, None=免測驗/無測驗
    survey_completed: bool | None,   # True=已完成, False=未完成, None=無問卷
    course_completed: bool,
    solve_mode: str | None,          # "ai" | "quiz_bank" | "manual" | "skipped" | None
    course_api_calls: int,           # 本門課實際消耗 (無測驗/題庫命中時精準為 0)
    today_api_calls: int,            # 全日累計消耗
    daily_limit: int = 1500,
    session_completed: int = 0,      # 本次累計完成門數
    session_quiz_passed: int = 0,    # 本次累計測驗通過門數
    session_quiz_total: int = 0,     # 本次有測驗的總門數 (排除免測門數)
) -> str:
    """格式化每門課即時動態成果卡片（純 Presenter）。"""
    # 1. 測驗成果判定 (三態)
    if not has_quiz or quiz_passed is None:
        quiz_text = "➖ 本課程無測驗"
    elif quiz_passed is True:
        quiz_text = "🎉 達標及格"
    else:
        quiz_text = "⚠️ 未達門檻"

    # 2. 問卷狀態判定
    if survey_completed is True:
        survey_text = "✅ 已完成"
    elif survey_completed is False:
        survey_text = "⚠️ 待填寫"
    else:
        survey_text = "➖ 無問卷"

    # 3. 本門作答方式
    if not has_quiz:
        solve_mode_text = "➖ 無須作答"
    elif solve_mode == "ai":
        solve_mode_text = "🤖 Gemini 批次秒答"
    elif solve_mode == "quiz_bank":
        solve_mode_text = "📚 本機題庫秒殺"
    elif solve_mode == "skipped":
        solve_mode_text = "⏩ 跳過測驗模式"
    elif solve_mode == "manual":
        solve_mode_text = "✋ 手動填答"
    else:
        solve_mode_text = "➖ 無須作答"

    # 4. 本次執行累計文字
    if session_quiz_total > 0:
        session_text = f"已完成 {session_completed}/{session_completed} 門課程（測驗通過 {session_quiz_passed}/{session_quiz_total} 門）"
    else:
        session_text = f"已完成 {session_completed}/{session_completed} 門課程"

    # 5. 配額與健康狀態
    remaining = max(0, daily_limit - today_api_calls)
    percentage = round((remaining / max(1, daily_limit)) * 100, 1)
    status_icon = "🟢" if remaining > 300 else ("🟡" if remaining > 50 else "🔴")

    card = f"""
┌────────────────────────────────────────────────────────────┐
│ 🎯 行政效能領航員 - 即時研習成效儀表板                        │
│ ────────────────────────────────────────────────────────── │
│ 📚 最新完成課程：【{course_name}】
│ 🏆 測驗成果：{quiz_text} ｜ 問卷：{survey_text}
│ ⚡ 本門作答方式：{solve_mode_text}
│                                                            │
│ 📊 本次執行累計：{session_text}
│ 💳 本門 API 呼叫：{course_api_calls} 次 ｜ 今日累計已用：{today_api_calls} / {daily_limit} 次
│ {status_icon} 配額健康狀態：充足（剩餘 {percentage}%，實際以官方為準）
└────────────────────────────────────────────────────────────┘"""
    return card.strip()
