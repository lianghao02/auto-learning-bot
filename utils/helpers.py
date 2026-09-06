import re
import time
import logging
import threading
from colorama import Fore, Style, init

init(autoreset=True)

# 人機協同測驗倒數逾時預設秒數（統一採 180 秒 / 03:00）
INTERACTIVE_QUIZ_TIMEOUT_SECONDS = 180

# 新分頁／彈出視窗的 Win32 HWND 通常會晚於 Selenium 點擊才建立。
# 以短時間防護取代常駐監控，避免背景模式在切頁時短暫露出 Chrome。
_WINDOW_HIDE_GUARDS = {}
_WINDOW_HIDE_GUARD_LOCK = threading.Lock()


class CustomFormatter(logging.Formatter):
    """自定義日誌輸出格式，增加 UX 視覺辨識度"""

    def format(self, record):
        prefix = ""
        if record.levelno == logging.DEBUG:
            prefix = f"{Fore.WHITE}[DEBUG]{Style.RESET_ALL} "
        elif record.levelno == logging.INFO:
            prefix = f"{Fore.CYAN}[INFO]{Style.RESET_ALL} "
        elif record.levelno == logging.WARNING:
            prefix = f"{Fore.YELLOW}[WARN]{Style.RESET_ALL} "
        elif record.levelno == logging.ERROR:
            prefix = f"{Fore.RED}[ERROR]{Style.RESET_ALL} "
        elif record.levelno == logging.CRITICAL:
            prefix = f"{Fore.MAGENTA}[CRITICAL]{Style.RESET_ALL} "
        return f"{time.strftime('%H:%M:%S')} {prefix}{record.getMessage()}"


def get_logger():
    logger = logging.getLogger("LearningPilot")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(CustomFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def to_sec(t_str):
    if not t_str:
        return 0
    try:
        # 移除 HTML 標籤
        clean = re.sub("<[^<]+?>", "", str(t_str)).strip()
        if not clean:
            return 0

        # 處理 HH:MM:SS 或 MM:SS
        if ":" in clean:
            p = list(map(int, clean.split(":")))
            if len(p) == 3:
                return p[0] * 3600 + p[1] * 60 + p[2]
            if len(p) == 2:
                return p[0] * 60 + p[1]

        # 處理純數字 (可能是小時或分鐘，通常 API 回傳 0.5 代表半小時)
        # 若包含點號，視為小時
        if "." in clean:
            return int(float(clean) * 3600)
        # 若不含點號且數值 > 10，可能直接是秒數或分鐘，這裡保守視為秒
        val = float(clean)
        if val < 10:  # 可能是小時 (如 1, 2)
            return int(val * 3600)
        return int(val)
    except (ValueError, AttributeError, TypeError):
        return 0


def sec_to_str(s):
    return f"{int(s // 3600):02d}:{int((s % 3600) // 60):02d}:{int(s % 60):02d}"


def draw_bar(cur, tot, length=20):
    pct = (cur / tot) if tot > 0 else 0
    filled = int(length * pct)
    bar = f"[{'#' * filled}{'-' * (length - filled)}] {pct * 100:.1f}%"
    return bar


def set_driver_window_visibility(driver, visible: bool) -> int:
    """Win32 API 無痕切換 Selenium 控制之 Chrome 視窗顯示 (SW_SHOW) 或隱藏 (SW_HIDE)，徹底排除黑屏控制台"""
    import sys
    if visible and driver:
        # 使用者主動顯示瀏覽器時，必須先取消尚未到期的隱藏防護，
        # 否則背景執行緒會在下一輪掃描時又把視窗藏起來。
        with _WINDOW_HIDE_GUARD_LOCK:
            _WINDOW_HIDE_GUARDS.pop(id(driver), None)
    if sys.platform != "win32" or not driver:
        return 0
    try:
        import ctypes
        import psutil
        user32 = ctypes.windll.user32
        SW_HIDE = 0
        SW_SHOW = 5
        cmd = SW_SHOW if visible else SW_HIDE

        target_pids = set()
        if hasattr(driver, "service") and driver.service and driver.service.process:
            service_pid = driver.service.process.pid
            try:
                proc = psutil.Process(service_pid)
                # 僅納入 Chrome 瀏覽器子行程，排除 chromedriver 本身
                for child in proc.children(recursive=True):
                    target_pids.add(child.pid)
            except Exception:
                pass

        found_hwnds = []

        def enum_windows_callback(hwnd, extra):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in target_pids:
                class_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_buf, 256)
                cls_name = class_buf.value

                # 排除黑屏控制台、IME 輸入法、MSCTF 輔助視窗及 Chrome 訊息視窗
                if any(x in cls_name for x in ["ConsoleWindowClass", "IME", "MSCTFIME", "Chrome_WidgetWin_0"]):
                    return True

                # 只要是 Chrome 主視窗 (Chrome_WidgetWin_1) 或有標題之視窗，在剛彈出載入中時亦全面納入隱藏
                if "Chrome_WidgetWin_1" in cls_name or user32.GetWindowTextLengthW(hwnd) > 0:
                    found_hwnds.append(hwnd)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

        for hwnd in found_hwnds:
            user32.ShowWindow(hwnd, cmd)
            if visible:
                user32.SetForegroundWindow(hwnd)
        return len(found_hwnds)
    except Exception:
        return 0


