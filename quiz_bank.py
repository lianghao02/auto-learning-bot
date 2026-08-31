"""
臺北e大 測驗自動作答模組
- 查 GAS 題庫 → 命中直接答 → 送出
- 未知題：呼叫 AI 分析答案 → 填答 → 送出 → 存 GAS
- AI 失敗 fallback：猜 val=0 送出 → review 讀正解 → 存 GAS → 再考一次
"""

import re, json, time, requests, difflib, threading, sys
from utils.security import validate_ai_base_url
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoAlertPresentException

GAS_URL = 'https://script.google.com/macros/s/AKfycbzYUNM--zLlS8El6YR6lIiKerBIz1M6rL2gM8nTGicmEjfh_1TNiBo12YcVsb37J7Cl/exec'


# ── 工具 ─────────────────────────────────────────────

def _safe_print(text):
    """安全輸出字串，防範 Windows CP950/Big5 控制台拋出 UnicodeEncodeError。"""
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

def gas_fetch_bank(course_id):
    """
    從 GAS 取得該課程題庫。
    回傳 dict: {normalize(q_text): val_str}
    支援兩種回傳格式：
      - 新格式：{status:'ok', data:[...]}
      - 舊/未支援：[] 或其他 list
    """
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
                bank[key] = str(row.get('val', '0'))
        if bank:
            print(f'  [題庫] 從 GAS 載入 {len(bank)} 題（course_id={course_id}）')
        else:
            print(f'  [題庫] GAS 目前沒有此課程題庫（course_id={course_id}），將用 AI/猜題建立題庫')
        return bank
    except Exception as e:
        print(f'  [題庫] GAS 載入失敗: {e}')
        return {}

def _taipei_question_payload(course_id, q):
    opts = q.get('options', {}) or {}
    return {
        'course_id': str(course_id),
        'q_text': q.get('qtext', ''),
        'opt0': opts.get('0', ''),
        'opt1': opts.get('1', ''),
        'opt2': opts.get('2', ''),
        'opt3': opts.get('3', ''),
    }

def gas_report_missing_questions(course_id, questions, course_name='', username='', config=None):
    """Report Taipei E-da missing questions to GAS/TG without blocking the quiz."""
    if not questions:
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

