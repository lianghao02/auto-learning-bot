import sys, io

# Send Taipei E-da console output to both the UI/log and a console when one exists.
# pythonw.exe has sys.stdout = None, so stdout.buffer must be guarded.
class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self._streams = [st for st in streams if st is not None]

    def write(self, s):
        for st in self._streams:
            try:
                st.write(s)
                st.flush()
            except Exception:
                pass
        return len(s)

    def flush(self):
        for st in self._streams:
            try:
                st.flush()
            except Exception:
                pass

_console = None
if sys.stdout is not None:
    if hasattr(sys.stdout, "buffer"):
        _console = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    else:
        _console = sys.stdout

_logfile = open("taipei_eda_course.log", "a", encoding="utf-8")
# ⚠️ 保留原始 sys.stdout，讓 run_taipei_eda 的 _UILog 作為唯一 UI 路由
# 不在模組載入時替換 sys.stdout，避免 _Tee 疊套造成訊息重複

import requests, time, urllib3, cv2, numpy as np, ddddocr, json, random, re, os, threading
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoAlertPresentException, UnexpectedAlertPresentException

from quiz_bank import do_quiz_with_bank, do_feedback

from utils.helpers import set_driver_window_visibility

# ── DOM 語意彈性相容防護網 (Resilient Selector Fallback) ──────────────────────
def find_element_resilient(driver, css_selector=None, text_keywords=None, tag_names=None, timeout=5):
    """
    多層彈性元素定位工具：
      1. 第一優先：精確 CSS Selector 搜尋。
      2. 二級語意 Fallback：當 CSS 定位失效（平台改版）時，自動以 HTML5 語意
         搜尋含有 text_keywords 的 button/a/input 元素。

    Args:
        css_selector:   CSS 選擇器字串（優先）
        text_keywords:  備用文字關鍵字清單（如 ['上課', '進入教室']）
        tag_names:      要搜尋的 HTML 標籤（預設 ['button', 'a', 'input']）
        timeout:        最長等待秒數（針對 CSS selector）

    Returns:
        WebElement 或 None
    """
    tag_names = tag_names or ['button', 'a', 'input']

    # 優先：CSS Selector
    if css_selector:
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
            )
            if el and el.is_displayed():
                return el
        except Exception:
            pass

    # 二級：語意文字關鍵字 Fallback
    if text_keywords:
        for tag in tag_names:
            try:
                elements = driver.find_elements(By.TAG_NAME, tag)
                for el in elements:
                    try:
                        text = (el.text or el.get_attribute('value') or el.get_attribute('title') or '').strip()
                        if any(kw in text for kw in text_keywords):
                            if el.is_displayed():
                                return el
                    except Exception:
                        continue
            except Exception:
                continue
    return None

_DRIVER_LOCK = threading.Lock()
_ACTIVE_DRIVER = None
_TAIPEI_IS_HIDDEN = False

def force_close_active_driver():
    global _ACTIVE_DRIVER
    with _DRIVER_LOCK:
        driver = _ACTIVE_DRIVER
        _ACTIVE_DRIVER = None
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass

def toggle_taipei_driver_visibility(visible: bool):
    global _ACTIVE_DRIVER, _TAIPEI_IS_HIDDEN
    _TAIPEI_IS_HIDDEN = not visible
    with _DRIVER_LOCK:
        driver = _ACTIVE_DRIVER
    if driver:
        try:
            set_driver_window_visibility(driver, visible)
        except Exception:
            pass

def _auto_hide_taipei_popups_if_needed(driver=None):
    global _ACTIVE_DRIVER, _TAIPEI_IS_HIDDEN
    if _TAIPEI_IS_HIDDEN:
        d = driver or _ACTIVE_DRIVER
        if d:
            try:
                set_driver_window_visibility(d, False)
            except Exception:
                pass

_ocr = ddddocr.DdddOcr(show_ad=False)

RESIDENCE_TIME = 75   # 每個章節停留秒數

# 載入 config：AI keys 等設定

def load_config(path=None):
    """
    從 config.json 載入設定。
    支援兩種格式：
      - {settings: {...}} 會取 settings
      - 直接傳入 settings dict
    找不到或讀取失敗時回傳空 dict。
    """
    candidates = [
        path,
        os.path.join(os.path.dirname(__file__), 'config.json'),
        'config.json',
    ]
    for p in candidates:
        if p and os.path.exists(p):
            try:
                with open(p, encoding='utf-8') as f:
                    raw = json.load(f)
                cfg = raw.get('settings', raw) if isinstance(raw, dict) else {}
                print(f'  [config] 已載入: {p}')
                return cfg
            except Exception as e:
                print(f'  [config] 讀取失敗 {p}: {e}')
    print('  [config] 找不到 config.json，AI 補答停用')
    return {}

# 共用工具

def parse_study_time(study_str):
    s = study_str or ''
    hrs  = int(re.search(r'(\d+)時', s).group(1)) if re.search(r'(\d+)時', s) else 0
    mins = int(re.search(r'(\d+)分', s).group(1)) if re.search(r'(\d+)分', s) else 0
    secs = int(re.search(r'(\d+)秒', s).group(1)) if re.search(r'(\d+)秒', s) else 0
    return hrs * 3600 + mins * 60 + secs

def solve_captcha(img_bytes):
    if not img_bytes:
        return ''
    
    # 策略 1: 直接以原圖進行 ddddocr 辨識 (預設無損辨識率最高)
    try:
        raw = _ocr.classification(img_bytes)
        digits = ''.join(c for c in raw if c.isdigit())
        if len(digits) == 4:
            return digits
    except Exception:
        pass

    # 策略 2: 放大兩倍 + 灰階轉換 (處理低對比度圖像)
    try:
        arr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, buf = cv2.imencode('.png', gray)
            raw = _ocr.classification(buf.tobytes())
            digits = ''.join(c for c in raw if c.isdigit())
            if len(digits) == 4:
                return digits
    except Exception:
        pass

    # 策略 3: 銳化濾鏡 (備用防護)
    try:
        arr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            kernel = np.array([[0,-1,0],[-1,5,-1],[0,-1,0]])
            sharp = cv2.filter2D(gray, -1, kernel)
            _, buf = cv2.imencode('.png', sharp)
            raw = _ocr.classification(buf.tobytes())
            digits = ''.join(c for c in raw if c.isdigit())
            if len(digits) == 4:
                return digits
    except Exception:
        pass

    return ''

