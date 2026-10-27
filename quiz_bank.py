"""
臺北e大 測驗自動作答模組
- 查 GAS 題庫 → 命中直接答 → 送出
- 未知題：呼叫 AI 分析答案 → 填答 → 送出 → 存 GAS
- AI 失敗或填答不完整：停止交卷；已確認未及格才重考覆核
"""

import re, json, time, requests, difflib, threading, sys, logging
from utils.security import validate_ai_base_url
from utils.helpers import match_radio_option_index
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoAlertPresentException

GAS_URL = 'https://script.google.com/macros/s/AKfycbzYUNM--zLlS8El6YR6lIiKerBIz1M6rL2gM8nTGicmEjfh_1TNiBo12YcVsb37J7Cl/exec'


# ── 工具 ─────────────────────────────────────────────

def _safe_print(text):
    """安全輸出字串，防範 Windows CP950/Big5 控制台拋出 UnicodeEncodeError。

    臺北E大流程會把全域 sys.stdout 換成自己的 UI 管道；其他執行緒（e等公務園）呼叫時改走
    logging，由 ThreadBoundUILogHandler 送到正確的平臺面板，避免訊息跑錯面板或遺失。
    """
    owner = getattr(sys.stdout, "owner_thread", None)
    if owner != threading.get_ident() and (owner is not None or sys.stdout is None):
        logging.getLogger("LearningPilot").info(str(text).strip())
        return
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "cp950"
        try:
            safe_text = str(text).encode(encoding, errors="replace").decode(encoding)
            print(safe_text)
        except Exception:
            pass

def _normalize(text):

    """去除空白標點，只留中英數，用於模糊比對 key"""
    return re.sub(r'[^\w\u4e00-\u9fff]', '', text or '').strip()

def _clean_question_text(text):
    """清掉 Moodle 題塊雜訊，只保留真正題幹。"""
    text = re.sub(r'\s+', ' ', text or '').strip()
    text = re.sub(r'^試題文字\s*', '', text)
    text = re.sub(r'\s*試題\s*\d+\s*$', '', text)
    text = re.sub(r'\s*試題\s*\d+\s*回答\s*.*$', '', text)
    text = re.sub(r'\s*回答\s*1[\.、]?\s*.*$', '', text)
    text = re.sub(r'\s*清除我的選擇\s*$', '', text)
    return text.strip()

def _dismiss_alerts(driver):
    for _ in range(5):
        try:
            driver.switch_to.alert.accept(); time.sleep(0.4)
        except NoAlertPresentException:
            break

def _click_js(driver, el):
    driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", el)


# ── GAS 題庫存取 ──────────────────────────────────────

def _is_cloud_sync_enabled(config=None) -> bool:
    if isinstance(config, dict):
        if "cloud_sync_enabled" in config:
            return bool(config["cloud_sync_enabled"])
        settings = config.get("settings")
        if isinstance(settings, dict) and "cloud_sync_enabled" in settings:
            return bool(settings["cloud_sync_enabled"])
    return True


def gas_fetch_bank(course_id, config=None):
    """
    從 GAS 取得該課程題庫。
    回傳 dict: {normalize(q_text): val_str}
    支援兩種回傳格式：
      - 新格式：{status:'ok', data:[...]}
      - 舊/未支援：[] 或其他 list
    """
    if not _is_cloud_sync_enabled(config):
        print(f'  [題庫] 雲端共用題庫同步已停用，僅使用本機題庫與 AI（course_id={course_id}）')
        return {}
    print(f'  [題庫] 正在從 GAS 載入 course_id={course_id}')
    try:
        r = requests.get(GAS_URL,
                         params={'action': 'taipei_quiz_get', 'course_id': str(course_id)},
                         timeout=10)
        resp = r.json()
        # 支援兩種格式
        if isinstance(resp, dict):
            data = resp.get('data', [])
        elif isinstance(resp, list):
            data = resp  # 舊格式或 taipei_eda_quiz sheet 尚未建立
        else:
            data = []
        bank = {}
        for row in data:
            if not isinstance(row, dict): continue
            key = _normalize(row.get('q_text', ''))
            if key:
                raw = str(row.get('val', ''))
                values = [v.strip() for v in raw.split(',') if v.strip()]
                texts = [row.get('opt' + v) or v for v in values]
                if texts:
                    bank[key] = texts if len(texts) > 1 else texts[0]
        if bank:
            print(f'  [題庫] 從 GAS 載入 {len(bank)} 題（course_id={course_id}）')
        else:
            print(f'  [題庫] GAS 目前沒有此課程題庫（course_id={course_id}），需 AI 或人工補答')
        return bank
    except Exception as e:
        print(f'  [題庫] GAS 載入失敗: {e}')
        return {}

def _taipei_question_payload(course_id, q):
    opts = q.get('options', {}) or {}
    return {
        'course_id': str(course_id),
        'q_text': q.get('qtext', ''),
        'opt0': list(opts.values())[0] if len(opts) > 0 else '',
        'opt1': list(opts.values())[1] if len(opts) > 1 else '',
        'opt2': list(opts.values())[2] if len(opts) > 2 else '',
        'opt3': list(opts.values())[3] if len(opts) > 3 else '',
    }