def gas_save_questions(course_id, questions_with_answers, course_name='', username=''):
    """
    把新答案存回 GAS/GitHub 共用題庫。
    questions_with_answers: [{q_text, val, opt0..opt3}, ...]
    """
    if not questions_with_answers:
        return
    payload = {
        'action': 'taipei_quiz_save',
        'course_id': str(course_id),
        'course': course_name,
        'username': username,
        'questions': [dict(course_id=course_id, **q) for q in questions_with_answers]
    }
    try:
        r = requests.post(GAS_URL, json=payload, timeout=15)
        result = r.json()
        if result.get('status') == 'ok':
            print(f'  [題庫] 已同步共用題庫: added={result.get("added")}, updated={result.get("updated")}')
        else:
            print(f'  [題庫] GAS 回傳異常: {result}')
    except Exception as e:
        print(f'  [題庫] GAS 存入失敗: {e}')

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
                resolved_ans = opt_map.get(ans_code_str, str(ans_code).strip())

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

    model = config.get('ai_model', 'gemini-2.0-flash')

    from utils.security import global_ai_rate_limiter, mask_api_key
    if not global_ai_rate_limiter.acquire(timeout=15.0):
        return {"success": False, "error": "超出每分鐘請求速率上限（5 RPM），請稍候重試", "answers": {}, "parsed_answers": {}}

    masked_key = mask_api_key(api_key)
    _safe_print(f"  [AI批次] 正在呼叫 {provider} ({model}) 端點: {base_url} (Key: {masked_key})")


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

    try:
        if provider == "Claude":
            url = f"{base_url}/messages"
            claude_payload = {
                "model": model,
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            }
            resp = requests.post(url, headers=headers, json=claude_payload, timeout=25)
            resp.raise_for_status()
            raw_text = resp.json()["content"][0]["text"].strip()
        else:
            url = f"{base_url}/chat/completions"
            resp = requests.post(url, headers=headers, json=payload, timeout=25)
            resp.raise_for_status()
            raw_text = resp.json()["choices"][0]["message"]["content"].strip()

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

            ans_code_str = str(ans_code).strip()
            answers_by_idx[idx_str] = ans_code_str

            opts = q.get("options", [])
            label_to_val = {opt["label"].upper(): str(opt["val"]) for opt in opts if "label" in opt and "val" in opt}

            codes = [c.strip().upper() for c in ans_code_str.replace("，", ",").replace("、", ",").replace(" ", ",").split(",") if c.strip()]
            matched_vals = [label_to_val[c] for c in codes if c in label_to_val]

            if matched_vals:
                parsed_answers[q["name"]] = matched_vals if len(matched_vals) > 1 else matched_vals[0]

        # 儲存進 SQLite
        save_ai_answers_to_sqlite(questions_data, answers_by_idx)

        _safe_print(f"  ✓ [AI批次] 成功解析 {len(answers_by_idx)}/{len(questions_data)} 題解答並同步至題庫")
        return {
            "success": True,
            "answers": answers_by_idx,
            "parsed_answers": parsed_answers,
            "raw_text": raw_text,
            "error": None
        }

    except requests.exceptions.HTTPError as e:
        status_code = getattr(e.response, "status_code", None)
        if status_code == 429:
            err_msg = "Google API 速率受限 (429 Resource Exhausted)，已自動防護"
        elif status_code == 401:
            err_msg = "API Key 無效或授權失敗 (401 Unauthorized)"
        else:
            err_msg = f"API 呼叫失敗 (HTTP {status_code})"
        _safe_print(f"  ❌ [AI批次] {err_msg}")
        return {"success": False, "error": err_msg, "answers": {}, "parsed_answers": {}}
    except Exception as e:
        err_msg = f"AI 解析過程異常: {e}"
        _safe_print(f"  ❌ [AI批次] {err_msg}")
        return {"success": False, "error": err_msg, "answers": {}, "parsed_answers": {}}



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
    """
    讀取作答頁所有題目與選項。
    回傳 list of dict:
      { name, qtext, options: {val: text}, prefix }
    """
    result = driver.execute_script("""
        function clean(s) { return (s || '').replace(/\\s+/g, ' ').trim(); }
        var out = [];
        var blocks = document.querySelectorAll('.que, div[id^="question-"]');
        blocks.forEach(function(q, qi) {
            var qtext = q.querySelector('.qtext');
            if (!qtext) {
                qtext = q.querySelector('.formulation .qtext, .formulation .questiontext');
            }
            var qtxt = qtext ? clean(qtext.textContent) : '';
            if (!qtxt) {
                var formulation = q.querySelector('.formulation');
                if (formulation) {
                    var clone = formulation.cloneNode(true);
                    clone.querySelectorAll('.answer, input, label, .ablock').forEach(function(el){ el.remove(); });
                    qtxt = clean(clone.textContent);
                }
            }
            var opts = {};
            q.querySelectorAll('input[type=radio]').forEach(function(r) {
                var val = r.value;
                if (val === '-1') return;
                var name = r.name;
                var labelTxt = '';
                var labelEl = document.getElementById(r.id + '_label');
                if (labelEl) labelTxt = clean(labelEl.textContent);
                if (!labelTxt) {
                    var lbl = q.querySelector('label[for="' + r.id + '"]');
                    if (lbl) labelTxt = clean(lbl.textContent);
                }
                if (!labelTxt) {
                    var parent = r.closest('div, p, span, li');
                    if (parent) labelTxt = clean(parent.textContent);
                }
                if (!opts._name) opts._name = name;
                opts[val] = labelTxt;
            });
            if (opts._name && qtxt) {
                out.push({name: opts._name, qtext: qtxt, options: opts});
            }
        });
        return out;
    """)
    seen = set()
    deduped = []
    for q in result:
        q['options'].pop('_name', None)
        q['qtext'] = _clean_question_text(q.get('qtext', ''))
        key = (q.get('name'), _normalize(q.get('qtext', '')))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(q)
    return deduped