def dismiss_alerts(driver):
    messages = []
    for _ in range(5):
        try:
            alert = driver.switch_to.alert
            text = alert.text or ''
            messages.append(text)
            print(f'  [Alert] {text}')
            alert.accept()
            time.sleep(0.5)
        except NoAlertPresentException:
            break
    return messages

def has_multi_window_alert(messages):
    return any('禁止多重視窗' in str(msg) for msg in (messages or []))

def deep_commit(driver):
    try:
        driver.execute_script(
            "function deepCommit(win){"
            "  try{ if(win.API) win.API.LMSCommit(''); }catch(e){}"
            "  try{ if(win.API_1484_11) win.API_1484_11.Commit(''); }catch(e){}"
            "  if(win.frames){ for(let i=0;i<win.frames.length;i++) deepCommit(win.frames[i]); }"
            "} deepCommit(window);"
        )
    except Exception:
        pass


def sec_to_hms(total_sec):
    total_sec = max(int(total_sec or 0), 0)
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f'{hrs:02d}:{mins:02d}:{secs:02d}'

def draw_bar(cur_sec, target_sec, width=20):
    if target_sec <= 0:
        pct = 1.0
    else:
        pct = max(0.0, min(float(cur_sec) / float(target_sec), 1.0))
    filled = int(round(pct * width))
    return '[' + ('#' * filled) + ('-' * (width - filled)) + f'] {pct*100:.1f}%'

def pause_and_mute_media(driver):
    try:
        driver.execute_script("""
            function visit(win) {
                try {
                    win.document.querySelectorAll('video,audio').forEach(function(media) {
                        media.muted = true;
                        media.volume = 0;
                        try { media.pause(); } catch(e) {}
                    });
                } catch(e) {}
                try {
                    for (var i = 0; i < win.frames.length; i++) visit(win.frames[i]);
                } catch(e) {}
            }
            visit(window);
        """)
    except Exception:
        pass


# 登入

def do_login(driver, wait, username='', password=''):
    if not username or not password:
        print('  [登入失敗] 缺少帳號或密碼，請先在程式設定中儲存登入資料')
        return False

    driver.get('https://elearning.taipei/mpage/login')
    wait.until(EC.presence_of_element_located((By.ID, 'pid')))
    time.sleep(0.8)
    driver.execute_script("refreshCaptcha();")
    time.sleep(0.8)

    max_submit_attempts = 15
    for attempt in range(max_submit_attempts):
        digits = ''
        # 最多嘗試 5 次自動刷新圖像，直到精確取得 4 位數驗證碼
        for refresh_retry in range(5):
            try:
                # 直接擷取 Chrome 已安全載入的驗證碼元素，避免另開 HTTP
                # 連線時受到網站憑證鏈或工作階段 Cookie 差異影響。
                captcha_el = wait.until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, '.captcha-img'))
                )
                img_bytes = captcha_el.screenshot_as_png
                digits = solve_captcha(img_bytes)
            except Exception as exc:
                if refresh_retry == 0:
                    print(f'  [驗證碼] 擷取或辨識失敗：{exc}')
                digits = ''
            if digits:
                break
            driver.execute_script("refreshCaptcha();")
            time.sleep(0.8)

        print(f'  captcha [{attempt+1}]: {digits!r}')
        if not digits:
            print(f'  [警告] 第 {attempt+1} 次無法自動辨識 4 位數驗證碼，重新載入登入頁面...')
            driver.get('https://elearning.taipei/mpage/login')
            wait.until(EC.presence_of_element_located((By.ID, 'pid')))
            driver.execute_script("refreshCaptcha();")
            time.sleep(0.8)
            continue

        for fid in ['pid', 'password', 'auth']:
            try:
                driver.find_element(By.ID, fid).clear()
            except Exception:
                pass
        driver.find_element(By.ID, 'pid').send_keys(username)
        driver.find_element(By.ID, 'password').send_keys(password)
        driver.find_element(By.ID, 'auth').send_keys(digits)
        driver.find_element(By.CSS_SELECTOR, 'button[type=submit]').click()
        time.sleep(2.5)

        if 'login' not in driver.current_url:
            print(f'  Login OK -> {driver.current_url}')
            return True

        driver.get('https://elearning.taipei/mpage/login')
        wait.until(EC.presence_of_element_located((By.ID, 'pid')))
        driver.execute_script("refreshCaptcha();")
        time.sleep(0.8)

    return False

# 課程清單