def gas_report_missing_questions(course_id, questions, course_name='', username='', config=None):
    """Report Taipei E-da missing questions to GAS/TG without blocking the quiz."""
    if not questions or not _is_cloud_sync_enabled(config):
        return

    seen = set()
    missing = []
    for q in questions:
        key = _normalize(q.get('qtext', ''))
        if not key or key in seen:
            continue
        seen.add(key)
        missing.append(_taipei_question_payload(course_id, q))

    if not missing:
        return

    gas_url = (config or {}).get('gas_url') or GAS_URL
    payload = {
        'action': 'taipei_quiz_missing',
        'course_id': str(course_id),
        'course': course_name or '未知課程',
        'username': username or '匿名',
        'missing': missing,
    }

    def _post():
        try:
            r = requests.post(gas_url, json=payload, timeout=20)
            result = r.json()
            if result.get('status') == 'ok':
                print(f'  [缺題] 已回報 GAS/TG（{len(missing)} 題，GAS新增 {result.get("added", 0)} 題）')
            else:
                print(f'  [缺題] GAS 回傳異常: {result}')
        except Exception as e:
            print(f'  [缺題] 回報失敗: {e}')

    threading.Thread(target=_post, daemon=True).start()
    print(f'  [缺題] 回報已背景送出（{len(missing)} 題）')

def gas_save_questions(course_id, questions_with_answers, course_name='', username='', config=None):
    """
    把新答案存回 GAS/GitHub 共用題庫。
    questions_with_answers: [{q_text, val, opt0..opt3}, ...]
    """
    if not questions_with_answers or not _is_cloud_sync_enabled(config):
        return False
    payload = {
        'action': 'taipei_quiz_save',
        'course_id': str(course_id),
        'course': course_name,
        'username': username,
        'questions': [dict(course_id=course_id, **q) for q in questions_with_answers]
    }
    try:
        r = requests.post((config or {}).get('gas_url') or GAS_URL, json=payload, timeout=15)
        result = r.json()
        if result.get('status') == 'ok':
            print(f'  [題庫] 已同步共用題庫: added={result.get("added")}, updated={result.get("updated")}')
            return True
        else:
            print(f'  [題庫] GAS 回傳異常: {result}')
    except Exception as e:
        print(f'  [題庫] GAS 存入失敗: {e}')
    return False

def lookup_bank(bank, q_text, threshold=0.75):
    """在 bank 裡模糊查找 q_text，回傳 val str 或 None"""
    key = _normalize(q_text)
    if key in bank:
        return bank[key]
    matches = difflib.get_close_matches(key, bank.keys(), n=1, cutoff=threshold)
    if matches:
        print(f'  [題庫] fuzzy: {matches[0][:20]}...')
        return bank[matches[0]]
    return None


# ── AI 分析答案 ──────────────────────────────────────

def save_ai_answers_to_sqlite(questions_data: list, answers_by_idx: dict):
    """將 AI 作答結果標準化儲存至本機 SQLite questions.db，達成問過一次永久記住。"""
    try:
        from utils.app_paths import user_data_path
        from utils.config_io import get_db_connection
        db_path = user_data_path("questions.db")
        conn = get_db_connection(db_path)
        try:
            for q in questions_data:
                idx_str = str(q.get("index", ""))
                ans_code = answers_by_idx.get(idx_str) or answers_by_idx.get(q.get("name", ""))
                if not ans_code:
                    continue
                q_text = q.get("q_text", "").strip()
                opts = q.get("options", [])
                opt_map = {opt["label"].upper(): opt["text"].strip() for opt in opts if "label" in opt and "text" in opt}

                ans_code_str = str(ans_code).strip().upper()
                codes = [code.strip() for code in ans_code_str.split(',') if code.strip()]
                texts = [opt_map[code] for code in codes if code in opt_map]
                resolved_ans = json.dumps(texts, ensure_ascii=False) if len(texts) > 1 else opt_map.get(ans_code_str, str(ans_code).strip())

                opt_a = opt_map.get("A", "")
                opt_b = opt_map.get("B", "")
                opt_c = opt_map.get("C", "")
                opt_d = opt_map.get("D", "")

                conn.execute(
                    "INSERT OR REPLACE INTO questions (question, option_a, option_b, option_c, option_d, answer) VALUES (?, ?, ?, ?, ?, ?)",
                    (q_text, opt_a, opt_b, opt_c, opt_d, resolved_ans)
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"  [題庫] 存入本機 SQLite 異常: {e}")


AI_BATCH_TIMEOUT = 45                 # 單次請求逾時秒數（整卷 10 題，尖峰時段 25 秒常不夠）
AI_RETRY_DELAYS = (5, 15)             # 暫時性錯誤的重試間隔（秒）
AI_FALLBACK_MODELS = {"Gemini": "gemini-3.5-flash"}  # 主模型過載時改用的備援模型
_TRANSIENT_HTTP = {500, 502, 503, 504}


class _AIRateLimited(Exception):
    pass


def _is_transient_ai_error(exc):
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError, _AIRateLimited)):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        return getattr(exc.response, "status_code", None) in _TRANSIENT_HTTP
    return False


def _describe_ai_error(exc):
    if isinstance(exc, requests.exceptions.HTTPError):
        code = getattr(exc.response, "status_code", None)
        if code == 429:
            return "Google API 速率受限 (429 Resource Exhausted)，已自動防護"
        if code == 401:
            return "API Key 無效或授權失敗 (401 Unauthorized)"
        if code == 503:
            return "API 呼叫失敗 (HTTP 503 模型過載)"
        return f"API 呼叫失敗 (HTTP {code})"
    if isinstance(exc, requests.exceptions.Timeout):
        return f"API 回應逾時（{AI_BATCH_TIMEOUT} 秒）"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "無法連線至 AI 服務"
    if isinstance(exc, _AIRateLimited):
        return str(exc)
    return f"AI 解析過程異常: {exc}"