def maintain_driver_windows_hidden(
    driver,
    *,
    duration: float = 2.0,
    interval: float = 0.15,
) -> None:
    """立即隱藏 Chrome，並在短時間內持續攔截延遲建立的新 HWND。

    同一個 driver 重複呼叫時只延長既有防護期限，不會建立大量背景執行緒。
    """
    if not driver:
        return

    set_driver_window_visibility(driver, False)
    duration = max(0.0, float(duration))
    interval = max(0.05, float(interval))
    if duration <= 0:
        return

    key = id(driver)
    deadline = time.monotonic() + duration
    start_worker = False
    with _WINDOW_HIDE_GUARD_LOCK:
        state = _WINDOW_HIDE_GUARDS.get(key)
        if state is None:
            state = {"driver": driver, "deadline": deadline}
            _WINDOW_HIDE_GUARDS[key] = state
            start_worker = True
        else:
            state["deadline"] = max(float(state["deadline"]), deadline)

    if not start_worker:
        return

    def _guard_worker():
        try:
            while True:
                with _WINDOW_HIDE_GUARD_LOCK:
                    current = _WINDOW_HIDE_GUARDS.get(key)
                    if current is not state:
                        return
                    remaining = float(state["deadline"]) - time.monotonic()
                if remaining <= 0:
                    return
                set_driver_window_visibility(driver, False)
                time.sleep(min(interval, remaining))
        finally:
            with _WINDOW_HIDE_GUARD_LOCK:
                if _WINDOW_HIDE_GUARDS.get(key) is state:
                    _WINDOW_HIDE_GUARDS.pop(key, None)

    threading.Thread(
        target=_guard_worker,
        daemon=True,
        name=f"ChromeHideGuard-{key}",
    ).start()


def format_quiz_prompt(course_name: str, questions_data: list) -> str:
    """將題目與選項轉換為提供給 ChatGPT / Gemini 的格式化提示詞。"""
    lines = [
        f"請針對以下《{course_name}》測驗題目進行回答。",
        "請直接以標準題號與選項代號回覆（例如 1. B 或 1: B，若是多選題例如 4. A, B, C），不需贅述冗長解析：\n"
    ]
    for q in questions_data:
        idx = q.get("index", 1)
        q_type = q.get("type", "單選")
        q_text = q.get("q_text", "")
        lines.append(f"{idx}. [{q_type}] {q_text}")
        for opt in q.get("options", []):
            label = opt.get("label", "")
            opt_text = opt.get("text", "")
            lines.append(f"   {label}. {opt_text}")
        lines.append("")
    return "\n".join(lines).strip()