def get_course_list(driver, wait):
    """讀取課程清單，回傳課程 list；首頁無法讀取時回傳 ``None``。"""
    driver.get('https://elearning.taipei/mpage/sso_moodle?redirectPage=courserecord')
    time.sleep(3)
    try:
        btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, '//button[contains(text(),"更新我的課程")]')
        ))
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(3)
    except Exception:
        pass

    def td_text(cell):
        try:
            value = driver.execute_script(
                "return (arguments[0].innerText || arguments[0].textContent || '').trim();",
                cell,
            )
            return (value or '').strip()
        except Exception:
            return cell.text.strip()

    all_courses = []
    page_num = 1

    while True:
        parsed_page = []
        last_row_count = 0
        
        # 最多嘗試 15 次等待當前頁面資料載入完成 (仿照原作者邏輯)
        for attempt in range(1, 16):
            rows = driver.find_elements(By.CSS_SELECTOR, 'table tbody tr')
            last_row_count = len(rows)
            parsed_page = []
            blank_rows = 0

            for row in rows:
                cells = row.find_elements(By.CSS_SELECTOR, 'td')
                if len(cells) < 12:
                    continue

                values = [td_text(cell) for cell in cells]
                if not any(values):
                    blank_rows += 1
                    continue

                name = values[0]
                done = values[11]
                study = values[3]
                cert_hrs = values[4]
                score = values[8]
                quest = values[10]
                links = cells[0].find_elements(By.CSS_SELECTOR, 'a[href]')
                href = links[0].get_attribute('href') if links else ''
                parsed_page.append({
                    'name': name, 'done': done, 'href': href,
                    'cert_hrs': cert_hrs, 'score': score,
                    'quest': quest, 'study': study,
                })

            if parsed_page:
                break

            if rows:
                print(f'  [掃描] 頁面 {page_num} - 第 {attempt} 次讀到 {len(rows)} 列，但文字尚未載入，等待中...')
            time.sleep(1)

        if not parsed_page:
            print(f'  [掃描] 頁面 {page_num} 課程表格未讀到有效文字，row_count={last_row_count}')
            # 第一頁一筆都讀不到通常代表 Session 已失效或頁面尚未正確載入。
            # 不可把這種情況當成「沒有待處理課程」，否則會產生錯誤的完成訊息。
            if page_num == 1:
                print('  [錯誤] [掃描] 首頁課程清單讀取失敗，停止本次流程以避免誤判為全部完成。')
                return None
            break

        all_courses.extend(parsed_page)
        print(f'  [掃描] 成功讀取第 {page_num} 頁，共 {len(parsed_page)} 門課程')

        # 嘗試翻到下一頁
        try:
            # 取得點擊前的活動頁碼
            active_elem = driver.find_elements(By.CSS_SELECTOR, "a.paginate-page.active")
            current_page_text = active_elem[0].text.strip() if active_elem else ""

            # 尋找包含下一頁箭頭的 a 標籤
            next_btns = driver.find_elements(By.XPATH, '//a[contains(@class, "paginate-page")][./i[contains(@class, "fa-angle-right")]]')
            if not next_btns:
                break # 沒有下一頁按鈕，停止翻頁
            
            next_btn = next_btns[0]
            
            # 使用 JS 進行點擊以避免元素被遮擋的錯誤
            driver.execute_script("arguments[0].click();", next_btn)
            
            # 等待當前活動頁碼改變 (代表切頁完成)，最多等 5 秒
            page_changed = False
            for _ in range(5):
                time.sleep(1)
                new_active_elem = driver.find_elements(By.CSS_SELECTOR, "a.paginate-page.active")
                new_page_text = new_active_elem[0].text.strip() if new_active_elem else ""
                if new_page_text and new_page_text != current_page_text:
                    page_changed = True
                    break
            
            if not page_changed:
                break # 頁碼未改變，停止翻頁
            
            page_num += 1
            
        except Exception as e:
            # 若有任何翻頁異常，視同已到最後一頁，結束迴圈
            break

    print(f'  [掃描] 翻頁掃描完成，總共取得 {len(all_courses)} 門課程')
    return all_courses


def _clean_status(text):
    return str(text or '').strip()

def is_study_incomplete(course, req_minutes=None):
    done_str = _clean_status(course.get('done'))
    if '已完成' in done_str or done_str == '完成':
        return False

    already_sec = parse_study_time(course.get('study', ''))

    # 💡 優先採用課程頁偵測到的特定閱讀時數門檻（例如：閱讀時間達36分鐘以上）
    target_min = req_minutes or course.get('req_minutes')
    if target_min:
        return already_sec < int(float(target_min) * 60)

    # 備用時數比對：依認證時數之 50% 門檻計算
    try:
        cert_hrs = float(course.get('cert_hrs') or 0)
    except Exception:
        cert_hrs = 0
    if cert_hrs > 0:
        target_sec = int(cert_hrs * 3600 * 0.5)
        if target_sec > 0 and already_sec < target_sec:
            return True

    if '未完成' in done_str:
        return True

    return False

def is_questionnaire_pending(course):
    quest = _clean_status(course.get('quest'))
    return quest == '填寫'

def is_quiz_passed(course, req_score=None):
    score = _clean_status(course.get('score')).replace(' ', '')
    if not score or score == '-':
        return False
    if any(word in score for word in ['通過', '合格', '已完成', '及格']):
        return True
    nums = []
    for raw in re.findall(r'\d+(?:\.\d+)?', score):
        try:
            nums.append(float(raw))
        except Exception:
            pass
    # 💡 支援個別課程設定之及格門檻（預設 60 分，若課程指定 80 分則以 80 分為準）
    pass_threshold = float(req_score or course.get('req_score') or 60.0)
    return bool(nums) and max(nums) >= pass_threshold

def is_quiz_pending(course, req_score=None):
    score = _clean_status(course.get('score')).replace(' ', '')
    if not score or score == '-':
        return False
    if any(word in score for word in ['未通過', '未完成', '不合格', '需補考', '待測驗']):
        return True
    return not is_quiz_passed(course, req_score=req_score)

def needs_course_processing(course):
    return (
        is_study_incomplete(course) or
        is_quiz_pending(course) or
        is_questionnaire_pending(course)
    )

def taipei_course_priority(course):
    """Order Taipei E-da work by the user's rule.

    0: study time already reached, still needs quiz + questionnaire
    1: study time already reached, only questionnaire is pending
    2: study time not reached yet
    """
    study_needed = is_study_incomplete(course)
    quiz_pending = is_quiz_pending(course)
    questionnaire_pending = is_questionnaire_pending(course)
    if not study_needed and quiz_pending and questionnaire_pending:
        return 0
    if not study_needed and questionnaire_pending:
        return 1
    if study_needed:
        return 2
    if quiz_pending:
        return 0
    return 9

def pending_courses_sorted(courses):
    pending = [c for c in courses if c.get('href') and needs_course_processing(c)]
    return sorted(pending, key=lambda c: (taipei_course_priority(c), c.get('name', '')))