def ai_batch_solve_quiz(course_name: str, questions_data: list, config: dict) -> dict:
    """
    呼叫 AI API 批次解析整份考卷題目（支援單選、多選、是非題），回傳結構化答案與對應之內部 val。
    """
    if not questions_data:
        return {"success": False, "error": "無題目資料", "answers": {}, "parsed_answers": {}}

    provider = config.get('ai_provider', 'Gemini')
    ai_keys  = config.get('ai_keys', {}) or {}
    api_key  = (ai_keys.get(provider) or config.get('ai_api_key', '')).strip()
    if not api_key:
        return {"success": False, "error": "尚未設定 API Key，請至系統設定填入", "answers": {}, "parsed_answers": {}}

    try:
        base_url = validate_ai_base_url(
            provider,
            config.get('ai_base_url', 'https://generativelanguage.googleapis.com/v1beta/openai'),
        )
    except ValueError as exc:
        return {"success": False, "error": f"API 網址遭安全規則拒絕：{exc}", "answers": {}, "parsed_answers": {}}

    model = config.get('ai_model', 'gemini-3.1-flash-lite')
    if provider == "Gemini" and ("gemini-2.0" in model or "gemini-1.5" in model or "gemini-2.5" in model):
        model = "gemini-3.1-flash-lite"


    from utils.security import global_ai_rate_limiter, mask_api_key
    masked_key = mask_api_key(api_key)


    prompt_lines = [
        f"請針對以下《{course_name}》測驗題目進行回答。",
        "請務必遵守以下作答規範：",
        "1. 一律以嚴格標準的 JSON 格式回傳，最外層為包含 'answers' 物件的字典。",
        "2. 'answers' 字典的 key 為題號字串（如 \"1\", \"2\", \"3\"...），value 為正確選項之代號字串（如 \"A\", \"B\", \"C\", \"D\"；是非題若是/對回傳 \"A\" 或對應代號；若為多選題請以逗號分隔如 \"A,C\"）。",
        '3. 回傳範例: {"answers": {"1": "C", "2": "C", "3": "D", "4": "A,C"}}',
        "4. 絕對不要輸出任何 Markdown 代碼塊（如 ```json）、不要輸出解釋說明，只輸出純 JSON。\n",
        "【測驗題目清單】"
    ]
    for q in questions_data:
        idx = q.get("index", 1)
        q_type = q.get("type", "單選")
        q_text = q.get("q_text", "").strip()
        opts = q.get("options", [])
        opts_str = "\n".join(f"   {opt.get('label', '')}. {opt.get('text', '')}" for opt in opts)
        prompt_lines.append(f"{idx}. [{q_type}] {q_text}\n{opts_str}\n")

    prompt = "\n".join(prompt_lines)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    if provider == "Claude":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a professional Taiwan government civil service examination and compliance expert. You output answers in strict JSON without any surrounding text."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0
    }

    def _request_once(use_model):
        if not global_ai_rate_limiter.acquire(timeout=15.0):
            raise _AIRateLimited("超出每分鐘請求速率上限（5 RPM），請稍候重試")
        _safe_print(f"  [AI批次] 正在呼叫 {provider} ({use_model}) 端點: {base_url} (Key: {masked_key})")
        # 記錄一次 API 發送嘗試（無論成功、逾時或 429 皆精確計數）
        try:
            from utils.security import global_quota_tracker
            global_quota_tracker.record_usage(1)
        except Exception:
            pass
        if provider == "Claude":
            claude_payload = {
                "model": use_model,
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            }
            resp = requests.post(f"{base_url}/messages", headers=headers, json=claude_payload, timeout=AI_BATCH_TIMEOUT)
            resp.raise_for_status()
            return resp.json()["content"][0]["text"].strip()
        resp = requests.post(f"{base_url}/chat/completions", headers=headers, json={**payload, "model": use_model}, timeout=AI_BATCH_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    # 暫時性錯誤（503 過載、逾時、連線中斷）才重試；401／429 等不重試，避免浪費額度
    plan = [(model, 0)] + [(model, AI_RETRY_DELAYS[0])]
    fallback = AI_FALLBACK_MODELS.get(provider)
    if fallback and fallback != model:
        plan.append((fallback, AI_RETRY_DELAYS[1]))
    else:
        plan.append((model, AI_RETRY_DELAYS[1]))

    try:
        raw_text = None
        last_exc = None
        for attempt_no, (use_model, delay) in enumerate(plan, start=1):
            if delay:
                _safe_print(f"  ⏳ [AI批次] {delay} 秒後重試（第 {attempt_no}/{len(plan)} 次，模型 {use_model}）")
                time.sleep(delay)
            try:
                raw_text = _request_once(use_model)
                break
            except Exception as exc:
                last_exc = exc
                if not _is_transient_ai_error(exc):
                    raise
                _safe_print(f"  ⚠️ [AI批次] 暫時性錯誤：{_describe_ai_error(exc)}")
        if raw_text is None:
            raise last_exc

        # 解析 JSON
        clean_json_str = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
        clean_json_str = re.sub(r"\s*```$", "", clean_json_str).strip()
        parsed_obj = json.loads(clean_json_str)

        if "answers" in parsed_obj and isinstance(parsed_obj["answers"], dict):
            raw_answers = parsed_obj["answers"]
        elif isinstance(parsed_obj, dict):
            raw_answers = parsed_obj
        else:
            raw_answers = {}

        parsed_answers = {}
        answers_by_idx = {}
        for q in questions_data:
            idx_str = str(q.get("index", ""))
            ans_code = raw_answers.get(idx_str) or (raw_answers.get(str(int(idx_str))) if idx_str.isdigit() else None)
            if not ans_code:
                continue

            ans_code_str = ','.join(str(code).strip() for code in ans_code) if isinstance(ans_code, list) else str(ans_code).strip()
            answers_by_idx[idx_str] = ans_code_str

            opts = q.get("options", [])
            label_to_val = {opt["label"].upper(): str(opt["val"]) for opt in opts if "label" in opt and "val" in opt}

            codes = [c.strip().upper() for c in ans_code_str.replace("，", ",").replace("、", ",").replace(" ", ",").split(",") if c.strip()]
            matched_vals = [label_to_val[c] for c in codes if c in label_to_val]

            if (matched_vals and len(matched_vals) == len(codes)
                    and (q.get('is_multiple') or len(matched_vals) == 1)):
                parsed_answers[q["name"]] = matched_vals if len(matched_vals) > 1 else matched_vals[0]

        _safe_print(f"  ✓ [AI批次] 成功解析 {len(answers_by_idx)}/{len(questions_data)} 題候選解答")

        return {
            "success": True,
            "answers": answers_by_idx,
            "parsed_answers": parsed_answers,
            "questions_data": questions_data,
            "raw_text": raw_text,
            "error": None
        }


    except Exception as e:
        err_msg = _describe_ai_error(e)
        transient = _is_transient_ai_error(e)
        if transient:
            err_msg += f"（已重試 {len(plan)} 次仍失敗，Google 服務暫時不穩）"
        _safe_print(f"  ❌ [AI批次] {err_msg}")
        return {"success": False, "error": err_msg, "transient": transient, "answers": {}, "parsed_answers": {}}



def ai_guess_answer(q_text, options, config):
    """
    呼叫 AI API（OpenAI-compatible 或 Claude）分析題目，回傳正確選項的 val str。
    config: {ai_provider, ai_keys:{Provider:key}, ai_base_url, ai_model}
    回傳 val str（'0'~'3'）或 None（失敗）
    """
    provider = config.get('ai_provider', 'Gemini')
    ai_keys  = config.get('ai_keys', {})
    api_key  = ai_keys.get(provider) or config.get('ai_api_key', '')

    if not api_key:
        print('  [AI] 無 API key，跳過')
        return None

    try:
        base_url = validate_ai_base_url(
            provider,
            config.get('ai_base_url', 'https://api.openai.com/v1'),
        )
    except ValueError as exc:
        print(f'  [AI] API 網址遭安全規則拒絕：{exc}')
        return None
    model    = config.get('ai_model', 'gpt-4o-mini')
    if provider == "Gemini" and any(v in model for v in ("gemini-2.0", "gemini-1.5", "gemini-2.5")):
        model = "gemini-3.1-flash-lite"  # 舊版 Gemini 模型已下架（API 回 404）

    # 建立選項文字清單（去掉編號前綴如 "1. "）
    opts_clean = {}
    for val, text in options.items():
        clean = re.sub(r'^\d+\.\s*', '', text).strip()
        opts_clean[val] = clean

    options_str = '\n'.join(f'{val}. {text}' for val, text in sorted(opts_clean.items()))
    prompt = (
        '你是考試作答助手。請從以下選項中選出正確答案，'
        '只回答正確選項的完整文字，不要編號、不要解釋、不要標點。\n\n'
        f'題目：{q_text}\n\n'
        f'選項：\n{options_str}\n\n'
        '正確答案：'
    )

    try:
        if provider == 'Claude':
            resp = requests.post(
                f'{base_url}/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'Content-Type': 'application/json'},
                json={'model': model, 'max_tokens': 150,
                      'messages': [{'role': 'user', 'content': prompt}]},
                timeout=20)
            resp.raise_for_status()
            ai_answer = resp.json()['content'][0]['text'].strip()
        else:
            resp = requests.post(
                f'{base_url}/chat/completions',
                headers={'Authorization': f'Bearer {api_key}',
                         'Content-Type': 'application/json'},
                json={'model': model, 'temperature': 0, 'max_tokens': 150,
                      'messages': [{'role': 'user', 'content': prompt}]},
                timeout=20)
            resp.raise_for_status()
            ai_answer = resp.json()['choices'][0]['message']['content'].strip()

        print(f'  [AI] 回答: {ai_answer!r}')

        # 去掉 AI 回答的編號前綴（如 "1. 是" → "是"）
        ai_clean = re.sub(r'^\d+[\.、\s]+', '', ai_answer).strip()

        # 把 AI 回答文字比對回 val
        ai_norm = _normalize(ai_clean)
        # 精確比對
        for val, text in opts_clean.items():
            if _normalize(text) == ai_norm:
                print(f'  [AI] 命中 val={val}')
                return val
        # fuzzy 比對
        clean_texts = list(opts_clean.values())
        matches = difflib.get_close_matches(ai_clean, clean_texts, n=1, cutoff=0.6)
        if matches:
            for val, text in opts_clean.items():
                if text == matches[0]:
                    print(f'  [AI] fuzzy 命中 val={val}')
                    return val

        print(f'  [AI] 無法比對回選項，回答: {ai_answer!r}')
        return None

    except Exception as e:
        print(f'  [AI] 呼叫失敗: {e}')
        return None


def ai_guess_answer_retry(q_text, options, wrong_val, config):
    """
    AI 重答：已知 wrong_val 是錯的，排除後重新猜。
    回傳 val str 或 None。
    """
    opts_excl = {v: t for v, t in options.items() if v != wrong_val}
    if not opts_excl:
        return None
    return ai_guess_answer(q_text, opts_excl, config)


# ── Moodle 測驗操作 ──────────────────────────────────

def _start_or_resume_quiz(driver, wait, quiz_view_url):
    """進測驗頁，點開始/繼續，回傳 attempt URL"""
    driver.get(quiz_view_url)
    time.sleep(3)
    _dismiss_alerts(driver)

    for xpath in [
        '//button[contains(text(),"繼續")] | //a[contains(text(),"繼續")]',
        '//button[contains(text(),"開始測驗")]',
        '//button[contains(text(),"再測驗一次")] | //a[contains(text(),"再測驗一次")]',
    ]:
        try:
            btn = driver.find_element(By.XPATH, xpath)
            _click_js(driver, btn)
            time.sleep(2)
            _dismiss_alerts(driver)
            print(f'  [測驗] 開始/繼續 → {driver.current_url}')
            return driver.current_url
        except:
            pass
    return None

def _read_questions(driver):
    """保留每個題目區塊，支援單選／複選；不支援題型也不得靜默漏掉。"""
    result = driver.execute_script(r"""
        function clean(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
        return Array.from(document.querySelectorAll('.que, div[id^="question-"]')).map(function(q) {
            var text = q.querySelector('.qtext, .questiontext');
            var radios = Array.from(q.querySelectorAll('input[type=radio]')).filter(r => r.value !== '-1');
            var boxes = Array.from(q.querySelectorAll('input[type=checkbox]'));
            var entry = q.querySelector('input[type=text][name*="answer"], input:not([type])[name*="answer"]');
            var inputs = boxes.length ? boxes : radios;
            var options = {}, controls = {};
            inputs.forEach(function(input, i) {
                var token = boxes.length ? String(i) : input.value;
                var label = document.getElementById(input.id + '_label') ||
                    Array.from(q.querySelectorAll('label')).find(el => el.htmlFor === input.id);
                options[token] = clean(label ? label.textContent : (input.parentElement.textContent || ''));
                controls[token] = {name: input.name, value: input.value};
            });
            // 僅辨識題幹內依序編號的複選簡答，其他文字題維持安全阻擋。
            var numeric = false;
            if (!inputs.length && entry && text) {
                var lines = (text.innerText || text.textContent || '').split(/\n/).map(clean).filter(Boolean);
                var numbered = lines.map(line => line.match(/^(\d)(?:[.．、]\s*|\s*)([^\d].*)$/)).filter(Boolean);
                numeric = numbered.length >= 2 && numbered.every((m, i) => Number(m[1]) === i + 1);
                if (numeric) numbered.forEach(m => { options[m[1]] = m[2]; });
            }
            return {name: boxes.length ? q.id : (inputs[0] ? inputs[0].name : q.id),
                qtext: clean(text ? text.textContent : ''), options: options, controls: controls,
                text_name: numeric ? entry.name : null, numeric_text: numeric,
                is_multiple: boxes.length > 0 || numeric, supported: (inputs.length > 0 || numeric) && !!text};
        });
    """) or []
    for q in result:
        q['qtext'] = _clean_question_text(q.get('qtext', ''))
    return result


def _question_values(q, raw):
    """複選簡答的連續代號轉為選項集合；拒絕重複或不存在的代號。"""
    from utils.quiz_policy import answer_values
    if q.get('numeric_text') and isinstance(raw, str) and re.fullmatch(r'[1-9]+', raw):
        if len(set(raw)) != len(raw):
            return []
        raw = list(raw)
    return answer_values(raw, q['options'], multiple=q.get('is_multiple', False))


def _fill_answers(driver, answers, questions=None):
    """依各題的控制項名稱／值勾選，再讀回驗證；複選先清除舊選取。"""
    from utils.quiz_policy import answer_values
    verified = 0
    for q in questions or []:
        values = _question_values(q, answers.get(q['name']))
        if not values:
            continue
        if q.get('numeric_text'):
            value = ''.join(sorted(values, key=int))
            ok = driver.execute_script(r"""
                var input = Array.from(document.querySelectorAll('input')).find(el => el.name === arguments[0]);
                if (!input || input.disabled || input.readOnly) return false;
                input.value = arguments[1];
                input.dispatchEvent(new Event('input', {bubbles:true}));
                input.dispatchEvent(new Event('change', {bubbles:true}));
                return input.value === arguments[1];
            """, q['text_name'], value)
            verified += ok is True
            continue
        controls = q.get('controls') or {value: {'name': q['name'], 'value': value} for value in q['options']}
        ok = driver.execute_script(r"""
            var controls = arguments[0], expected = arguments[1], multiple = arguments[2];
            var inputs = Array.from(document.querySelectorAll('input[type=radio], input[type=checkbox]'));
            var matched = {};
            for (var token of Object.keys(controls)) {
                var spec = controls[token];
                var input = inputs.find(el => el.name === spec.name && el.value === spec.value);
                if (!input || input.disabled) return false;
                matched[token] = input;
            }
            for (var token of Object.keys(matched)) {
                var want = expected.includes(token), input = matched[token];
                if (input.checked !== want && (multiple || want)) input.click();
            }
            return Object.keys(matched).every(token => matched[token].checked === expected.includes(token));
        """, controls, values, q.get('is_multiple', False))
        if ok is True:
            verified += 1
    return verified


def _submission_counts(driver):
    """比對實際題數、已答題數與導覽列總題數，防止分頁或題型漏讀。"""
    return driver.execute_script(r"""
        var qs = Array.from(document.querySelectorAll('.que, div[id^="question-"]'));
        var answered = qs.filter(q => {
            if (q.querySelector('input[type=radio]:checked, input[type=checkbox]:checked')) return true;
            var entry = q.querySelector('input[type=text][name*="answer"], input:not([type])[name*="answer"]');
            return entry && entry.value.trim().length > 0;
        }).length;
        var nav = Array.from(document.querySelectorAll('.qnbutton'));
        var total = nav.length || qs.length;
        return {total: qs.length, answered: answered, expected_total: total};
    """)




def _submit_quiz(driver, wait):

    """點完成作答 → summary → 全部送出並結束 → modal confirm → review URL"""
    from utils.quiz_policy import can_submit, has_unanswered_warning
    counts = _submission_counts(driver)
    if not can_submit(**counts):
        print('  ⚠️ 題目或填答不完整，保留草稿，不交卷。')
        return None
    # 完成作答
    finish = driver.execute_script("""
        for (var b of document.querySelectorAll('button,input[type=submit]')) {
            if ((b.value||b.textContent||'').trim().indexOf('完成作答') !== -1) return b;
        }
        return null;
    """)
    if not finish:
        print('  [測驗] ✗ 找不到完成作答')
        return None
    _click_js(driver, finish)
    time.sleep(2); _dismiss_alerts(driver)

    body = driver.find_element(By.TAG_NAME, 'body').text
    if has_unanswered_warning(body):
        print('  ⚠️ 交卷摘要仍有未回答題目，保留草稿，不確認送出。')
        return None

    # 全部送出並結束
    confirm_btn = driver.execute_script("""
        for (var b of document.querySelectorAll('button,input[type=submit]')) {
            var t = (b.value||b.textContent||'').trim();
            if (t.indexOf('全部送出並結束') !== -1 || t.indexOf('送出所有答案並結束') !== -1) return b;
        }
        return null;
    """)
    if confirm_btn:
        driver.execute_script("arguments[0].click();", confirm_btn)
        time.sleep(1.5)
        try:
            modal_save = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-action="save"]'))
            )
            if has_unanswered_warning(driver.find_element(By.TAG_NAME, 'body').text):
                print('  ⚠️ 最後確認視窗顯示漏答，停止送出。')
                return None
            driver.execute_script("arguments[0].click();", modal_save)
        except:
            try:
                alert = driver.switch_to.alert
                if has_unanswered_warning(alert.text):
                    alert.dismiss()
                    return None
                alert.accept()
            except Exception:
                pass
        time.sleep(2); _dismiss_alerts(driver)

    print(f'  [測驗] review → {driver.current_url}')
    return driver.current_url if 'review.php' in driver.current_url else None