def _fill_answers(driver, answers):
    """
    填答：answers = {name: val}
    """
    for name, val in answers.items():
        try:
            # 優先使用原有的 value 屬性精確匹配
            r = driver.find_element(By.CSS_SELECTOR,
                f'input[type=radio][name="{name}"][value="{val}"]')
            driver.execute_script("arguments[0].click();", r)
            driver.execute_script(
                "arguments[0].checked=true;"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", r)
        except Exception as e:
            # 💡 防禦性填答：當 value 對不上時（例如題庫 1-based 與網頁 0-based 不一致）
            try:
                # 尋找該題名下所有的 radio 按鈕
                radios = driver.find_elements(By.CSS_SELECTOR, f'input[type=radio][name="{name}"]')
                if radios:
                    # 嘗試將 val 轉為整數
                    val_int = int(val)
                    target_idx = -1

                    # 情況一：題庫存的是 1-based (1~4)，網頁是 0-based。當 val=4 且 radios 有 4 個時，目標 index 為 3
                    if 1 <= val_int <= len(radios):
                        target_idx = val_int - 1
                    # 情況二：如果 val 剛好是 0-based 的 index (0~3)
                    elif 0 <= val_int < len(radios):
                        target_idx = val_int

                    if target_idx != -1:
                        r = radios[target_idx]
                        driver.execute_script("arguments[0].click();", r)
                        driver.execute_script(
                            "arguments[0].checked=true;"
                            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", r)
                        print(f'  [填答] 💡 透過索引重新填答成功：{name} 第 {target_idx + 1} 個選項 (val={val})')
                        continue
            except Exception:
                pass
            print(f'  [填答] ✗ {name}={val}: {e}')

def _submit_quiz(driver, wait):
    """點完成作答 → summary → 全部送出並結束 → modal confirm → review URL"""
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
            driver.execute_script("arguments[0].click();", modal_save)
        except:
            try: driver.switch_to.alert.accept()
            except: pass
        time.sleep(2); _dismiss_alerts(driver)

    print(f'  [測驗] review → {driver.current_url}')
    return driver.current_url

def _read_correct_from_review(driver):
    """
    從 review 頁讀每題的正解 val。
    策略：
      1. 找 .answer div.correct 裡的 radio（Moodle 標示正確選項，需開啟顯示正解）
      2. 若題目整體標示 .que.correct → checked radio = 正解
      3. 若題目整體標示 .que.incorrect → 記錄題目是非題還是 MCQ
         - 是非題 (options=2)：翻轉 checked val
         - MCQ：無法判斷，回傳 None（後續 AI 重答）
    回傳 {name: val}（確認正確的才加入）
    """
    result = driver.execute_script("""
        var out = {};
        document.querySelectorAll('.que').forEach(function(q) {
            var name   = null;
            var val    = null;
            var radios = Array.from(q.querySelectorAll('input[type=radio]')).filter(
                function(r){ return r.value !== '-1'; });
            if (!radios.length) return;

            // 1. 優先：.answer div.correct 裡有 radio（正解標示）
            var correctDiv = q.querySelector(
                '.answer .r0.correct, .answer .r1.correct, ' +
                '.answer .r2.correct, .answer .r3.correct, ' +
                '.answer div.correct');
            if (correctDiv) {
                var r = correctDiv.querySelector('input[type=radio]');
                if (r && r.value !== '-1') { name = r.name; val = r.value; }
            }

            // 2. 題目本身標示 correct（我們答對了）
            if (!name && q.classList.contains('correct')) {
                radios.forEach(function(r){ if (r.checked) { name=r.name; val=r.value; } });
            }

            // 3. 題目本身標示 incorrect（答錯了）
            var isIncorrect = q.classList.contains('incorrect');
            if (!name && isIncorrect) {
                var checked_r = null;
                radios.forEach(function(r){ if (r.checked) checked_r = r; });
                if (checked_r) {
                    // 是非題 (2個選項)：翻轉
                    if (radios.length === 2) {
                        var other = radios.find(function(r){ return r !== checked_r; });
                        if (other) { name = other.name; val = other.value; }
                    }
                    // MCQ：無法確定，跳過，避免把錯選項存回題庫
                }
            }

            // 4. 最後 fallback：checked radio，只在頁面沒有標示 incorrect 時保底
            if (!name && !isIncorrect) {
                radios.forEach(function(r){ if (r.checked) { name=r.name; val=r.value; } });
            }

            if (name && val !== null) out[name] = val;
        });
        return out;
    """)
    return result

def _get_score_from_review(driver):
    """從 review 頁讀成績，回傳 (score_text, is_100)"""
    try:
        body = driver.find_element(By.TAG_NAME, 'body').text
        for line in body.split('\n'):
            if '分' in line and ('得' in line or '滿分' in line):
                return line.strip()
    except: pass
    return ''

def _is_100(score_text):
    """判斷成績是否為 100 分（抓「得X.XX分」的分子）"""
    m = re.search(r'得\s*([\d.]+)\s*分', score_text)
    if m:
        try: return float(m.group(1)) >= 100
        except: pass
    # fallback: 找 X/Y 格式
    m2 = re.search(r'(\d+)\s*/\s*\d+', score_text)
    if m2:
        try: return int(m2.group(1)) >= 100
        except: pass
    return False


# ── 主函式 ──────────────────────────────────────────

def do_quiz_with_bank(driver, wait, course_id, quiz_view_url, config=None, course_name='', username='', quiz_interactive_callback=None, min_pass_score=60.0):
    """
    臺北E大測驗流程：
    1. 第一次只用 GAS 題庫作答。
    2. 不及格才第二次啟用本機 AI 補答。
    3. 若本機無 AI 或仍未通過，最多跑 3 次；缺題背景回報 GAS/TG，由 GAS 端 AI 補 JSON DB。
    回傳 (score_text, is_100: bool)
    """
    if config is None:
        config = {}

    provider = config.get('ai_provider', 'OpenAI')
    ai_keys = config.get('ai_keys', {}) or {}
    has_local_ai = bool(ai_keys.get(provider) or config.get('ai_api_key', ''))

    print(f'\n=== 測驗 (course_id={course_id}) ===')
    print('  [題庫] 使用臺北E大 GAS/GitHub 共用題庫')
    print('  [測驗] 第一次只用題庫；未通過才啟用本機 AI')

    best_score_text = ''
    best_is_100 = False
    reported_missing_keys = set()

    def _question_record(q, val):
        return {
            'q_text': q['qtext'], 'val': val,
            'opt0': q['options'].get('0',''), 'opt1': q['options'].get('1',''),
            'opt2': q['options'].get('2',''), 'opt3': q['options'].get('3',''),
        }

    def _save_known_answers(to_save):
        if not to_save:
            return
        deduped = []
        seen = set()
        for item in to_save:
            key = _normalize(item.get('q_text', ''))
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        if deduped:
            gas_save_questions(course_id, deduped, course_name=course_name, username=username)
            print(f'  [題庫] 本次同步共用題庫 {len(deduped)} 題')

    def _report_missing_once(missing_qs):
        fresh = []
        for q in missing_qs:
            key = _normalize(q.get('qtext', ''))
            if not key or key in reported_missing_keys:
                continue
            reported_missing_keys.add(key)
            fresh.append(q)
        if fresh:
            gas_report_missing_questions(
                course_id,
                fresh,
                course_name=course_name,
                username=username,
                config=config,
            )

    def _is_score_passed(score_str, min_score=60.0):
        m = re.search(r'得\s*([\d.]+)\s*分', score_str)
        if m:
            try: return float(m.group(1)) >= min_score
            except Exception: pass
        m2 = re.search(r'(\d+)\s*/\s*\d+', score_str)
        if m2:
            try: return int(m2.group(1)) >= min_score
            except Exception: pass
        return False

    def _run_attempt(attempt_no, use_local_ai):
        print(f'\n  [測驗] 第 {attempt_no} 次作答：' + ('題庫 + 本機AI' if use_local_ai else '只用題庫'))

        bank = gas_fetch_bank(course_id)
        attempt_url = _start_or_resume_quiz(driver, wait, quiz_view_url)
        if not attempt_url:
            print('  [測驗] ✗ 無法開始作答')
            return '', False, {}, {}

        questions = _read_questions(driver)
        print(f'  [測驗] 讀到 {len(questions)} 題')
        if not questions:
            try:
                body_preview = driver.find_element(By.TAG_NAME, 'body').text[:300]
            except Exception:
                body_preview = ''
            print(f'  [測驗] ⚠️ 沒讀到題目，頁面文字預覽: {body_preview!r}')

        answers = {}
        missing_qs = []
        ai_answered = []

        # 1. 優先比對共用題庫
        for q in questions:
            val = lookup_bank(bank, q['qtext'])
            if val is not None:
                answers[q['name']] = val
                print(f'  ✓ [庫] {q["qtext"][:28]}... → val={val}')

        # 2. 若有未命中題目，且啟用人機協同作答模式
        cb = quiz_interactive_callback or config.get('quiz_interactive_callback')
        is_interactive = bool(config.get('interactive_quiz_for_session')) and callable(cb)
        unanswered_qs = [q for q in questions if q['name'] not in answers]

        if unanswered_qs:
            questions_data = []
            opt_labels = ["A", "B", "C", "D", "E", "F", "G", "H"]
            for idx, q in enumerate(questions, 1):
                opts_list = []
                for opt_idx, (opt_val, opt_txt) in enumerate(sorted(q['options'].items(), key=lambda x: str(x[0]))):
                    label = opt_labels[opt_idx] if opt_idx < len(opt_labels) else str(opt_idx + 1)
                    opts_list.append({"label": label, "text": opt_txt, "val": str(opt_val)})

                is_tf = len(opts_list) == 2 and any(k in q['qtext'] or k in "".join(o['text'] for o in opts_list) for k in ["是非", "是否", "對錯", "○", "╳", "⭕", "❌"])
                q_type = "是非" if is_tf else "單選"
                questions_data.append({
                    "index": idx,
                    "name": q['name'],
                    "type": q_type,
                    "is_multiple": False,
                    "q_text": q['qtext'],
                    "options": opts_list,
                    "raw_q": q
                })

            # 若使用者開啟「AI 全自動背景作答」且具備 API Key，直接背景秒答
            ai_auto_solve = bool(config.get("ai_auto_solve", False))
            if ai_auto_solve and has_local_ai:
                print('  ⚡ 啟用 AI 全自動背景極速作答（Gemini 批次模式）...')
                batch_res = ai_batch_solve_quiz(course_name or f"課程 {course_id}", questions_data, config)
                if batch_res.get("success") and batch_res.get("parsed_answers"):
                    for q_name, q_val in batch_res["parsed_answers"].items():
                        answers[q_name] = q_val if not isinstance(q_val, list) else q_val[0]
                        print(f'  ✓ [AI全自動] {q_name} → val={answers[q_name]}')

            # 否則若啟用人機協同助理彈窗
            elif is_interactive and unanswered_qs:
                print('  🤖 啟用人機協同作答助理（彈窗回貼 / Gemini 批次）...')
                parsed = cb(course_name or f"課程 {course_id}", questions_data)
                if parsed == "STOP_ALL":
                    print('  🛑 使用者選擇結束本次執行')
                    return '', False, {}, {}
                elif parsed == "SKIP":
                    print('  ⏩ 使用者選擇跳過測驗，將自動檢查並完成問卷')
                    return 'SKIPPED', False, {}, {}
                elif isinstance(parsed, dict) and parsed:
                    for q_item in questions_data:
                        idx = q_item["index"]
                        if idx in parsed:
                            chosen_labels = [l.upper() for l in parsed[idx]]
                            for opt in q_item["options"]:
                                if opt["label"].upper() in chosen_labels:
                                    answers[q_item["name"]] = opt["val"]
                                    print(f'  ✓ [人機/Gemini] {q_item["q_text"][:28]}... → 選 {opt["label"]} (val={opt["val"]})')
                                    break


        # 3. 仍未作答者，由本機 AI 或猜題保底
        for q in questions:
            if q['name'] in answers:
                continue

            if use_local_ai and has_local_ai:
                val = ai_guess_answer(q['qtext'], q['options'], config)
                if val is not None:
                    answers[q['name']] = str(val)
                    ai_answered.append((q, str(val)))
                    print(f'  ✓ [AI] {q["qtext"][:28]}... → val={val}')
                    continue

            answers[q['name']] = '0'
            missing_qs.append(q)
            print(f'  ? [猜] {q["qtext"][:28]}... → val=0')

        _report_missing_once(missing_qs)

        _fill_answers(driver, answers)
        _submit_quiz(driver, wait)
        time.sleep(2)

        correct_by_name = _read_correct_from_review(driver)
        score_text = _get_score_from_review(driver)
        is_100 = _is_100(score_text)
        print(f'  [成績{attempt_no}] {score_text}  (100分: {is_100})')

        name_to_q = {q['name']: q for q in questions}
        correct_by_text = {}
        to_save = []

        for name, val in correct_by_name.items():
            q = name_to_q.get(name)
            if not q:
                continue
            correct_by_text[q['qtext']] = val
            to_save.append(_question_record(q, val))

        for q, ai_val in ai_answered:
            real_val = correct_by_name.get(q['name'])
            if real_val and real_val != ai_val:
                print(f'  [AI誤] {q["qtext"][:28]}... AI={ai_val} 正解={real_val}')
            if not real_val:
                to_save.append(_question_record(q, ai_val))

        _save_known_answers(to_save)
        return score_text, is_100, correct_by_text, answers

    attempt_plan = [False]
    if has_local_ai:
        attempt_plan.append(True)
    else:
        print('  [AI] 本機未設定 AI key，將用題庫/猜答最多跑 3 次，缺題交給 GAS 端 AI 補庫')
        attempt_plan.append(False)
    attempt_plan.append(False)

    for idx, use_ai in enumerate(attempt_plan, start=1):
        score_text, is_100, _, _ = _run_attempt(idx, use_ai)
        if score_text:
            best_score_text = score_text
            best_is_100 = is_100
        if is_100 or _is_score_passed(score_text, min_score=min_pass_score):
            print(f'  🎉 測驗達標通過！【{score_text}】（門檻: {int(min_pass_score)} 分）')
            return score_text, is_100
        if idx == 1:
            print('  [測驗] 第一次未達及格標準，準備第二次補答')
        elif idx < len(attempt_plan):
            print('  [測驗] 尚未及格，繼續下一次')

    return best_score_text, best_is_100


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