def build_taipei_work_queue(driver, courses):
    """Build the Taipei E-da queue with module-aware priority.

    The course-record table does not reliably tell whether score "-" means
    "no quiz" or "quiz not done". For courses that already reached study time
    and have a pending questionnaire, pre-scan the course page so quiz+feedback
    courses are handled before feedback-only courses.
    """
    queue = []
    for course in courses:
        if not course.get('href') or not needs_course_processing(course):
            continue

        item = dict(course)
        priority = taipei_course_priority(item)
        if not is_study_incomplete(item) and is_questionnaire_pending(item):
            modules = get_course_modules(driver, item['href'])
            item['_modules'] = modules
            if modules.get('quiz_url') and not is_quiz_passed(item):
                priority = 0
            else:
                priority = 1
        queue.append((priority, item.get('name', ''), item))

    return [item for _, _, item in sorted(queue, key=lambda row: (row[0], row[1]))]


# ── 課程模組偵測（quiz / feedback cmid）─────────────────

def get_course_modules(driver, course_href):
    """
    進入課程頁，掃描所有 mod/quiz 和 mod/feedback 連結。
    回傳 dict:
      {
        'course_id': int or None,
        'quiz_url':  str or None,   # mod/quiz/view.php?id=XXXX
        'fb_url':    str or None,   # mod/feedback/view.php?id=XXXX
      }
    """
    result = {'course_id': None, 'quiz_url': None, 'fb_url': None}
    if not course_href:
        return result

    try:
        driver.get(course_href)
        time.sleep(3)
        dismiss_alerts(driver)

        # 從 URL 抓 course_id（支援 course/view.php?id=XXX 或 courserecord 頁）
        m = re.search(r'course[/=](\d+)', driver.current_url)
        if not m:
            m = re.search(r'\?id=(\d+)', driver.current_url)
        if m:
            result['course_id'] = int(m.group(1))

        # 掃描頁面上的特定完成條件（例如「閱讀時間達36分鐘以上」、「測驗分數達80分以上」）
        try:
            body_txt = driver.find_element(By.TAG_NAME, 'body').text
            m_time = re.search(r'閱讀時間達\s*(\d+(?:\.\d+)?)\s*分鐘', body_txt)
            if m_time:
                result['req_minutes'] = float(m_time.group(1))
                print(f'  🎯 偵測到課程特定時數門檻：{int(result["req_minutes"])} 分鐘')

            m_score = re.search(r'測驗分數達\s*(\d+(?:\.\d+)?)\s*分', body_txt)
            if m_score:
                result['req_score'] = float(m_score.group(1))
                print(f'  🎯 偵測到課程特定及格門檻：{int(result["req_score"])} 分')
        except Exception:
            pass

        # 掃所有連結
        links = driver.find_elements(By.CSS_SELECTOR, 'a[href]')
        for lnk in links:
            href = lnk.get_attribute('href') or ''
            if 'mod/quiz/view.php' in href and not result['quiz_url']:
                result['quiz_url'] = href
            if 'mod/feedback/view.php' in href and not result['fb_url']:
                result['fb_url'] = href

        print(f'  [模組] course_id={result["course_id"]} quiz={result["quiz_url"]} fb={result["fb_url"]}')
    except Exception as e:
        print(f'  [模組] 偵測失敗: {e}')

    return result

def clear_session_and_relogin(driver, wait, config=None):
    try:
        cfg = config or {}
        username = cfg.get('account') or cfg.get('username') or ''
        password = cfg.get('password') or ''
        if username and password:
            print('  🔄 偵測到「禁止多重視窗」鎖定，正在自動清理 Session Cookie 並重新登入以釋放鎖定...')
            driver.delete_all_cookies()
            time.sleep(1)
            if do_login(driver, wait, username=username, password=password):
                print('  ✅ 已成功重新登入並重置 SCORM Session')
                return True
    except Exception as e:
        print(f'  ⚠️ 自動重新登入失敗: {e}')
    return False


def recover_from_multi_window_lock(driver, wait, course_url, config=None):
    """遇到持續性的多重視窗鎖定時，重新登入後回到原課程頁。"""
    if not clear_session_and_relogin(driver, wait, config):
        return False
    try:
        driver.get(course_url)
        time.sleep(3)
        msgs = dismiss_alerts(driver)
        if has_multi_window_alert(msgs):
            print('  ⚠️ 重新登入後仍收到多重視窗警告，本課程暫停處理。')
            return False
        print('  ✅ 已回到課程頁，將重新嘗試進入課程播放器。')
        return True
    except Exception as e:
        print(f'  ⚠️ 重新登入後無法回到課程頁: {e}')
        return False