def _read_correct_from_review(driver):
    """只採用本題正解標記或明確答對；複選必須有完整正解集合。"""
    records = driver.execute_script(r"""
        return Array.from(document.querySelectorAll('.que')).map(function(q) {
            var radios = Array.from(q.querySelectorAll('input[type=radio]')).filter(r => r.value !== '-1');
            var boxes = Array.from(q.querySelectorAll('input[type=checkbox]'));
            var inputs = boxes.length ? boxes : radios;
            var state = q.querySelector('.state');
            var correct = q.classList.contains('correct') || (state && ['答對', '正確'].includes(state.textContent.trim()));
            var vals = [];
            inputs.forEach(function(input, i) {
                var option = input.closest('.r0, .r1, .r2, .r3, .r4, .r5, .r6, .r7');
                if ((correct && input.checked) || (option && option.classList.contains('correct'))) {
                    vals.push(boxes.length ? String(i) : input.value);
                }
            });
            var right = q.querySelector('.rightanswer');
            var entry = q.querySelector('input[type=text][name*="answer"], input:not([type])[name*="answer"]');
            return {name: boxes.length ? q.id : (inputs[0] ? inputs[0].name : ''),
                    values: vals, multiple: boxes.length > 0, verified: !!correct || !boxes.length,
                    text: right ? right.textContent : '', text_id: entry ? q.id : null,
                    text_value: correct && entry ? entry.value : ''};
        });
    """) or []
    questions = {q['name']: q for q in _read_questions(driver)}
    result = {}
    from utils.quiz_policy import answer_values
    for item in records:
        q = questions.get(item.get('text_id') or item['name'])
        if not q:
            continue
        text = re.sub(r'^.*?(?:正確答案(?:為|是)?|正解)\s*[:：]?\s*', '', item.get('text', '')).strip(' \"「」')
        if q.get('numeric_text'):
            values = _question_values(q, text or item.get('text_value'))
            if values:
                result[q['name']] = values
            continue
        values = answer_values(text, q['options'], multiple=item['multiple']) if text else []
        if not values and item.get('verified'):
            values = item['values']
        if values:
            result[item['name']] = values if item['multiple'] else values[0]
    return result


