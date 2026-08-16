import re
import time
import logging
from colorama import Fore, Style, init

init(autoreset=True)

# 人機協同測驗倒數逾時預設秒數（統一採 180 秒 / 03:00）
INTERACTIVE_QUIZ_TIMEOUT_SECONDS = 180


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


def set_driver_window_visibility(driver, visible: bool):
    """Win32 API 無痕切換 Selenium 控制之 Chrome 視窗顯示 (SW_SHOW) 或隱藏 (SW_HIDE)"""
    import sys
    if sys.platform != "win32" or not driver:
        return
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
            target_pids.add(service_pid)
            try:
                proc = psutil.Process(service_pid)
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
                
                # 排除 IME 輸入法、MSCTF 輔助視窗及 Chrome 訊息視窗，防止在工作列彈出 Default IME 殘留圖示
                if any(x in cls_name for x in ["IME", "MSCTFIME", "Chrome_WidgetWin_0"]):
                    return True

                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    found_hwnds.append(hwnd)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

        for hwnd in found_hwnds:
            user32.ShowWindow(hwnd, cmd)
            if visible:
                user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


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
    """智慧解析使用者貼回的 AI 解答字串，轉換為 {題號: [選中標籤清單]} 結構。"""
    if not raw_text or not raw_text.strip():
        return {}

    parsed = {}
    lines = raw_text.strip().split("\n")

    # 建立題號與問題資訊的索引
    q_map = {q.get("index", idx + 1): q for idx, q in enumerate(questions_data)}

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        # 匹配常見題號開頭：如 1. B, 1: B, 第1題: B, 1. (B), (1) B, 1: [B], 1. A, B, C 等
        match = re.match(
            r"^(?:第\s*)?(\d+)\s*(?:題|\.|\:|\)|\、|\-|\s)\s*(?:\[|\()?(.+?)(?:\]|\))?$",
            line_clean,
        )
        if match:
            try:
                q_idx = int(match.group(1))
                ans_body = match.group(2).strip()
            except ValueError:
                continue

            if q_idx not in q_map:
                continue

            q_info = q_map[q_idx]
            options = q_info.get("options", [])
            selected_labels = []

            # 1. 搜尋 A-D / 1-4 英數選項代號
            letters = re.findall(r"\b([A-Da-d])\b", ans_body)
            if not letters:
                letters = [ch.upper() for ch in ans_body if ch.upper() in ["A", "B", "C", "D"]]

            if letters:
                selected_labels.extend([l.upper() for l in letters])

            # 2. 是非題特殊對應（⭕/O/是/對 -> 第一個選項，❌/X/否/錯 -> 第二個選項）
            if not selected_labels and q_info.get("type") == "是非":
                if any(sym in ans_body for sym in ["⭕", "O", "o", "是", "對", "正確"]):
                    if options:
                        selected_labels.append(options[0].get("label", "A").upper())
                elif any(sym in ans_body for sym in ["❌", "X", "x", "否", "錯", "不正確"]):
                    if len(options) > 1:
                        selected_labels.append(options[1].get("label", "B").upper())

            # 3. 模糊文字比對：若回貼的是選項文字（如「機器學習」），比對匹配的選項
            if not selected_labels:
                for opt in options:
                    opt_t = opt.get("text", "").strip()
                    if opt_t and (opt_t in ans_body or ans_body in opt_t):
                        selected_labels.append(opt.get("label", "").upper())

            if selected_labels:
                # 若為單選題，只保留第一個選項
                if not q_info.get("is_multiple", False):
                    selected_labels = [selected_labels[0]]
                parsed[q_idx] = list(dict.fromkeys(selected_labels))  # 去重保持順序

    return parsed