def get_scorm_player_url(driver, wait, course_url, config=None):
    driver.get(course_url)
    time.sleep(3)
    msgs = dismiss_alerts(driver)
    if has_multi_window_alert(msgs):
        print('  ⚠️ 臺北E大發出多重視窗警告，嘗試重新登入重置 Session...')
        if not recover_from_multi_window_lock(driver, wait, course_url, config):
            return None

    def current_is_player():
        url = driver.current_url or ''
        return 'mod/scorm/player.php' in url or bool(get_chapters(driver))

    def find_scorm_link():
        def is_valid_scorm_href(h):
            if not h or 'javascript' in h.lower():
                return False
            # 排除問卷、測驗、討論區、作業等非 SCORM 模組 URL
            if any(bad in h for bad in ['mod/feedback', 'mod/quiz', 'mod/forum', 'mod/assign', 'mod/page', 'mod/resource']):
                return False
            # 排除指向當前課程主頁本身的連結，防止同頁重複載入
            clean_h = h.split('#')[0].rstrip('/')
            clean_curr = (driver.current_url or '').split('#')[0].rstrip('/')
            clean_course = (course_url or '').split('#')[0].rstrip('/')
            if clean_h == clean_curr or clean_h == clean_course:
                return False
            return True

        # 1. 在當前頁面尋找 direct scorm 連結
        scorm_css = 'a[href*="mod/scorm/view.php"], a[href*="mod/scorm/player.php"], a[href*="mod/scorm"], .modtype_scorm a, .activityinstance a'
        links = driver.find_elements(By.CSS_SELECTOR, scorm_css)
        for link in links:
            href = link.get_attribute('href') or ''
            text = (link.text or link.get_attribute('title') or '').strip()
            if is_valid_scorm_href(href):
                return href, text or href

        # 2. 若簡介頁無 mod/scorm 連結，進行語意彈性搜尋，尋找「進入教室/上課」按鈕
        ENTER_KEYWORDS = ['上課', '進入教室', '開始學習', '閱讀課程', '開始閱讀', '進入課程', 'Go to course', '立即上課', '閱讀教材']
        DANGER_KEYWORDS = ['退選', '取消', '刪除', 'Unenroll', 'Cancel', 'Delete', '登出', 'Logout', '搜尋', 'Search',
                           '問卷', '滿意度', '填寫', '回答', 'feedback', 'survey', 'questionnaire']
        for css in ['a[href*="sso"]', 'a[href*="redirect"]', 'a.btn', 'button', 'a']:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, css)
                for el in elements:
                    txt = ((el.text or '') + ' ' + (el.get_attribute('value') or '') + ' ' + (el.get_attribute('title') or '')).strip()
                    if any(k in txt for k in ENTER_KEYWORDS) and not any(dk in txt for dk in DANGER_KEYWORDS):
                        href = el.get_attribute('href') or ''
                        if is_valid_scorm_href(href):
                            return href, txt[:30]
            except Exception:
                pass

        return '', ''

    def enter_from_scorm_view():
        msgs = dismiss_alerts(driver)
        if has_multi_window_alert(msgs):
            # 先 dismiss 再檢查，有時 player 頁面仍可使用
            print('  ⚠️ 多重視窗警告 (enter_from_scorm_view)，dismiss 後檢查 player...')
            time.sleep(1)
            dismiss_alerts(driver)
        pause_and_mute_media(driver)
        if current_is_player():
            return True

        # 1. 優先嘗試尋找並提交包含 player.php 的表單
        try:
            forms = driver.find_elements(By.CSS_SELECTOR, 'form[action*="mod/scorm/player.php"], form[action*="player.php"]')
            for form in forms:
                action = form.get_attribute('action') or ''
                if 'player.php' in action:
                    print(f'  ▶️ 正式提交 SCORM 播放器表單: {action[:50]}')
                    driver.execute_script("arguments[0].submit();", form)
                    time.sleep(3)
                    dismiss_alerts(driver)
                    # 若點擊後開啟新視窗，自動切換至最新視窗
                    if len(driver.window_handles) > 1:
                        driver.switch_to.window(driver.window_handles[-1])
                        _auto_hide_taipei_popups_if_needed(driver)
                    if current_is_player():
                        return True
        except Exception:
            pass

        selectors = [
            'a[href*="mod/scorm/player.php"]',
            'form[action*="mod/scorm/player.php"] input[type=submit]',
            'form[action*="mod/scorm/player.php"] button',
            'input[type=submit]',
            'button[type=submit]',
            'button',
            'a.btn',
            'a',
        ]
        seen = set()
        for selector in selectors:
            try:
                buttons = driver.find_elements(By.CSS_SELECTOR, selector)
            except Exception:
                buttons = []
            for btn in buttons:
                try:
                    key = btn.id or (btn.get_attribute('outerHTML')[:50] if hasattr(btn, 'get_attribute') else str(btn))
                    if key in seen:
                        continue
                    seen.add(key)
                    href = btn.get_attribute('href') or ''
                    value = btn.get_attribute('value') or ''
                    text = ((btn.text or '') + ' ' + value + ' ' + href).strip()
                    is_submit = (btn.get_attribute('type') or '').lower() == 'submit'
                    # ⚠️ 嚴格過濾危險按鈕（退選、取消、刪除、登出、問卷、滿意度等）
                    DANGER_KEYWORDS = ['退選', '取消', '刪除', 'Unenroll', 'Cancel', 'Delete', '登出', 'Logout', '搜尋', 'Search',
                                       '問卷', '滿意度', '填寫', '回答', 'feedback', 'survey', 'questionnaire']
                    if any(dk in text for dk in DANGER_KEYWORDS):
                        continue
                    # 同時過濾 href 指向 feedback 模組的連結
                    if href and 'mod/feedback' in href:
                        continue

                    if href and 'mod/scorm/player.php' in href:
                        print(f'  ▶️ 進入 SCORM player (URL): {href}')
                        driver.get(href)
                    elif any(k in text for k in ['進入', '開始', '繼續', 'Start', 'Enter', 'Launch', '閱讀', '上課', '進入教室', '進入課程', '閱讀教材', '確定']):
                        print(f'  ▶️ 點擊 SCORM 進入按鈕: {text[:40]}')
                        driver.execute_script("arguments[0].click();", btn)
                    elif is_submit and any(k in text for k in ['scorm', 'player', 'lesson', 'class', '課程', '教材', '單元']):
                        print(f'  ▶️ 點擊 SCORM 提交按鈕: {text[:40]}')
                        driver.execute_script("arguments[0].click();", btn)
                    else:
                        continue

                    for _ in range(20):
                        msgs2 = dismiss_alerts(driver)
                        if has_multi_window_alert(msgs2):
                            # 不立刻放棄，先檢查 player 是否仍可用
                            time.sleep(1)
                            dismiss_alerts(driver)
                            if current_is_player():
                                return True
                            return False  # 被踢回才放棄
                        # 若開啟了新分頁或新視窗，自動切換至最新視窗
                        if len(driver.window_handles) > 1:
                            driver.switch_to.window(driver.window_handles[-1])
                            _auto_hide_taipei_popups_if_needed(driver)
                        pause_and_mute_media(driver)
                        if current_is_player():
                            return True
                        time.sleep(0.25)
                except Exception:
                    pass

        return current_is_player()

    has_recovered_multi_window_lock = False
    for attempt in range(1, 4):
        if current_is_player():
            pause_and_mute_media(driver)
            return driver.current_url

        if enter_from_scorm_view():
            pause_and_mute_media(driver)
            return driver.current_url

        scorm_url, label = find_scorm_link()
        if not scorm_url:
            print('  找不到 SCORM 連結，跳過')
            return None

        print(f'  ▶️ 進入課程連結: {(label or scorm_url)[:40]}')
        try:
            # Use same-window navigation. Taipei E-da blocks multiple course windows.
            driver.get(scorm_url)
            time.sleep(2)
        except Exception as e:
            print(f'  ⚠️ 進入 SCORM 連結失敗: {e}')
            return None

        msgs = dismiss_alerts(driver)
        if has_multi_window_alert(msgs):
            # 警告出現但不立刻放棄：dismiss 後檢查是否仍在 player
            print('  ⚠️ 臺北E大多重視窗警告（可能是舊 session 殘留），dismiss 後繼續檢查...')
            time.sleep(1.5)
            dismiss_alerts(driver)
            if current_is_player():
                print('  ✅ 雖有多重視窗警告，但 player 頁面仍可使用，繼續上課')
                pause_and_mute_media(driver)
                return driver.current_url
            # 被踢回課程頁代表伺服器端 SCORM 鎖定尚未釋放；僅重載頁面無效。
            if not has_recovered_multi_window_lock:
                has_recovered_multi_window_lock = True
                print('  🔄 多重視窗警告後被踢回，執行一次 Session 回復後重試...')
                if recover_from_multi_window_lock(driver, wait, course_url, config):
                    continue
            print('  ⚠️ 多重視窗鎖定未能自動解除，暫停本課程並繼續下一門。')
            return None

        if enter_from_scorm_view():
            pause_and_mute_media(driver)
            return driver.current_url

        print(f'  ⚠️ 尚未進入播放器，重試 {attempt}/3，目前: {driver.current_url}')
        driver.get(course_url)
        time.sleep(2)
        dismiss_alerts(driver)

    return None