_SCORE_LINE_KEYWORDS = ('分數', '成績', '評分', '得分')


def _get_score_from_review(driver):
    """只讀成績證據，不把課程及格門檻或說明當成實得分數。"""
    from utils.quiz_policy import grade_evidence
    try:
        score, _ = grade_evidence(driver.find_element(By.TAG_NAME, 'body').text)
    except Exception:
        return ''
    return f'審閱頁得分：{score:g} 分' if score is not None else ''


def _review_grade_counts(driver):
    """審閱頁有標示對錯時，回傳 (答對題數, 總題數)；未公布對錯回傳 None。"""
    try:
        counts = driver.execute_script("""
            var qs = document.querySelectorAll('.que');
            var graded = 0, correct = 0;
            qs.forEach(function(q) {
                var state = q.querySelector('.state');
                var text = state ? state.textContent.trim() : '';
                if (q.classList.contains('correct') || text === '答對' || text === '正確') { graded++; correct++; }
                else if (q.classList.contains('incorrect') || q.classList.contains('notanswered') ||
                    text === '答錯' || text === '未回答' || text === '尚未回答') { graded++; }
            });
            return [correct, qs.length, graded];
        """)
        correct, total, graded = (int(x) for x in counts)
    except Exception:
        return None
    if total <= 0 or graded != total:
        return None
    return correct, total


