from __future__ import annotations

from egov.helpers import (
    By,
    EC,
    EXAM_AI_OUTAGE_DEFER_SECONDS,
    EXAM_AI_OUTAGE_MAX_DEFERS,
    Fore,
    GLOBAL_DB_LOCK,
    INTERACTIVE_QUIZ_TIMEOUT_SECONDS,
    MAX_QUIZ_ATTEMPTS,
    NoAlertPresentException,
    Options,
    Service,
    Style,
    UnexpectedAlertPresentException,
    WebDriverWait,
    _ALL_ABOVE_PATTERNS,
    _COURSE_ENTRY_SCRIPT,
    _TRUE_FALSE_ANSWERS,
    _can_resolve_exam_answer,
    _is_driver_disconnect_error,
    _match_unavailable_course_reason,
    _negation_signature,
    _normalize_q,
    answer_values,
    app_dir,
    can_submit,
    closing,
    ctypes,
    download_best_chromedriver,
    draw_bar,
    ensure_seeded_database,
    get_close_matches,
    get_db_connection,
    get_package_dashboard_script,
    grade_evidence,
    grade_passed,
    is_cloud_sync_enabled,
    json,
    log_path,
    logger,
    maintain_driver_windows_hidden,
    match_radio_option_index,
    needs_ai_review,
    os,
    parse_multiple_choice_answers,
    psutil,
    random,
    re,
    requests,
    resolve_gas_url,
    sec_to_str,
    set_driver_window_visibility,
    sqlite3,
    sys,
    threading,
    time,
    to_sec,
    traceback,
    unicodedata,
    user_data_path,
    validate_ai_base_url,
    webdriver,
    write_json_atomically,
)