def get_chapters(driver):
    result = []
    try:
        els = driver.find_elements(By.CSS_SELECTOR, '[data-scoid]')
        for idx, el in enumerate(els, start=1):
            try:
                scoid = el.get_attribute('data-scoid') or ''
                if not scoid:
                    continue
                name = (el.text or el.get_attribute('title') or el.get_attribute('aria-label') or '').strip()
                if not name:
                    try:
                        name = driver.execute_script(
                            """
                            const el = arguments[0];
                            const parts = [];
                            let cur = el;
                            for (let i = 0; cur && i < 3; i++, cur = cur.parentElement) {
                              const txt = (cur.innerText || cur.textContent || '').trim();
                              if (txt) parts.push(txt);
                            }
                            return parts[0] || '';
                            """,
                            el,
                        ) or ''
                    except Exception:
                        name = ''
                if not name:
                    name = f'單元 {idx} ({scoid})'

                icon_class = ''
                try:
                    icons = el.find_elements(By.CSS_SELECTOR, 'i.icon, i, .fa, [class*="check"]')
                    icon_class = ' '.join((ic.get_attribute('class') or '') for ic in icons)
                except Exception:
                    pass

                cls = el.get_attribute('class') or ''
                done = any(k in (icon_class + ' ' + cls) for k in [
                    'fa-check-square-o',
                    'fa-check',
                    'completed',
                    'complete',
                    'finish',
                    'done',
                ])
                result.append({'scoid': scoid, 'name': name, 'done': done, 'icon': icon_class})
            except Exception:
                pass
    except Exception:
        pass
    return result

def click_chapter_by_scoid(driver, scoid):
    try:
        el = driver.find_element(By.CSS_SELECTOR, f'[data-scoid="{scoid}"]')
        driver.execute_script(
            """
            const el = arguments[0];
            const clickable =
              el.querySelector('button, a, [role="button"]') ||
              el.closest('button, a, [role="button"], li, div') ||
              el;
            clickable.scrollIntoView({block:'center'});
            clickable.click();
            """,
            el,
        )
        return True
    except Exception:
        try:
            url = driver.current_url
            if 'scoid=' in url:
                url = re.sub(r'scoid=\d+', f'scoid={scoid}', url)
            elif '#' in url:
                url = url.replace('#', f'&scoid={scoid}#')
            else:
                joiner = '&' if '?' in url else '?'
                url = f'{url}{joiner}scoid={scoid}'
            driver.get(url)
            return True
        except Exception:
            return False

def is_chapter_done(driver, scoid):
    try:
        el = driver.find_element(By.CSS_SELECTOR, f'[data-scoid="{scoid}"]')
        icons = el.find_elements(By.CSS_SELECTOR, 'i.icon')
        icon_class = icons[0].get_attribute('class') if icons else ''
        return 'fa-check-square-o' in icon_class
    except Exception:
        return False

