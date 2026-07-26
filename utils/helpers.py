import re
import time
import logging
from colorama import Fore, Style, init

init(autoreset=True)


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