def parse_ai_quiz_answers(raw_text: str, questions_data: list) -> dict:
    """智慧解析使用者貼回的 AI 解答字串，轉換為 {題號: [選中標籤清單]} 結構。全面相容 Markdown 格式、列表、表格與多種回覆風格。"""
    if not raw_text or not raw_text.strip():
        return {}

    parsed = {}
    q_map = {q.get("index", idx + 1): q for idx, q in enumerate(questions_data)}

    # 預處理：按行分割
    lines = raw_text.strip().split("\n")

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        # 1. 脫除前置清單/引用符號：如 "- ", "* ", "+ ", "• ", "> "
        line_clean = re.sub(r"^[\s\-\客\*\+\•\>\#\|]+\s*", "", line_clean).strip()
        # 脫除後置表格符號：如 " |"
        line_clean = re.sub(r"\s*\|\s*$", "", line_clean).strip()

        # 2. 脫除 Markdown 粗體/斜體/行內程式碼標記：如 "**", "*", "__", "_", "`"
        clean_text = re.sub(r"[\*\_\`\~]", "", line_clean).strip()
        if not clean_text:
            continue

        # 3. 匹配題號模式：
        # - "1. B", "1: B", "1、B", "1 - B", "1) B", "(1) B", "[1] B"
        # - "第1題: B", "第 1 題：B", "題1: B"
        # - 表格列 "1 | B" 或 "1 | B | 解析"
        match = re.match(
            r"^(?:第\s*)?(\d+)\s*(?:題|\.|\:|\：|\)|\、|\-|\s|\|)\s*(?:\[|\()?(.+?)(?:\]|\))?$",
            clean_text,
            re.IGNORECASE,
        )
        if match:
            try:
                q_idx = int(match.group(1))
                ans_body = match.group(2).strip()
            except (ValueError, IndexError):
                continue

            if q_idx not in q_map:
                continue

            q_info = q_map[q_idx]
            options = q_info.get("options", [])
            selected_labels = []

            # 清理 ans_body 前贅詞：如 "答案：", "答案是", "答：", "選項", "選擇", "建議選", "正確答案為"
            ans_body = re.sub(
                r"^(?:答案\s*[:：是為]?|答\s*[:：]?|選項\s*[:：]?|選擇\s*[:：]?|建議選\s*[:：]?|正確答案\s*[:：是為]?)\s*",
                "",
                ans_body,
                flags=re.IGNORECASE,
            ).strip()

            # 1. 是非題特殊對應（優先判定否定詞，避免「不正確」、「不是」被「正確」、「是」子字串誤傷）
            if q_info.get("type") == "是非":
                neg_syms = ["❌", "✕", "X", "x", "否", "錯", "不正確", "錯誤", "不是", "不對", "False", "false", "F", "f", "2"]
                pos_syms = ["⭕", "○", "O", "o", "是", "對", "正確", "True", "true", "T", "t", "1", "V", "v"]
                if any(sym in ans_body for sym in neg_syms):
                    if len(options) > 1:
                        selected_labels.append(options[1].get("label", "B").upper())
                elif any(sym in ans_body for sym in pos_syms):
                    if options:
                        selected_labels.append(options[0].get("label", "A").upper())

            # 2. 搜尋 A-Z / 1-9 英數選項代號（支援 5 選項 E、6 選項 F 等）
            if not selected_labels:
                valid_labels = [
                    opt.get("label", "").upper()
                    for opt in options
                    if opt.get("label")
                ]
                if not valid_labels:
                    valid_labels = [chr(65 + i) for i in range(max(len(options), 8))]

                # 支援 "A, B, C" / "A、B、C" / "A B C" / "(A)" / "[A]" / "ABC" / "E"
                letters = re.findall(r"\b([A-Za-z])\b", ans_body)
                if not letters:
                    # 連寫如 "ABC" 或有括號 "(A)"
                    letters = [ch.upper() for ch in ans_body if ch.upper() in valid_labels]
                matched_letters = [l.upper() for l in letters if l.upper() in valid_labels]
                if matched_letters:
                    selected_labels.extend(matched_letters)

            # 2b. 數字選項代號轉換：例如回覆 "5" 或 "(5)" 對應至第 5 個選項 "E"
            if not selected_labels and options:
                num_matches = re.findall(r"(?<!\d)([1-9])(?!\d)", ans_body)
                for num_str in num_matches:
                    num_idx = int(num_str) - 1
                    if 0 <= num_idx < len(options):
                        selected_labels.append(
                            options[num_idx].get("label", chr(65 + num_idx)).upper()
                        )

            # 3. 模糊文字比對：若回貼的是選項內容文字（如「以上皆是」、「巴黎協定」）
            if not selected_labels:
                for opt in options:
                    opt_t = opt.get("text", "").strip()
                    if opt_t and (opt_t in ans_body or ans_body in opt_t):
                        selected_labels.append(opt.get("label", "").upper())

            if selected_labels:
                # 判斷是否為多選題
                is_multiple = q_info.get("is_multiple", False) or q_info.get("type") == "多選"
                if not is_multiple:
                    selected_labels = [selected_labels[0]]
                parsed[q_idx] = list(dict.fromkeys(selected_labels))  # 去重保持順序

    # 4. Fallback：若無顯式題號（如 A\nD\nC\nB），且非空行數等於測驗題數，按行序映射
    if not parsed and questions_data:
        candidate_lines = []
        for line in raw_text.splitlines():
            c_line = line.strip()
            c_line = re.sub(r"^[\s\-\客\*\+\•\>\#\|]+\s*", "", c_line).strip()
            c_line = re.sub(r"[\*\_\`\~]", "", c_line).strip()
            if c_line:
                candidate_lines.append(c_line)
        if len(candidate_lines) == len(questions_data):
            for i, line_text in enumerate(candidate_lines, 1):
                if i in q_map:
                    q_info = q_map[i]
                    options = q_info.get("options", [])
                    selected = []
                    # 清理前綴贅詞
                    line_body = re.sub(
                        r"^(?:答案\s*[:：是為]?|答\s*[:：]?|選項\s*[:：]?|選擇\s*[:：]?|建議選\s*[:：]?|正確答案\s*[:：是為]?)\s*",
                        "",
                        line_text,
                        flags=re.IGNORECASE,
                    ).strip()
                    if q_info.get("type") == "是非":
                        neg_syms = ["❌", "✕", "X", "x", "否", "錯", "不正確", "錯誤", "不是", "不對", "False", "false", "F", "f", "2"]
                        pos_syms = ["⭕", "○", "O", "o", "是", "對", "正確", "True", "true", "T", "t", "1", "V", "v"]
                        if any(sym in line_body for sym in neg_syms):
                            if len(options) > 1:
                                selected.append(options[1].get("label", "B").upper())
                        elif any(sym in line_body for sym in pos_syms):
                            if options:
                                selected.append(options[0].get("label", "A").upper())
                    if not selected:
                        valid_labels = [
                            opt.get("label", "").upper()
                            for opt in options
                            if opt.get("label")
                        ]
                        if not valid_labels:
                            valid_labels = [
                                chr(65 + k) for k in range(max(len(options), 8))
                            ]
                        letters = re.findall(r"\b([A-Za-z])\b", line_body)
                        if not letters:
                            letters = [
                                ch.upper()
                                for ch in line_body
                                if ch.upper() in valid_labels
                            ]
                        matched_letters = [
                            l.upper() for l in letters if l.upper() in valid_labels
                        ]
                        if matched_letters:
                            selected.extend(matched_letters)
                    if not selected and options:
                        num_matches = re.findall(r"(?<!\d)([1-9])(?!\d)", line_body)
                        for num_str in num_matches:
                            num_idx = int(num_str) - 1
                            if 0 <= num_idx < len(options):
                                selected.append(
                                    options[num_idx]
                                    .get("label", chr(65 + num_idx))
                                    .upper()
                                )
                    if not selected:
                        for opt in options:
                            opt_t = opt.get("text", "").strip()
                            if opt_t and (opt_t in line_body or line_body in opt_t):
                                selected.append(opt.get("label", "").upper())
                    if selected:
                        is_multiple = q_info.get("is_multiple", False) or q_info.get("type") == "多選"
                        if not is_multiple:
                            selected = [selected[0]]
                        parsed[i] = list(dict.fromkeys(selected))

    return parsed