def do_scorm_course(driver, wait, course, config=None, should_continue=None, modules=None):
    config = config or {}
    should_continue = should_continue or (lambda: True)

    name = course['name']
    href = course['href']
    try:
        cert_hrs = float(course.get('cert_hrs') or 0)
    except Exception:
        cert_hrs = 0

    target_percentage = float(config.get('target_percentage', 1.0) or 1.0)
    req_minutes = (modules.get('req_minutes') if modules else None) or course.get('req_minutes')
    is_package = '套裝' in name or '組合' in name or cert_hrs >= 2.0

    if req_minutes:
        target_sec = int(float(req_minutes) * 60 * target_percentage)
        print(f'  🎯 依課程特定要求設定目標時數：{int(req_minutes)} 分鐘')
    elif is_package:
        target_sec = int(cert_hrs * 3600 * target_percentage)
    else:
        criteria_sec = int(cert_hrs * 3600 * 0.5)
        target_sec = int(criteria_sec * target_percentage)

    already_sec = parse_study_time(course.get('study', ''))
    remain_sec = max(target_sec - already_sec, 0)

    print(f'課程: {name[:60]}')
    if target_sec > 0:
        print(f'目標: {target_sec//60} 分鐘 | 已有: {already_sec//60} 分 {already_sec%60} 秒 | 還需: {remain_sec//60} 分 {remain_sec%60} 秒')
        if remain_sec <= 0:
            print(f'  ✅ 上課時數已達標 (已有 {already_sec//60} 分鐘 >= 目標 {target_sec//60} 分鐘)，無需進入 SCORM 播放器')
            return True
    else:
        print('目標: 無認證時數要求，僅檢查章節狀態')

    scorm_view_url = get_scorm_player_url(driver, wait, href, config=config)
    if not scorm_view_url:
        print('  找不到 SCORM 連結，跳過')
        return False

    print(f'  Player URL: {driver.current_url}')
    pause_and_mute_media(driver)

    chapters = get_chapters(driver)
    if not chapters:
        print('  ⚠️ 找不到章節，等待後重試...')
        time.sleep(10)
        chapters = get_chapters(driver)

    if not chapters:
        print('  ⚠️ SCORM 頁面沒有讀到任何章節，避免空迴圈補時間，跳過此課程')
        return False

    scoid_order = [ch['scoid'] for ch in chapters]
    start_time = time.time()
    round_num = 0

    while should_continue():
        _auto_hide_taipei_popups_if_needed(driver)
        round_num += 1
        elapsed_sec = time.time() - start_time
        chapters = get_chapters(driver)
        ch_map = {ch['scoid']: ch for ch in chapters}
        pending = [s for s in scoid_order if not ch_map.get(s, {}).get('done', False)]
        all_done = len(pending) == 0
        time_ok = elapsed_sec >= remain_sec

        if remain_sec > 0 and elapsed_sec >= remain_sec:
            print(f'  ✅ 研習時數已 100% 達標 (已有: {sec_to_hms(already_sec + elapsed_sec)} / 目標: {sec_to_hms(target_sec)})，結束課程研習！')
            break

        if all_done and (time_ok or remain_sec == 0):
            print(f'  ✅ 所有章節均已完成，已補跑 {elapsed_sec/60:.1f} 分鐘')
            break

        to_visit = pending if pending else list(scoid_order)

        for scoid in to_visit:
            if not should_continue():
                print('  使用者已停止臺北E大流程')
                return False

            elapsed_sec = time.time() - start_time
            if remain_sec > 0 and elapsed_sec >= remain_sec:
                print(f'  ✅ 研習時數已 100% 達標 (已有: {sec_to_hms(already_sec + elapsed_sec)} / 目標: {sec_to_hms(target_sec)})，跳出學習！')
                break

            elapsed_sec = time.time() - start_time
            print(f'  研習進度：{sec_to_hms(already_sec + elapsed_sec)} / {sec_to_hms(target_sec)} {draw_bar(already_sec + elapsed_sec, target_sec)}')
            ch_info = ch_map.get(scoid, {'name': scoid, 'done': False})
            print(f'  進入單元：{ch_info["name"][:40]}...')

            if not click_chapter_by_scoid(driver, scoid):
                print('      ⚠️ 點擊失敗，跳過')
                continue
            time.sleep(1)
            dismiss_alerts(driver)
            pause_and_mute_media(driver)

            st = time.time()
            while should_continue() and time.time() - st < RESIDENCE_TIME:
                time.sleep(1)
                pause_and_mute_media(driver)
                deep_commit(driver)

            if is_chapter_done(driver, scoid):
                print('      ✅ 單元已完成')

        if time.time() - start_time > 7200:
            print('  ⚠️ 單一課程研習已達 2 小時，先切換下一門課')
            break

    if not should_continue():
        return False

    print('  點擊離開按鈕...')
    try:
        leave = wait.until(EC.element_to_be_clickable(
            (By.XPATH, '//*[contains(text(),"離開時請點選此按鈕")]')
        ))
        driver.execute_script("arguments[0].click();", leave)
        time.sleep(3)
        dismiss_alerts(driver)
        print(f'  離開後: {driver.current_url}')
    except Exception as e:
        print(f'  離開按鈕: {e}')

    return True

# ── 主程式 ────────────────────────────────────────────

# 載入 config（AI keys）