def _extract_score_num(score_text):
    from utils.quiz_policy import extract_score
    return extract_score(score_text)


def _is_100(score_text):
    """判斷成績是否為 100 分（滿分）"""
    val = _extract_score_num(score_text)
    return val is not None and val >= 100.0


def _get_score_from_course_record(driver, course_id, quiz_view_url):
    """審閱頁不提供分數時，回同課程頁讀取明確的測驗分數欄位。"""
    from urllib.parse import urlsplit
    origin = urlsplit(quiz_view_url)
    url = f'{origin.scheme}://{origin.netloc}/elearn/course/view.php?id={int(course_id)}'
    driver.get(url)
    time.sleep(2)
    text = driver.find_element(By.TAG_NAME, 'body').text
    match = re.search(r'測驗分數\s*[：:]\s*(\d+(?:\.\d+)?)', text)
    return f'課程紀錄得分：{match.group(1)} 分' if match else ''


# ── 主函式 ──────────────────────────────────────────


def do_quiz_with_bank(driver, wait, course_id, quiz_view_url, config=None, course_name='', username='', quiz_interactive_callback=None, min_pass_score=60.0, stats=None):
    """共用政策：題庫優先、缺題補答、未及格覆核，完整填答才交卷。"""
    from utils.quiz_policy import MAX_QUIZ_ATTEMPTS, answer_values, can_submit, grade_passed, needs_ai_review
    config = config or {}
    stats = stats if stats is not None else {}
    stats.update(passed=False, score_num=None, score_unknown=False, ai_used=False, blocked=False)
    provider = config.get('ai_provider', 'OpenAI')
    keys = config.get('ai_keys', {}) or {}
    ai_enabled = bool(config.get('ai_auto_solve') and (keys.get(provider) or config.get('ai_api_key')))
    verified = {}
    best_score = ''
    print(f'\n=== 測驗 (course_id={course_id}) ===')
    print('  [測驗] 題庫優先；缺題補答，未及格由 AI 覆核；每次作答最多一批 AI。')
    for attempt in range(1, MAX_QUIZ_ATTEMPTS + 1):
        batch = None
        print(f'  [測驗] 第 {attempt} 次作答')
        if not _start_or_resume_quiz(driver, wait, quiz_view_url):
            stats['blocked'] = True
            break
        questions = _read_questions(driver)
        print(f'  [測驗] 讀到 {len(questions)} 題')
        counts = _submission_counts(driver)
        if not questions or len(questions) != counts['expected_total'] or any(not q.get('supported', True) or not q.get('options') for q in questions):
            print('  ⚠️ 題型或分頁未完整讀取，保留草稿，不交卷。')
            stats['blocked'] = True
            break
        bank = gas_fetch_bank(course_id, config=config)
        answers, review = {}, []
        for index, q in enumerate(questions, 1):
            raw = verified.get(_normalize(q['qtext']))
            if raw is None:
                raw = lookup_bank(bank, q['qtext'])
            values = _question_values(q, raw)
            if values:
                answers[q['name']] = values if q.get('is_multiple') else values[0]
            if needs_ai_review(answers.get(q['name']), attempt - 1) and (ai_enabled or q['name'] not in answers):
                review.append((index, q))
            elif q['name'] in answers:
                print(f'  ✓ [庫] {q["qtext"][:28]}...')
        if review:
            data = [{'index': index, 'name': q['name'], 'q_text': q['qtext'],
                     'type': '多選' if q.get('is_multiple') else '單選', 'is_multiple': q.get('is_multiple', False),
                     'options': [{'label': chr(65 + i), 'text': text, 'val': val} for i, (val, text) in enumerate(q['options'].items())]}
                    for index, q in review]
            # 重考不得沿用剛確認未及格的舊答案冒充 AI 覆核結果。
            for _, q in review:
                answers.pop(q['name'], None)
            cb = quiz_interactive_callback or config.get('quiz_interactive_callback')
            if config.get('interactive_quiz_for_session') and callable(cb):
                result = cb(course_name or f'課程 {course_id}', data)
                if result == 'STOP_ALL':
                    stats['stopped'] = True
                    return 'STOP_ALL', False
                if result == 'SKIP':
                    return 'SKIPPED', False
                if not isinstance(result, dict):
                    result = {}
                for item in data:
                    labels = (result or {}).get(item['index'], [])
                    values = [o['val'] for o in item['options'] if o['label'] in labels]
                    if values:
                        answers[item['name']] = values if item['is_multiple'] else values[0]
            elif ai_enabled:
                stats['ai_used'] = True
                batch = ai_batch_solve_quiz(course_name or f'課程 {course_id}', data, config)
                if batch.get('success'):
                    answers.update(batch.get('parsed_answers', {}))
                else:
                    stats['ai_outage'] = bool(batch.get('transient'))
                    print(f'  ⚠️ AI 未能補答，保留草稿：{batch.get("error", "無有效解答")}')
            else:
                gas_report_missing_questions(course_id, [q for _, q in review], course_name=course_name, username=username, config=config)
        valid = {}
        for q in questions:
            values = _question_values(q, answers.get(q['name']))
            if values:
                valid[q['name']] = values if q.get('is_multiple') else values[0]
        if not can_submit(len(questions), len(valid), expected_total=counts['expected_total']):
            stats['blocked'] = True
            print('  ⚠️ 尚有無有效答案的題目，保留草稿，不猜答或交卷。')
            break
        filled = _fill_answers(driver, valid, questions=questions)
        if not can_submit(len(questions), filled, expected_total=counts['expected_total']):
            stats['blocked'] = True
            print('  ⚠️ 勾選後驗證未通過，保留草稿，不交卷。')
            break
        if not _submit_quiz(driver, wait):
            stats['blocked'] = True
            break
        time.sleep(2)
        correct = _read_correct_from_review(driver)
        score_text = _get_score_from_review(driver)
        counts = _review_grade_counts(driver) if not score_text else None
        if not score_text:
            try:
                score_text = _get_score_from_course_record(driver, course_id, quiz_view_url)
            except Exception:
                pass
        if not score_text and counts:
            score_text = f'審閱頁推算 {counts[0]}/{counts[1]} 題正確'
        score = _extract_score_num(score_text)
        passed = grade_passed(score, min_pass_score)
        stats.update(score_num=score, passed=passed is True, score_unknown=passed is None)
        best_score = score_text or ''
        # 只有逐題正解或整卷滿分可回寫；AI 提議本身不是正解證據。
        if score is not None and score >= 100:
            correct = valid
            if batch and batch.get('success'):
                save_ai_answers_to_sqlite(data, batch.get('answers', {}))
        to_save = []
        for q in questions:
            values = _question_values(q, correct.get(q['name']))
            if not values:
                continue
            texts = [q['options'][value] for value in values]
            verified[_normalize(q['qtext'])] = texts if q.get('is_multiple') else texts[0]
            if len(q['options']) <= 4:
                tokens = list(q['options'])
                record = {'q_text': q['qtext'], 'val': ','.join(str(tokens.index(value)) for value in values)}
                record.update({f'opt{i}': q['options'][tokens[i]] if i < len(tokens) else '' for i in range(4)})
                to_save.append(record)
        if to_save:
            if gas_save_questions(course_id, to_save, course_name=course_name, username=username, config=config) is True:
                print(f'  [題庫] 本次成功同步共用題庫 {len(to_save)} 題')
            else:
                print('  [題庫] 本次共用同步未確認成功，不影響已取得的測驗結果。')
        if passed is True:
            print(f'  🎉 測驗達標通過！【{score_text}】（門檻: {min_pass_score:g} 分）')
            return score_text, score >= 100
        if passed is None:
            print('  ⚠️ 成績無法判讀，停止重考，請至平臺確認成績。')
            break
        print(f'  [測驗] 得分 {score:g}，門檻 {min_pass_score:g}；未達標。')
    return best_score, False