def parse_multiple_choice_answers(raw_ans, num_options=4):
    """將各類多選答案（如 'A,B,C'、'A、B、C'、'A B C'、'ABCD'、'1,2,3'、'1 2 3'、['A','B']）
    標準化為大寫字母清單（如 ['A', 'B', 'C']）。"""
    if not raw_ans:
        return []
    if isinstance(raw_ans, list):
        items = []
        for it in raw_ans:
            items.extend(parse_multiple_choice_answers(it, num_options))
        return sorted(list(dict.fromkeys(items)))
    text = str(raw_ans).strip()
    if not text:
        return []
    parts = [p.strip() for p in re.split(r'[,，、;\s/]+', text) if p.strip()]
    res = []
    for p in parts:
        if re.fullmatch(r'[A-Za-z]+', p) and len(p) > 1:
            for ch in p.upper():
                res.append(ch)
        elif re.fullmatch(r'[A-Za-z]', p):
            res.append(p.upper())
        elif p.isdigit():
            val_int = int(p)
            if 1 <= val_int <= num_options:
                res.append(chr(ord('A') + val_int - 1))
            elif val_int == 0 and num_options > 0:
                res.append('A')
            elif 0 <= val_int < num_options:
                res.append(chr(ord('A') + val_int))
        else:
            m_ch = re.findall(r'[A-Za-z]', p)
            if m_ch:
                for ch in m_ch:
                    res.append(ch.upper())
    return sorted(list(dict.fromkeys(res)))