def _is_pid_alive(pid):
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def _acquire_taipei_run_lock():
    lock_path = os.path.join(os.path.dirname(__file__), ".taipei_eda_course.lock")
    try:
        if os.path.exists(lock_path):
            try:
                with open(lock_path, "r", encoding="utf-8") as f:
                    old_pid = (f.read() or "").strip()
            except Exception:
                old_pid = ""
            if old_pid and _is_pid_alive(old_pid):
                print("臺北E大流程已在執行中，請先停止目前流程或關閉舊視窗。")
                return None
            try:
                os.remove(lock_path)
            except Exception:
                pass
        with open(lock_path, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return lock_path
    except Exception as e:
        print(f"臺北E大流程鎖建立失敗，仍繼續執行: {e}")
        return ""

def _release_taipei_run_lock(lock_path):
    if not lock_path:
        return
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception:
        pass



def run_taipei_eda(config_override=None, should_continue=None, log_callback=None, quiz_interactive_callback=None):
    """Run the Taipei E-learning workflow from the GUI/back-end dispatcher."""
    should_continue = should_continue or (lambda: True)
    config = load_config()

    # ── 日誌路由：只建立一層 _UILog，避免 _Tee 疊套造成重複訊息 ──────────────
    original_stdout = sys.stdout
    if log_callback:
        class _UILog(io.TextIOBase):
            def write(self, s):
                text = str(s)
                if text.strip():
                    for line in text.rstrip().splitlines():
                        log_callback(line)
                        # 同步寫入 log 檔（單一管道）
                        try:
                            _logfile.write(line + "\n")
                            _logfile.flush()
                        except Exception:
                            pass
                return len(text)

            def flush(self):
                pass

        # 只重導向一次 stdout，不再包進 _Tee（避免疊套）
        sys.stdout = _UILog()

    driver = None
    lock_path = _acquire_taipei_run_lock()
    if lock_path is None:
        return False
    try:
        if config_override:
            config.update(config_override)

        username = config.get('account') or config.get('username') or ''
        password = config.get('password') or ''
        if not username or not password:
            print('臺北E大登入失敗：缺少帳號或密碼')
            return False

        headless_mode = config.get('headless', False)
        opts = Options()
        opts.add_argument('--window-size=1400,900')
        opts.add_argument('--disable-gpu')
        opts.add_argument('--mute-audio')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        opts.add_argument('--disable-extensions')
        opts.add_argument('--disable-background-timer-throttling')
        opts.add_argument('--disable-backgrounding-occluded-windows')
        opts.add_argument('--disable-renderer-backgrounding')
        # 防禦臺北E大資安升級引發的混合內容(HTTPS/HTTP)或不安全警告阻擋
        opts.add_argument('--allow-running-insecure-content')
        opts.add_argument('--ignore-certificate-errors')
        opts.add_argument('--allow-insecure-localhost')

        # ── Chrome Driver 路徑：優先使用 app.py 下載的 chromedriver ─────────
        try:
            from app import download_best_chromedriver
            from selenium.webdriver.chrome.service import Service as ChromeService
            _driver_path = os.path.abspath(download_best_chromedriver())
            print(f'  🔧 使用 chromedriver: {_driver_path}')
            _service = ChromeService(_driver_path)
            if sys.platform == 'win32':
                import subprocess
                _service.creation_flags = subprocess.CREATE_NO_WINDOW
            driver = webdriver.Chrome(service=_service, options=opts)
        except Exception as _e:
            print(f'  ⚠️ 無法取得指定 chromedriver，嘗試系統 PATH: {_e}')
            driver = webdriver.Chrome(options=opts)

        global _ACTIVE_DRIVER
        with _DRIVER_LOCK:
            _ACTIVE_DRIVER = driver
        driver.set_window_size(1400, 900)

        global _TAIPEI_IS_HIDDEN
        _TAIPEI_IS_HIDDEN = bool(headless_mode)
        if headless_mode and sys.platform == 'win32':
            set_driver_window_visibility(driver, False)
        wait = WebDriverWait(driver, 20)

        print('=== 登入 ===')
        if not do_login(driver, wait, username=username, password=password):
            print('登入失敗')
            return False

        # 建立 ap1 session
        driver.get('https://elearning.taipei/mpage/sso_moodle?redirectPage=courserecord')
        time.sleep(4)

        print('\n=== 掃描課程清單 ===')
        courses = get_course_list(driver, wait)
        if courses is None:
            print('❌ 無法確認臺北E大課程清單，已停止本次流程；請確認登入狀態後再試。')
            return False
        incomplete = build_taipei_work_queue(driver, courses)

        print(f'  課程總數: {len(courses)} 筆，待處理: {len(incomplete)} 筆')
        if not incomplete:
            print('\n沒有待處理課程！')
            return True

        print(f'\n共 {len(incomplete)} 門待處理課程，開始依序處理...')

        stopped = False
        for course in incomplete:
            if not should_continue():
                print('使用者已停止臺北E大流程')
                stopped = True
                break

            print(f'\n{"="*60}')
            print(f'處理: {course["name"]}')

            modules = course.pop('_modules', None) or get_course_modules(driver, course['href'])
            course_id = modules.get('course_id')
            if not course_id:
                m = re.search(r'id=(\d+)', course['href'] or '')
                if m:
                    course_id = int(m.group(1))

            req_minutes = modules.get('req_minutes')
            req_score = modules.get('req_score', 60.0)

            study_needed = is_study_incomplete(course, req_minutes=req_minutes)
            if study_needed:
                scorm_ok = do_scorm_course(driver, wait, course, config=config, should_continue=should_continue, modules=modules)
                if not scorm_ok:
                    print('  ⚠️ SCORM 上課失敗，跳過測驗/問卷')
                    continue
            else:
                print('  ✅ 上課時數已達標，跳過上課，檢查測驗/問卷')

            skip_exam_for_session = bool(config.get('skip_exam_for_session', False))
            quiz_url = modules.get('quiz_url')
            quiz_passed = is_quiz_passed(course, req_score=req_score)

            if quiz_url and course_id and not quiz_passed and skip_exam_for_session:
                print('  ⚠️ 本次已選擇跳過測驗；時數已達標，改為嘗試填寫問卷。')
            elif quiz_url and course_id and not quiz_passed:
                print(f'\n  📝 測驗 (course_id={course_id}，及格標準: {int(req_score)} 分)')
                score_text, is_100 = do_quiz_with_bank(
                    driver, wait,
                    course_id=course_id,
                    quiz_view_url=quiz_url,
                    config=config,
                    course_name=course.get('name', ''),
                    username=config.get('name', '') or config.get('account', ''),
                    quiz_interactive_callback=quiz_interactive_callback or config.get('quiz_interactive_callback'),
                    min_pass_score=req_score,
                )
                print(f'  測驗結果: {score_text} | 達標: {is_100 or is_quiz_passed(course, req_score=req_score)}')
            elif quiz_url and course_id:
                print('  ✅ 測驗已完成/通過，跳過')
            elif quiz_url and not course_id:
                print('  ⚠️ 找到測驗但無法取得 course_id，跳過')
            else:
                print('  無測驗')

            fb_url = modules.get('fb_url')
            quest = _clean_status(course.get('quest'))
            if is_questionnaire_pending(course):
                if not fb_url:
                    print('  重新掃描 feedback URL...')
                    modules2 = get_course_modules(driver, course['href'])
                    fb_url = modules2.get('fb_url')

                if fb_url:
                    print('\n  📋 問卷')
                    do_feedback(driver, wait, feedback_view_url=fb_url)
                else:
                    print('  ⚠️ 問卷狀態為填寫，但找不到問卷入口')
            elif quest == '已完成':
                print('  ✅ 問卷已完成，跳過')
            else:
                print('  無問卷')
            time.sleep(3)

        print('\n=== 最終課程狀態 ===')
        courses_final = get_course_list(driver, wait)
        if courses_final is None:
            print('⚠️ 無法重新讀取最終課程清單，不能宣告全部完成。')
            return False
        final_incomplete = pending_courses_sorted(courses_final)
        print(f'  課程總數: {len(courses_final)} 筆，待處理: {len(final_incomplete)} 筆')
        if final_incomplete:
            preview = '、'.join(c["name"][:18] for c in final_incomplete[:5])
            suffix = '...' if len(final_incomplete) > 5 else ''
            print(f'  尚未完成: {preview}{suffix}')

        print('\n完成！')
        return not stopped
    finally:
        force_close_active_driver()
        _release_taipei_run_lock(lock_path)
        if log_callback:
            sys.stdout = original_stdout


if __name__ == "__main__":
    run_taipei_eda()