def do_feedback(driver, wait, feedback_view_url):
    """填問卷：radio 選最大值，textarea 填預設文字，多重搜尋並送出"""
    print(f'\n=== 問卷 ===')
    driver.get(feedback_view_url)
    time.sleep(3)
    _dismiss_alerts(driver)

    # 偵測是否已完成
    try:
        page_text = driver.find_element(By.TAG_NAME, 'body').text
    except Exception:
        page_text = ''
    done_keywords = ['謝謝您的回覆', '您已經完成這活動', '已完成', 'already completed', '感謝您的填寫']
    if any(kw in page_text for kw in done_keywords) or 'completed' in driver.current_url:
        print('  ✅ 問卷已完成（跳過）')
        return True

    try:
        start = driver.find_element(By.XPATH,
            '//a[contains(text(),"開始填寫") or contains(text(),"填寫回答") or contains(text(),"再次填寫") or contains(text(),"開始")]')
        driver.get(start.get_attribute('href'))
        time.sleep(3)
        _dismiss_alerts(driver)
    except Exception:
        pass

    def fill_and_submit_in_current_context():
        radio_groups = {}
        for r in driver.find_elements(By.CSS_SELECTOR, 'input[type=radio]'):
            name = r.get_attribute('name') or ''
            val  = r.get_attribute('value') or ''
            if name and val:
                radio_groups.setdefault(name, []).append(val)

        for name, vals in radio_groups.items():
            max_val = max(vals, key=lambda v: int(v) if v.lstrip('-').isdigit() and int(v) >= 0 else -999)
            try:
                r = driver.find_element(By.CSS_SELECTOR,
                    f'input[type=radio][name="{name}"][value="{max_val}"]')
                driver.execute_script("arguments[0].click();", r)
            except Exception as e:
                print(f'    ✗ {name}: {e}')

        for ta in driver.find_elements(By.CSS_SELECTOR, 'textarea'):
            try:
                ta.clear()
                ta.send_keys('課程內容豐富實用，解說清晰易懂，獲益良多，感謝臺北ｅ大提供優質學習資源。')
            except Exception:
                pass

        try:
            submitted = driver.execute_script("""
                var keywords = ['送出並結束', '提交問卷', '送出問卷', '送出', '提交', '完成回答', '完成', '儲存回答', '儲存', 'Submit', 'Save', '確定'];
                var btns = Array.from(document.querySelectorAll(
                    'input[type=submit], button[type=submit], button, input.btn, a.btn, input[type=button]'));
                for (var b of btns) {
                    var txt = (b.value || b.textContent || b.innerText || '').trim();
                    if (keywords.some(function(k){ return txt.indexOf(k) >= 0; })) {
                        b.scrollIntoView(true); b.click(); return txt;
                    }
                }
                var submits = document.querySelectorAll('input[type=submit], button[type=submit], input[value*="送出"], input[value*="提交"]');
                if (submits.length > 0) {
                    var sb = submits[0];
                    var txt = (sb.value || sb.textContent || 'Submit').trim();
                    sb.scrollIntoView(true); sb.click(); return txt;
                }
                return null;
            """)
            return submitted
        except Exception:
            return None

    # 最外層 context 嘗試
    submitted = fill_and_submit_in_current_context()
    if submitted:
        time.sleep(3)
        _dismiss_alerts(driver)
        print(f'  問卷送出: {submitted!r} | {driver.title}')
        return True

    # 若最外層沒找到按鈕，嘗試進 iframe 尋找
    iframes = driver.find_elements(By.TAG_NAME, 'iframe')
    for idx, frame in enumerate(iframes):
        try:
            driver.switch_to.frame(frame)
            sub_submitted = fill_and_submit_in_current_context()
            if sub_submitted:
                time.sleep(3)
                driver.switch_to.default_content()
                _dismiss_alerts(driver)
                print(f'  問卷送出 (iframe {idx}): {sub_submitted!r}')
                return True
        except Exception:
            pass
        finally:
            driver.switch_to.default_content()

    print('  ✗ 找不到送出按鈕')
    return False