class EgovQuestionStoreMixin:
    """本機 SQLite 題庫查詢、AI 單題補答與雲端題庫同步。"""

    @staticmethod
    def _clean_answer(ans: str) -> str:
        """去除答案的數字前綴（如 '2.唾液' → '唾液'）及 || 後綴"""
        import re as _re

        if isinstance(ans, str) and ans.strip().startswith('['):
            try:
                values = json.loads(ans)
                if isinstance(values, list):
                    return values
            except (ValueError, TypeError):
                pass
        # 去除 '1.', '2. ', '3、' 等數字前綴（保留純數字答案如 '0.74'）
        ans = _re.sub(r"^\d+[.\uff0e\u3001]\s*(?=[^\d])", "", ans).strip()
        # 去除 '||' 後綴（標注符號）
        ans = _re.sub(r"\s*\|\|.*$", "", ans).strip()
        return ans

    def _find_answer(self, question_text, *, num_options=None):
        """在題庫中查詢答案。

        策略（依優先順序）：
        1. normalize 後精準比對 _answer_map
        2. difflib fuzzy 比對（cutoff=0.90，且強制驗證否定詞簽章與題型相容）
        3. 都找不到 → None

        回傳 str（答案文字）或 None。
        """
        if not question_text or len(question_text.strip()) < 4:
            return None
        q_norm = _normalize_q(question_text.strip())
        if not q_norm or len(q_norm) < 4:
            return None

        # 1. 精準比對
        row = self._answer_map.get(q_norm)
        if row:
            return self._clean_answer(row["answer"])

        # 2. difflib fuzzy（只在有 key list 時執行，避免空集合 warning）
        if self._answer_keys:
            q_neg_sig = _negation_signature(q_norm)
            matches = get_close_matches(q_norm, self._answer_keys, n=3, cutoff=0.90)
            for match_key in matches:
                row = self._answer_map[match_key]
                # 否定詞簽章不一致（例如「不屬於」vs「屬於」）禁止模糊配對
                if _negation_signature(match_key) != q_neg_sig:
                    continue
                cleaned = self._clean_answer(row["answer"])
                # 多選項單／多選題（>=3 選項）禁止模糊配到純是非題
                if (
                    num_options is not None
                    and num_options >= 3
                    and not row.get("options")
                    and isinstance(cleaned, str)
                    and cleaned.strip().lower() in _TRUE_FALSE_ANSWERS
                ):
                    continue
                logger.debug(f"   🔍 fuzzy match: {row['question'][:30]!r}")
                return cleaned

        # 3. 向後相容：舊 self.answers list 雙向包含比對（只在未從 DB 載入時有資料）
        if self.answers:
            q = question_text.strip()
            MIN_LEN = 12
            for keyword, ans in self.answers:
                if keyword in q:
                    if len(keyword) >= MIN_LEN and len(q) >= MIN_LEN:
                        return self._clean_answer(ans)
                elif q in keyword:
                    if len(q) >= MIN_LEN:
                        return self._clean_answer(ans)

        return None

    def _ai_find_answer(self, question_text: str, option_texts: list):
        """題庫找不到答案時，透過共用 AI 通道協助選答（含限速、配額追蹤與 429 熔斷）。"""
        if not option_texts:
            return None
        if getattr(self, "_ai_circuit_broken", False):
            return None

        cleaned_options = [
            str(opt).strip() if str(opt).strip() else f"選項{i + 1}"
            for i, opt in enumerate(option_texts)
        ]
        options_str = "\n".join(
            [f"{i + 1}. {opt}" for i, opt in enumerate(cleaned_options)]
        )
        prompt = (
            "你是考試作答助手。請從以下選項中選出正確答案。\n"
            "務必只回覆一個選項編號，例如 1、2、3、4。\n"
            "不要回覆選項文字，不要解釋，不要加前後綴。\n\n"
            f"題目：{question_text}\n\n"
            f"選項：\n{options_str}\n\n"
            "正確答案選項編號："
        )

        from quiz_bank import AI_SINGLE_TIMEOUT, request_ai_completion

        result = request_ai_completion(
            [{"role": "user", "content": prompt}],
            self.config,
            json_mode=False,
            max_tokens=150,
            temperature=0.0,
            timeout=AI_SINGLE_TIMEOUT,
            log_prefix="[AI單題]",
        )
        if result["success"]:
            answer = result["text"]
            logger.info(f"   🤖 AI 補充答案（{result['model']}）：{answer!r}")
            return answer

        if result.get("rate_limited") and not getattr(self, "_ai_circuit_broken", False):
            self._ai_circuit_broken = True
            bank_count = len(getattr(self, "_answer_map", {}) or {})
            if hasattr(self, "logger"):
                self.logger.warning(
                    f"⚠️ 偵測到 Gemini API 超出限額 (429)，本工作階段自動暫停 AI 呼叫，切換為『純本地 {bank_count} 題庫速答』模式"
                )
        elif result.get("error") and "網址遭安全規則拒絕" in result["error"] and hasattr(self, "logger"):
            self.logger.error(f"❌ {result['error']}")
        return None

    def _save_answers_to_db(self, answers: dict, source: str = ""):
        """交易成功後才更新記憶體及回報成功；失敗不留下部分答案。"""
        from contextlib import closing
        if not answers:
            return False
        try:
            db_path = str(ensure_seeded_database())
            with GLOBAL_DB_LOCK:
                with closing(get_db_connection(db_path, timeout=30.0)) as conn:
                    with conn:
                        conn.execute("""
                            CREATE TABLE IF NOT EXISTS questions (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                question TEXT UNIQUE NOT NULL,
                                option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
                                answer TEXT
                            )
                        """)
                        added = 0
                        for question, answer in answers.items():
                            if conn.execute('SELECT id FROM questions WHERE question = ?', (question,)).fetchone():
                                conn.execute('UPDATE questions SET answer = ? WHERE question = ?', (answer, question))
                            else:
                                conn.execute('INSERT INTO questions (question, answer) VALUES (?, ?)', (question, answer))
                                added += 1
                answer_map = self.__dict__.setdefault('_answer_map', {})
                answer_keys = self.__dict__.setdefault('_answer_keys', [])
                for question, answer in answers.items():
                    key = _normalize_q(question)
                    if key:
                        if key not in answer_map:
                            answer_keys.append(key)
                        answer_map[key] = {'answer': answer, 'options': [], 'question': question}
            tag = f'（{source}）' if source else ''
            logger.info(f'   💾 已同步 {len(answers)} 題到 questions.db{tag}（新增 {added} 題）')
            return True
        except Exception as exc:
            logger.warning(f'   ⚠️ 寫入 questions.db 失敗: {exc}')
            return False


    # ── GAS 題庫同步 URL（送出缺題 + 下載更新共用同一個 endpoint）──
    _GAS_DB_URL = "https://script.google.com/macros/s/AKfycbzYUNM--zLlS8El6YR6lIiKerBIz1M6rL2gM8nTGicmEjfh_1TNiBo12YcVsb37J7Cl/exec"
    _GAS_PATCH_URL = "https://raw.githubusercontent.com/waynelord0628-beep/auto-learning-bot/main/patches/questions_patch.json"

    def _update_db_from_gas(self):
        """啟動時靜默背景同步：從 GitHub Raw 直接下載 questions_patch.json 並 upsert 進本地 questions.db。

        格式：[{"question":"...","answer":"...","options":["A","B","C","D"],...}, ...]
        """
        try:
            logger.info("📥 正在從雲端同步最新題庫（背景）...")
            resp = requests.get(
                self._GAS_PATCH_URL,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or len(data) == 0:
                logger.info("📥 GAS 回傳題庫為空或格式不符，略過")
                return

            db_path = str(ensure_seeded_database())
            added = 0
            updated = 0
            with GLOBAL_DB_LOCK, closing(get_db_connection(db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS questions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        question TEXT UNIQUE NOT NULL,
                        option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
                        answer TEXT
                    )
                """)
                for item in data:
                    q = (item.get("question") or "").strip()
                    a = (item.get("answer") or "").strip()
                    if not q or not a:
                        continue
                    # 支援 options:[] 格式（questions_patch.json）與 option_a/b/c/d 格式（GAS doGet）
                    opts = item.get("options") or []
                    oa = (opts[0] if len(opts) > 0 else item.get("option_a") or "").strip()
                    ob = (opts[1] if len(opts) > 1 else item.get("option_b") or "").strip()
                    oc = (opts[2] if len(opts) > 2 else item.get("option_c") or "").strip()
                    od = (opts[3] if len(opts) > 3 else item.get("option_d") or "").strip()
                    existing = conn.execute(
                        "SELECT id, answer FROM questions WHERE question = ?", (q,)
                    ).fetchone()
                    if existing:
                        if existing[1] != a:
                            conn.execute(
                                "UPDATE questions SET answer=?, option_a=?, option_b=?, option_c=?, option_d=? WHERE question=?",
                                (a, oa, ob, oc, od, q),
                            )
                            updated += 1
                    else:
                        conn.execute(
                            "INSERT INTO questions (question, option_a, option_b, option_c, option_d, answer) VALUES (?,?,?,?,?,?)",
                            (q, oa, ob, oc, od, a),
                        )
                        added += 1
                    # 同步記憶體 _answer_map
                    nk = _normalize_q(q)
                    if nk:
                        if nk not in self._answer_map:
                            self._answer_keys.append(nk)
                        self._answer_map[nk] = {
                            "answer": a,
                            "options": [o for o in [oa, ob, oc, od] if o],
                            "question": q,
                        }
                conn.commit()
            logger.info(
                f"📥 GAS 題庫同步完成：新增 {added} 題，更新 {updated} 題"
                f"，記憶體共 {len(self._answer_map)} 題"
            )
        except Exception as e:
            logger.warning(f"📥 GAS 題庫同步失敗（不影響本機題庫）: {e}")

