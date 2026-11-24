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


class EgovExamSurveyMixin:
    """自動測驗、AI 批次補答、交卷判分、s_main 通過複查、正解擷取與自動問卷。"""

    def _accept_alert(self):
        """若有 alert/confirm 對話框則點確定，無則跳過"""
        try:
            WebDriverWait(self.driver, 3).until(EC.alert_is_present())
            self.driver.switch_to.alert.accept()
            return True
        except Exception:
            return False

    def _harvest_correct_answers(self, view_result_url: str) -> dict:
        """
        從 view_result.php 頁面讀取正確答案。
        流程：
          1. 取得 queryStr 和 isReadAnswer（JS 變數）
          2. 若 isReadAnswer != '1'，用 http_session GET set_see_question_result.php
          3. reload 後，找每題 span[style*='background-color: green'] input → 取 value
          4. 回傳 {題目關鍵字: 答案value} dict（可能為空）
        """
        result = {}
        try:
            # 確認在正確視窗
            time.sleep(1)
            query_str = self.driver.execute_script(
                "try { return typeof queryStr !== 'undefined' ? queryStr : null; } catch(e) { return null; }"
            )
            is_read = self.driver.execute_script(
                "try { return typeof isReadAnswer !== 'undefined' ? isReadAnswer : '0'; } catch(e) { return '0'; }"
            )
            if not query_str:
                logger.debug("   harvest: 無法取得 queryStr，放棄")
                return result

            logger.info(f"   📖 嘗試讀取正確答案（isReadAnswer={is_read}）")

            if is_read != "1":
                # 呼叫 set_see_question_result.php（優先以當前分站視窗同源 fetch 發送，避免跨分站 school_hash Cookie 衝突）
                base_url = view_result_url.split("/learn/")[0]
                api_url = (
                    f"{base_url}/learn/exam/set_see_question_result.php?{query_str}"
                )
                resp_text = ""
                if callable(getattr(self.driver, "execute_async_script", None)):
                    try:
                        fetch_res = self.driver.execute_async_script(
                            """
                            var url = arguments[0];
                            var done = arguments[arguments.length - 1];
                            fetch(url, {credentials: 'include'})
                                .then(function(r) { return r.text(); })
                                .then(function(t) { done({ok: true, text: t}); })
                                .catch(function(e) { done({ok: false, text: String(e)}); });
                            """,
                            api_url,
                        )
                        if isinstance(fetch_res, dict) and fetch_res.get("ok"):
                            resp_text = str(fetch_res.get("text") or "").strip()
                    except Exception as _fe:
                        logger.debug(f"   同源 fetch set_see_question_result 失敗: {_fe}")

                if resp_text == "1":
                    self.driver.refresh()
                    time.sleep(3)
                else:
                    logger.warning(
                        f"   ⚠️ 讀取答案請求遭伺服器拒絕（回應：{resp_text[:50]!r}）；本課程可能不開放公布答案"
                    )
                    return result

            # 讀取每題的正確答案（span[style*=green] input）+ 選項文字
            q_data = self.driver.execute_script(
                """
                var result = [];
                var rows = document.querySelectorAll('tr.bg03.font01, tr.bg04.font01');
                for (var i = 0; i < rows.length; i++) {
                    var row = rows[i];
                    var p = row.querySelector('p');
                    var qText = p ? p.innerText.trim() : '';
                    if (!qText) continue;
                    // 找 background-color: green 的 span 裡的 input
                    var spans = row.querySelectorAll('span');
                    var correctVals = [];
                    var correctTexts = [];
                    for (var j = 0; j < spans.length; j++) {
                        var bg = spans[j].style.backgroundColor;
                        if (bg === 'green' || bg === 'rgb(0, 128, 0)') {
                            var inp = spans[j].querySelector('input');
                            if (inp) correctVals.push(inp.value);
                            // 取選項文字（span 內去掉 input 的文字）
                            var spanText = spans[j].innerText || spans[j].textContent || '';
                            spanText = spanText.replace(/^[\\s\\d.]+/, '').trim();
                            if (spanText) correctTexts.push(spanText);
                        }
                    }
                    if (correctVals.length > 0) {
                        result.push({q: qText, ans: correctVals, texts: correctTexts});
                    }
                }
                return result;
                """
            )

            if not q_data:
                logger.warning("   ⚠️ 未讀到任何正確答案（可能頁面未更新或格式不符）")
                return result

            # 轉換格式並寫入 answers.json（優先用選項文字，其次用 value）
            for item in q_data:
                q_text = item["q"]
                ans_vals = item["ans"]
                ans_texts = item.get("texts", [])
                # 去掉題號前綴（如 "1. " "（1）" 等），與 auto_exam 的題目文字一致
                q_text_clean = re.sub(r"^[\d０-９]+[.．、。）)\s]+", "", q_text).strip()
                # 保留題目全文作為 key（不截 30 字，避免碰撞）
                key = q_text_clean.strip()
                # 優先用選項文字作為答案，多選以「、」合併為一個字串
                if ans_texts:
                    ans_str = (
                        "、".join(ans_texts) if len(ans_texts) > 1 else ans_texts[0]
                    )
                else:
                    # fallback: 用 input value
                    ans_str = (
                        "、".join(ans_vals)
                        if len(ans_vals) > 1
                        else (ans_vals[0] if ans_vals else "")
                    )
                result[key] = ans_str
                logger.debug(f"   harvest: {key!r} => {ans_str!r}")

            logger.info(f"   📖 讀到 {len(result)} 題正確答案")

            # 寫入 answers.json（list 格式 [{"題目": ..., "答案": ...}]）
            try:
                answers_path = str(user_data_path("answers.json"))
                existing_list = []
                if os.path.exists(answers_path):
                    with open(answers_path, encoding="utf-8") as f:
                        existing_list = json.load(f)
                # 建立題目全文→index 的快速查找（雙向比對以找到相同題目）
                existing_keys = {}
                for idx_e, entry in enumerate(existing_list):
                    ek = entry.get("題目", "").strip()
                    existing_keys[ek] = idx_e
                # 更新或新增
                added = 0
                for key, ans_str in result.items():
                    # 先嘗試精確匹配，再嘗試雙向包含
                    matched_idx = None
                    if key in existing_keys:
                        matched_idx = existing_keys[key]
                    else:
                        for ek, idx_e in existing_keys.items():
                            if (
                                key
                                and ek
                                and len(key) >= 8
                                and len(ek) >= 8
                                and (key in ek or ek in key)
                            ):
                                matched_idx = idx_e
                                break
                    if matched_idx is not None:
                        # 更新現有條目
                        existing_list[matched_idx]["答案"] = ans_str
                    else:
                        existing_list.append({"題目": key, "答案": ans_str})
                        added += 1
                with open(answers_path, "w", encoding="utf-8") as f:
                    json.dump(existing_list, f, ensure_ascii=False, indent=2)
                logger.info(
                    f"   ✅ 已將 {len(result)} 題答案寫入 answers.json（新增 {added} 題，共 {len(existing_list)} 題）"
                )
                # 更新記憶體中的 answers（list of (題目, 答案)）
                for key, ans_str in result.items():
                    self.answers.append((key, ans_str))
            except Exception as e:
                logger.warning(f"   ⚠️ 寫入 answers.json 失敗: {e}")

            # 同步寫入 questions.db（複用 _save_answers_to_db）
            self._save_answers_to_db(result, source="harvest")

        except Exception as e:
            logger.debug(f"   harvest_correct_answers 失敗: {e}")

        return result

    def _check_exam_passed_via_s_main(self, main_window) -> bool:
        """當交卷結果頁未直接顯示單次得分時，回主視窗 s_main 測驗清單複查是否已標記為「已通過」。"""
        if not main_window or not self.driver:
            return False
        prev_win = None
        try:
            prev_win = self.driver.current_window_handle
        except Exception:
            prev_win = None
        try:
            self.driver.switch_to.window(main_window)
            self.driver.switch_to.default_content()
            try:
                self.driver.switch_to.frame("mooc_sysbar")
                exam_link = self.driver.find_element(
                    By.CSS_SELECTOR, "a[href*='exam/exam_list.php'], a[href*='exam']"
                )
                self.driver.execute_script("arguments[0].click();", exam_link)
            except Exception:
                pass
            status, _ = self._wait_s_main_action_or_status(
                done_keywords=("已通過", "已選擇公布答案"),
                none_keywords=(),
                timeout=6.0,
            )
            return status == "done"
        except Exception:
            return False
        finally:
            if prev_win and prev_win != main_window:
                try:
                    if prev_win in self.driver.window_handles:
                        self.driver.switch_to.window(prev_win)
                except Exception:
                    pass

    def _read_exam_result(self, course, _ai_answered=None, *, main_window=None):
        """讀取測驗繳交後的成績與通過狀態並記錄日誌。依據每門課程之 criteria_exam_score 精確核定通過與否。"""
        course_id = str(course.get("course_id", ""))
        course_name = course.get("caption", course_id)
        passed = False
        self._last_exam_score_unknown = False
        time.sleep(3)

        # 取得課程專屬及格門檻（動態支援 60、70、75、80、100 分等各平臺門檻）
        pass_score = 60.0
        for f in [
            "criteria_exam_score",
            "criteria_score",
            "pass_score",
            "exam_pass_score",
            "criteria_test_score",
        ]:
            val = course.get(f)
            if val is not None and str(val).strip() not in ("", "--", "None", "null", "0", "0.0"):
                try:
                    pass_score = float(val)
                    break
                except Exception:
                    pass

        try:
            body_text = self.driver.execute_script(
                "return document.body ? document.body.innerText : '';"
            ) or ""
            try:
                iframe_text = self.driver.execute_script(
                    """
                    var f = document.querySelector('[name="submitTarget"], #submitTarget, iframe[name="submitTarget"]');
                    if (f && f.contentDocument) return f.contentDocument.body.innerText;
                    return '';
                    """
                )
                if iframe_text:
                    body_text += " " + iframe_text
            except Exception:
                pass

            # 擷取分數
            score_val, result_status = grade_evidence(body_text)
            score_str = f"【得分：{score_val} 分 / 門檻：{pass_score} 分】" if score_val is not None else f"【門檻：{pass_score} 分】"

            if score_val is not None:
                if grade_passed(score_val, pass_score) is True:
                    logger.info(f"   🎉 測驗結果：達標及格 {score_str}！")
                    passed = True
                    self._exam_fail_counts.pop(course_id, None)
                    # 🛡️ 只有獲得 100 分滿分時，才將整卷 AI 答案同步至題庫；部分及格不存庫，防止未滿分之錯誤答案污染
                    if _ai_answered and score_val >= 100.0:
                        if self._save_answers_to_db(_ai_answered, source="AI") is True:
                            logger.info(f"   💾 測驗獲得 100 分滿分，已將 {len(_ai_answered)} 題 AI 驗證解答正式同步至題庫")
                else:
                    self._exam_fail_counts[course_id] = self._exam_fail_counts.get(course_id, 0) + 1
                    fail_now = self._exam_fail_counts[course_id]
                    logger.warning(f"   ❌ 測驗結果：未達門檻 {score_str}（已累計未達標 {fail_now} 次）")
                    passed = False
            elif grade_passed(None, pass_score, result_status) is False:
                self._exam_fail_counts[course_id] = self._exam_fail_counts.get(course_id, 0) + 1
                fail_now = self._exam_fail_counts[course_id]
                logger.warning(f"   ❌ 測驗結果：不及格 / 未通過 {score_str}（已累計不及格 {fail_now} 次）")
                passed = False
            elif grade_passed(None, pass_score, result_status) is True:
                logger.info(f"   🎉 測驗結果：及格 / 通過 {score_str}！")
                passed = True
                self._exam_fail_counts.pop(course_id, None)
            elif main_window and self._check_exam_passed_via_s_main(main_window):
                logger.info(f"   🎉 測驗結果：平臺測驗清單已確認通過 {score_str}！")
                passed = True
                self._exam_fail_counts.pop(course_id, None)
            else:
                logger.info(f"   📝 測驗已送出 {score_str}（請至學習紀錄查核狀態）")
                self._last_exam_score_unknown = True
                passed = False
        except Exception as e:
            logger.debug(f"讀取測驗成績失敗: {e}")
            self._last_exam_score_unknown = True
            passed = False

        if self._last_exam_score_unknown:
            self._mark_exam_manual_review(course, "已交卷但成績未知，停止自動重考，請查核平臺紀錄")
        return passed

    def _count_session_quiz_course(self, course_id):
        courses = self.__dict__.setdefault("_session_quiz_courses", set())
        courses.add(course_id)
        self._session_quiz_total_count = len(courses)

    def _defer_exam_after_ai_outage(self, course):
        """AI 服務暫時中斷（503／逾時）造成的不及格：不計入 3 次上限，冷卻後再考；每門最多寬限 3 次。"""
        if not getattr(self, "_last_exam_ai_outage", False):
            return False
        c_id = str(course.get("course_id", ""))
        outages = self.__dict__.setdefault("_exam_ai_outages", {})
        if outages.get(c_id, 0) >= EXAM_AI_OUTAGE_MAX_DEFERS:
            if callable(getattr(self, '_mark_exam_manual_review', None)):
                self._mark_exam_manual_review(course, 'AI 多次無法回應，保留草稿，請稍後重新執行')
            return False
        outages[c_id] = outages.get(c_id, 0) + 1
        if getattr(self, '_last_exam_submitted', True) and self._exam_fail_counts.get(c_id, 0) > 0:
            self._exam_fail_counts[c_id] -= 1
        self.__dict__.setdefault("_exam_retry_after", {})[c_id] = time.time() + EXAM_AI_OUTAGE_DEFER_SECONDS
        logger.warning(
            f"   ⏸️ 「{course.get('caption', c_id)}」因 AI 服務暫時無法回應而未及格，不計入 3 次上限；"
            f"{EXAM_AI_OUTAGE_DEFER_SECONDS // 60} 分鐘後再重考（寬限 {outages[c_id]}/{EXAM_AI_OUTAGE_MAX_DEFERS}）"
        )
        return True

    def _apply_interactive_exam_answers(self, course, rows, answers):
        """回貼必須涵蓋所有題目，不能以先前殘留的勾選填補缺答。"""
        if set(answers) != set(range(1, len(rows) + 1)):
            self._mark_exam_manual_review(course, '人機協同回貼缺題，停止交卷')
            return False
        for q_idx, row in enumerate(rows):
            q_num = q_idx + 1
            if q_num not in answers:
                continue
            selected_labels = answers[q_num]

            radios = row.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            checkboxes = row.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            inputs = checkboxes if checkboxes else radios

            expected = {str(label).upper() for label in selected_labels}
            for opt_idx, control in enumerate(inputs):
                want = chr(65 + opt_idx) in expected
                checked = bool(self.driver.execute_script('return arguments[0].checked;', control))
                if want != checked and (checkboxes or want):
                    self.driver.execute_script('arguments[0].click();', control)
            actual = {chr(65 + i) for i, control in enumerate(inputs)
                      if self.driver.execute_script('return arguments[0].checked;', control) is True}
            if not expected or actual != expected:
                self._mark_exam_manual_review(course, '人機協同答案未完整勾選，停止交卷')
                return False

        return self._verify_exam_ready(course, rows)

    def _verify_exam_ready(self, course, rows):
        """雙平臺採相同完整性門檻；e 等依每個題目列讀回勾選狀態。"""
        counts = self.driver.execute_script("""
            var rows = arguments[0];
            var answered = rows.filter(row => row.querySelector('input[type=radio]:checked, input[type=checkbox]:checked')).length;
            return {total: rows.length, answered: answered};
        """, rows)
        ready = isinstance(counts, dict) and can_submit(counts.get('total', 0), counts.get('answered', 0), expected_total=len(rows))
        if not ready:
            self._mark_exam_manual_review(course, '仍有未填答或無法讀取的題目，保留草稿，禁止交卷')
        return ready

    def _click_course_entry(self, *, include_exam=False, allow_enrollment=False):
        """依序處理確認、報名與上課入口；最多四步，原生 Alert 留給呼叫端處理。"""
        script = ("const includeExam = arguments[0];\n"
                  "const includeEnrollment = arguments[1];\n" + _COURSE_ENTRY_SCRIPT)
        for _ in range(4):
            if not self.running:
                return None
            before_url = self.driver.current_url
            before_handles = set(self.driver.window_handles)
            action = self.driver.execute_script(script, include_exam, allow_enrollment)
            if not action:
                return None
            if action['kind'] == 'entry':
                return action['label']
            logger.info(f"   📝 已點擊「{action['label']}」，繼續確認上課入口")
            if not self.safe_sleep(1):
                return None
            try:
                if set(self.driver.window_handles) - before_handles:
                    return action['label']
                current_url = self.driver.current_url
                if current_url != before_url and '/info/' not in current_url:
                    return action['label']
            except UnexpectedAlertPresentException:
                return action['label']
        return None

    def auto_exam(self, course):
        """累積同一課程各輪測驗用量，包含不及格或中斷的嘗試。"""
        from utils.security import global_quota_tracker

        totals = self.__dict__.setdefault('_course_api_calls', {})
        course_id = str(course.get('course_id', ''))
        try:
            before = global_quota_tracker.get_stats()
        except Exception:
            before = None
        try:
            return self._auto_exam_attempt(course)
        finally:
            if before is not None:
                try:
                    after = global_quota_tracker.get_stats()
                    delta = after['used'] - before['used'] if after['date'] == before['date'] else after['used']
                    totals[course_id] = totals.get(course_id, 0) + max(0, delta)
                except Exception as exc:
                    logger.debug(f'測驗用量統計失敗，不影響測驗結果：{exc}')

    def _wait_s_main_action_or_status(
        self,
        *,
        done_keywords: tuple[str, ...],
        none_keywords: tuple[str, ...],
        timeout: float = 12.0,
    ) -> tuple[str, object | None]:
        """切換至 s_main（或主頁）並輪詢等待「已完成／無項目／可點擊按鈕」出現。"""
        deadline = time.time() + max(1.0, float(timeout))
        while time.time() <= deadline:
            if not getattr(self, "running", True):
                return "stopped", None
            try:
                self.driver.switch_to.default_content()
                try:
                    self.driver.switch_to.frame("s_main")
                except Exception:
                    pass

                for el in self.driver.find_elements(By.CSS_SELECTOR, "div.process-btn"):
                    try:
                        txt = (el.text or "").strip()
                    except Exception:
                        txt = ""
                    if txt and any(kw in txt for kw in done_keywords):
                        return "done", None

                for btn in self.driver.find_elements(By.CSS_SELECTOR, "div.process-btn.pay.active"):
                    try:
                        if btn.is_displayed():
                            return "button", btn
                    except Exception:
                        return "button", btn

                body_text = ""
                try:
                    body_text = self.driver.execute_script(
                        "return document.body ? document.body.innerText : '';"
                    ) or ""
                except Exception:
                    pass
                if any(kw in body_text for kw in done_keywords):
                    return "done", None
                if any(kw in body_text for kw in none_keywords):
                    return "none", None
            except Exception:
                pass
            time.sleep(0.4)
        return "timeout", None

    def _auto_exam_attempt(self, course):
        """時數達標後，自動進入測驗並作答。回傳 True=通過, False=未通過/失敗"""
        self._last_exam_ai_outage = False
        self._last_exam_submitted = False
        ai_keys = self.config.get("ai_keys", {})
        ai_keys = ai_keys if isinstance(ai_keys, dict) else {}
        ai_provider = self.config.get("ai_provider", "Gemini")
        has_api_key = bool(ai_keys.get(ai_provider) or self.config.get("ai_api_key", ""))
        ai_auto_solve = bool(self.config.get("ai_auto_solve", False))
        ai_enabled = has_api_key and ai_auto_solve

        if (
            not self.config.get("interactive_quiz_for_session")
            and not self._answer_map
            and not self.answers
            and not ai_enabled
        ):
            logger.info("   📝 未設定題庫或 AI，且未啟用人機協同模式，跳過自動作答")
            self._mark_exam_manual_review(course, '未設定有效題庫、AI 或人機協同，停止自動作答')
            return False

        course_id = str(course.get("course_id", ""))

        # 不及格超過 3 次，跳過此課程
        fail_count = self._exam_fail_counts.get(course_id, 0)
        if fail_count >= MAX_QUIZ_ATTEMPTS:
            self._mark_exam_manual_review(course, '測驗未及格已達三次上限，請人工確認')
            logger.warning(
                f"   ⚠️ 課程「{course.get('caption', course_id)}」已不及格 {fail_count} 次，跳過，請使用者自行完成測驗"
            )
            return False

        logger.info("   📝 開始自動作答流程...")
        # 收集本場 AI 補答的題目，考試通過後寫入 db
        _ai_answered = {}
        # 僅在已啟用 AI 且重測時才以 AI 覆核；否則維持純題庫模式。
        if not ai_enabled:
            if not has_api_key:
                logger.info("   📚 未設定 API Key，啟用純題庫模式，不呼叫 AI。")
            else:
                logger.info("   📚 本次採用 SQLite 題庫秒殺模式，不呼叫 AI（0 耗額）。")

        # 以「目前所在視窗」為課程教室主視窗（不論從哪條路徑進入）
        main_window = self.driver.current_window_handle

        try:
            # ── 1. 切回教室主視窗，點左側 sidebar「測驗/考試」──
            # sidebar 在 mooc_sysbar frame（<frame name="mooc_sysbar">）
            self.driver.switch_to.window(main_window)
            self.driver.switch_to.default_content()

            # 💡 若仍在 /info/ 課程介紹頁面，先檢查是否已通過，或點擊「上課去」進入教室介面
            if "/info/" in self.driver.current_url:
                try:
                    info_text = (
                        self.driver.execute_script(
                            "return document.body ? document.body.innerText : '';"
                        )
                        or ""
                    )
                    if (
                        "通過狀態" in info_text
                        and "已通過" in info_text
                        and ("測驗" in info_text and ("100" in info_text or "及格" in info_text))
                    ) or self._is_course_already_completed_on_info_page():
                        logger.info(
                            f"   🎉 課程「{course.get('caption', '')}」平臺顯示測驗已通過／已完成，免再次測驗。"
                        )
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        return True

                    clicked_in = self._click_course_entry(include_exam=True)
                    if clicked_in:
                        logger.info(f"   📝 已點擊「{clicked_in}」進入教室/測驗介面")
                        time.sleep(4)
                        if len(self.driver.window_handles) > 1:
                            main_window = self.driver.window_handles[-1]
                            self.driver.switch_to.window(main_window)
                            self._auto_hide_popups_if_needed(settle=True)
                except Exception:
                    pass

            clicked_exam = False
            try:
                self.driver.switch_to.frame("mooc_sysbar")
                exam_link = self.driver.find_element(
                    By.CSS_SELECTOR, "a[href*='exam/exam_list.php'], a[href*='exam']"
                )
                self.driver.execute_script("arguments[0].click();", exam_link)
                self._auto_hide_popups_if_needed(settle=True)
                logger.info("   📝 已點擊「測驗/考試」")
                clicked_exam = True
            except Exception:
                pass

            if not clicked_exam:
                self.driver.switch_to.default_content()
                try:
                    exam_btn = self.driver.find_element(
                        By.CSS_SELECTOR,
                        "a[href*='exam_list'], a[href*='exam'], button[onclick*='exam'], a[onclick*='exam'], .btn-warning, a.btn[href*='quiz'], input[value*='測驗'], input[value*='認證'], a.btn[href*='cert']"
                    )
                    self.driver.execute_script("arguments[0].click();", exam_btn)
                    self._auto_hide_popups_if_needed(settle=True)
                    logger.info("   📝 已從主頁面點擊「測驗/認證」")
                    clicked_exam = True
                except Exception as e:
                    logger.warning(f"   ⚠️ 找不到測驗連結（可能為平台已下架或無測驗介面課程）: {e}")
                    self._mark_exam_manual_review(course, "找不到測驗入口，尚未確認測驗已通過")
                    return False

            # ── 2 & 3. 切到 s_main 並等待測驗狀態／「進行測驗」按鈕載入完成 ──
            status, pay_btn = self._wait_s_main_action_or_status(
                done_keywords=("已通過", "已選擇公布答案"),
                none_keywords=("目前沒有任何測驗", "尚無測驗", "無測驗資料", "沒有測驗"),
                timeout=12.0,
            )
            if status == "stopped":
                return False
            if status == "done":
                logger.info("   ✅ 測驗已通過（先前已完成），跳過作答")
                return True
            if status == "none":
                logger.info("   ℹ️ 測驗清單顯示目前無測驗項目，跳過作答")
                return True
            if status != "button" or not pay_btn:
                entry_fails = self.__dict__.setdefault("_exam_entry_fail_counts", {})
                entry_fails[course_id] = entry_fails.get(course_id, 0) + 1
                logger.warning(
                    f"   ⚠️ 找不到「進行測驗」按鈕（等待 s_main 逾時，第 {entry_fails[course_id]} 次）"
                )
                if entry_fails[course_id] >= 2:
                    self._mark_exam_manual_review(
                        course, "找不到「進行測驗」按鈕（頁面未載入或版面不符）"
                    )
                return False

            try:
                self.driver.execute_script("arguments[0].click();", pay_btn)
                self._auto_hide_popups_if_needed(settle=True)
                logger.info("   📝 已點擊「進行測驗」")
            except Exception as e:
                err_line = (getattr(e, "msg", None) or str(e)).splitlines()[0]
                logger.warning(f"   ⚠️ 點擊「進行測驗」按鈕失敗: {err_line}")
                return False

            time.sleep(3)

            # ── 4. 切換到新跳出的考試視窗 ──
            all_handles = self.driver.window_handles
            exam_window = next((h for h in all_handles if h != main_window), None)
            if not exam_window:
                logger.warning("   ⚠️ 未偵測到考試視窗")
                return False

            self.driver.switch_to.window(exam_window)
            self._auto_hide_popups_if_needed(settle=True)
            logger.info("   📝 已切換至考試視窗")

            # 等待考試頁面載入完成（最多 15 秒）
            try:
                WebDriverWait(self.driver, 15).until(
                    lambda d: d.execute_script(
                        'var inputs = document.querySelectorAll(\'input[type="button"], input[type="submit"]\');'
                        "for(var i=0;i<inputs.length;i++){var v=inputs[i].value||''; if(v.indexOf('\u958b\u59cb')!==-1||v.indexOf('\u4f5c\u7b54')!==-1) return true;}"
                        "return inputs.length > 0;"
                    )
                )
            except Exception:
                # timeout 了，繼續往下嘗試（舊版 fallback）
                pass

            # 記錄 exam_start URL（含 course_id+attempt+token）供步驟10推算 view_result URL
            exam_start_url = self.driver.current_url

            # ── 5. 點「開始作答」 ──
            # 用 JS 點擊（避免 StaleElementReferenceException）
            # 頁面有 type=button 的「開始作答」，是第一個 input[type=button]
            try:
                clicked = self.driver.execute_script(
                    """
                    var inputs = document.querySelectorAll('input');
                    for (var i = 0; i < inputs.length; i++) {
                        var v = inputs[i].value || '';
                        // 「開始作答」Unicode: \u958b\u59cb\u4f5c\u7b54
                        if (v.indexOf('\u958b\u59cb') !== -1) {
                            inputs[i].click();
                            return v;
                        }
                    }
                    // fallback：點第一個 type=button
                    var btn = document.querySelector('input[type="button"]');
                    if (btn) { btn.click(); return btn.value; }
                    return null;
                    """
                )
                if clicked:
                    logger.info(f"   📝 已點擊開始按鈕：{clicked!r}")
                else:
                    logger.warning("   ⚠️ 找不到開始作答按鈕")
                    return False
            except Exception as e:
                logger.warning(f"   ⚠️ 點擊開始作答失敗: {e}")
                return False

            time.sleep(2)

            # ── 6. 逐題作答 ──
            answered = 0
            skipped = 0
            _missing = []  # 題庫無答案的題目，考試後回報 GAS

            rows = self.driver.find_elements(
                By.CSS_SELECTOR, "tr.bg03.font01, tr.bg04.font01"
            )

            # ── DOM 診斷（首次執行時印出） ──
            try:
                iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                frames = self.driver.find_elements(By.TAG_NAME, "frame")
                logger.debug(
                    f"   [DOM] iframe 數量: {len(iframes)}, frame 數量: {len(frames)}"
                )
                logger.debug(
                    f"   [DOM] iframe names: {[f.get_attribute('name') or f.get_attribute('id') or '?' for f in iframes]}"
                )
                logger.debug(f"   [DOM] rows 數量: {len(rows)}")
                if rows:
                    first_html = self.driver.execute_script(
                        "return arguments[0].outerHTML;", rows[0]
                    )
                    logger.debug(
                        f"   [DOM] 第一個row HTML (前1000字): {first_html[:1000]}"
                    )
                else:
                    # rows 為空，印出整個 table body 的 HTML 幫助診斷
                    page_sample = self.driver.execute_script(
                        "var t = document.querySelector('table'); return t ? t.outerHTML.substring(0,2000) : document.body.innerHTML.substring(0,2000);"
                    )
                    logger.debug(
                        f"   [DOM] rows 為空，頁面 table HTML (前2000字): {page_sample}"
                    )
            except Exception as _dom_e:
                logger.debug(f"   [DOM] 診斷略過: {_dom_e}")

            # ── 6a. 檢查是否啟用人機協同作答助理（彈窗複製題目／回貼答案） ──
            if self.config.get("interactive_quiz_for_session") and self.quiz_interactive_callback:
                questions_data = []
                for q_idx, row in enumerate(rows):
                    try:
                        q_text = (
                            self.driver.execute_script(
                                """
                            var tds = arguments[0].querySelectorAll('td');
                            var td = null;
                            for (var j = 0; j < tds.length; j++) {
                                if (tds[j].querySelector('ol, ul, input')) {
                                    td = tds[j];
                                    break;
                                }
                            }
                            if (!td) {
                                var candidates = arguments[0].querySelectorAll('td[align="left"]');
                                for (var k = 0; k < candidates.length; k++) {
                                    if (!candidates[k].hasAttribute('nowrap')) {
                                        td = candidates[k];
                                        break;
                                    }
                                }
                            }
                            if (!td) td = arguments[0].querySelector('td');
                            if (!td) return '';
                            var text = '';
                            for (var i = 0; i < td.childNodes.length; i++) {
                                var n = td.childNodes[i];
                                if (n.nodeType === 3) {
                                    text += n.textContent;
                                } else if (n.nodeName === 'P' || n.nodeName === 'STRONG' || n.nodeName === 'SPAN') {
                                    text += n.innerText || n.textContent;
                                    break;
                                } else if (n.nodeName === 'OL' || n.nodeName === 'UL') {
                                    break;
                                }
                            }
                            text = text.trim();
                            text = text.replace(/^[\\d]+[.\\s]+/, '').trim();
                            return text;
                            """,
                                row,
                            )
                            or ""
                        )
                        if not q_text:
                            try:
                                q_el = row.find_element(By.TAG_NAME, "p")
                                q_text = q_el.text.strip()
                            except Exception:
                                q_text = row.text.strip().split("\n")[0]

                        opt_texts = (
                            self.driver.execute_script(
                                """
                            var tds = arguments[0].querySelectorAll('td');
                            var td = null;
                            for (var j = 0; j < tds.length; j++) {
                                if (tds[j].querySelector('ol, ul, input')) {
                                    td = tds[j];
                                    break;
                                }
                            }
                            if (!td) {
                                var candidates = arguments[0].querySelectorAll('td[align="left"]');
                                for (var k = 0; k < candidates.length; k++) {
                                    if (!candidates[k].hasAttribute('nowrap')) {
                                        td = candidates[k];
                                        break;
                                    }
                                }
                            }
                            if (!td) td = arguments[0].querySelector('td');
                            if (!td) return [];
                            var items = td.querySelectorAll('ol li, ul li');
                            var texts = [];
                            for (var i = 0; i < items.length; i++) {
                                var clone = items[i].cloneNode(true);
                                var removeNodes = clone.querySelectorAll('input, script, style');
                                for (var r = 0; r < removeNodes.length; r++) {
                                    removeNodes[r].remove();
                                }
                                texts.push((clone.textContent || '').replace(/\\s+/g, ' ').trim());
                            }
                            if (texts.length === 0) {
                                var choiceInputs = td.querySelectorAll('input[type="radio"], input[type="checkbox"]');
                                for (var c = 0; c < choiceInputs.length; c++) {
                                    var inp = choiceInputs[c];
                                    var labelText = '';
                                    if (inp.id) {
                                        var lbl = td.querySelector('label[for="' + inp.id.replace(/"/g, '\\"') + '"]');
                                        if (lbl) labelText = (lbl.textContent || '').trim();
                                    }
                                    if (!labelText && inp.parentElement && inp.parentElement.tagName === 'LABEL') {
                                        var pClone = inp.parentElement.cloneNode(true);
                                        var pInps = pClone.querySelectorAll('input, script, style');
                                        for (var p = 0; p < pInps.length; p++) pInps[p].remove();
                                        labelText = (pClone.textContent || '').trim();
                                    }
                                    if (!labelText) {
                                        var sib = inp.nextSibling;
                                        while (sib && sib.nodeName !== 'INPUT' && sib.nodeName !== 'BR') {
                                            labelText += (sib.textContent || '');
                                            sib = sib.nextSibling;
                                        }
                                        labelText = labelText.trim();
                                    }
                                    texts.push(labelText.replace(/\\s+/g, ' ').trim());
                                }
                            }
                            return texts;
                            """,
                                row,
                            )
                            or []
                        )

                        radios = row.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                        checkboxes = row.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
                        is_multiple = len(checkboxes) > 0
                        q_type = "多選" if is_multiple else ("是非" if len(radios) == 2 else "單選")

                        options = []
                        if opt_texts:
                            for o_idx, ot in enumerate(opt_texts):
                                label = chr(65 + o_idx)
                                options.append({"label": label, "text": ot})
                        elif len(radios) == 2:
                            options = [
                                {"label": "A", "text": "⭕ (是/正確)"},
                                {"label": "B", "text": "❌ (否/錯誤)"},
                            ]
                        else:
                            count = len(radios) or len(checkboxes)
                            for o_idx in range(count):
                                label = chr(65 + o_idx)
                                options.append({"label": label, "text": f"選項 {label}"})

                        questions_data.append({
                            "index": q_idx + 1,
                            "type": q_type,
                            "q_text": q_text,
                            "options": options,
                            "is_multiple": is_multiple,
                        })
                    except Exception as e:
                        logger.debug(f"萃取題目 {q_idx + 1} 失敗: {e}")

                if questions_data:
                    logger.info(f"   📝 正在啟動「人機協同作答助理」互動視窗（{INTERACTIVE_QUIZ_TIMEOUT_SECONDS} 秒倒數）...")
                    interactive_ans_map = self.quiz_interactive_callback(
                        course.get("caption", "公務員測驗"),
                        questions_data,
                        timeout_sec=INTERACTIVE_QUIZ_TIMEOUT_SECONDS,
                    )

                    if isinstance(interactive_ans_map, dict) and interactive_ans_map:
                        logger.info(
                            f"   🚀 已收到回貼答案（共 {len(interactive_ans_map)} 題），正在自動勾選網頁選項..."
                        )
                        if not self._apply_interactive_exam_answers(course, rows, interactive_ans_map):
                            return False
                        logger.info("   ✅ 選項勾選與完整性驗證完成，正在送出考卷...")
                        time.sleep(1)
                        try:
                            self.driver.execute_script(
                                """
                                var btns = document.querySelectorAll('input[type="submit"]');
                                for (var i = 0; i < btns.length; i++) {
                                    var b = btns[i];
                                    var formName = b.form ? (b.form.name || b.form.id || '') : '';
                                    if (formName === 'responseForm') {
                                        b.click();
                                        return true;
                                    }
                                }
                                if (btns.length > 0) { btns[0].click(); return true; }
                                return false;
                                """
                            )
                        except Exception:
                            pass

                        time.sleep(1)
                        self._accept_alert()
                        self._last_exam_submitted = True
                        passed = self._read_exam_result(course, main_window=main_window)
                        # 人機協同答案只用於本次作答，不寫回本機題庫。
                        if not passed and not getattr(self, "_last_exam_score_unknown", False):
                            time.sleep(1)
                            try:
                                cur_exam_url = self.driver.current_url
                                if "view_result" in cur_exam_url:
                                    self._harvest_correct_answers(cur_exam_url)
                            except Exception:
                                pass
                        try:
                            self.driver.switch_to.window(main_window)
                        except Exception:
                            pass
                        return passed
                    elif interactive_ans_map == "STOP_ALL":
                        logger.info("🛑 使用者於測驗逾時對話框選擇【結束本次執行】。")
                        self.running = False
                        try:
                            self.driver.close()
                            self.driver.switch_to.window(main_window)
                        except Exception:
                            pass
                        return False
                    elif interactive_ans_map == "DIALOG_ERROR":
                        self._mark_exam_manual_review(
                            course, "人機協同測驗視窗無法顯示，尚未執行跳過指令"
                        )
                        try:
                            self.driver.close()
                            self.driver.switch_to.window(main_window)
                        except Exception:
                            pass
                        return False
                    else:
                        logger.info(f"   ⏩ 使用者選擇跳過課程【{course.get('caption', '')}】之測驗，繼續下一門。")
                        try:
                            self.driver.close()
                            self.driver.switch_to.window(main_window)
                        except Exception:
                            pass
                        return False

            def _parse_multiple_choice_answers(raw_ans, num_options=4):
                """將各類多選答案（如 'A,B,C'、'A、B、C'、'A B C'、'ABCD'、'1,2,3'、'1 2 3'、['A','B']）
                標準化為大寫字母清單（如 ['A', 'B', 'C']）。"""
                if not raw_ans:
                    return []
                if isinstance(raw_ans, list):
                    items = []
                    for it in raw_ans:
                        items.extend(_parse_multiple_choice_answers(it, num_options))
                    return sorted(list(dict.fromkeys(items)))
                text = str(raw_ans).strip()
                if not text:
                    return []
                # 排除「以上皆是」等非直接選項符號
                # 先以逗號、頓號、分號、斜線、空白切分
                parts = [p.strip() for p in re.split(r'[,，、;\s/]+', text) if p.strip()]
                res = []
                for p in parts:
                    # 若為連寫字母（例如 "ABCD" 或 "ABC" 或 "CD"）
                    if re.fullmatch(r'[A-Za-z]+', p) and len(p) > 1:
                        for ch in p.upper():
                            res.append(ch)
                    # 單一字母（如 "A", "B"）
                    elif re.fullmatch(r'[A-Za-z]', p):
                        res.append(p.upper())
                    # 數字（1-based 如 1,2,3,4 或 0-based 如 0,1,2,3）
                    elif p.isdigit():
                        val_int = int(p)
                        # 優先以 1-based (1->A, 2->B...)
                        if 1 <= val_int <= num_options:
                            res.append(chr(ord('A') + val_int - 1))
                        elif val_int == 0 and num_options > 0:
                            res.append('A')
                        elif 0 <= val_int < num_options:
                            res.append(chr(ord('A') + val_int))
                    else:
                        # 包含括號如 (A)、[A] 等
                        m_ch = re.findall(r'[A-Za-z]', p)
                        if m_ch:
                            for ch in m_ch:
                                res.append(ch.upper())
                return sorted(list(dict.fromkeys(res)))

            parsed_items = []
            for q_idx, row in enumerate(rows):
                try:
                    # ── 題目文字擷取 ──
                    try:
                        q_text = (
                            self.driver.execute_script(
                                """
                            var tds = arguments[0].querySelectorAll('td');
                            var td = null;
                            for (var j = 0; j < tds.length; j++) {
                                if (tds[j].querySelector('ol, ul, input')) {
                                    td = tds[j];
                                    break;
                                }
                            }
                            if (!td) {
                                var candidates = arguments[0].querySelectorAll('td[align="left"]');
                                for (var k = 0; k < candidates.length; k++) {
                                    if (!candidates[k].hasAttribute('nowrap')) {
                                        td = candidates[k];
                                        break;
                                    }
                                }
                            }
                            if (!td) td = arguments[0].querySelector('td');
                            if (!td) return '';
                            var text = '';
                            for (var i = 0; i < td.childNodes.length; i++) {
                                var n = td.childNodes[i];
                                if (n.nodeType === 3) {
                                    text += n.textContent;
                                } else if (n.nodeName === 'P' || n.nodeName === 'STRONG' || n.nodeName === 'SPAN') {
                                    text += n.innerText || n.textContent;
                                    break;
                                } else if (n.nodeName === 'OL' || n.nodeName === 'UL') {
                                    break;
                                }
                            }
                            text = text.trim();
                            text = text.replace(/^[\\d]+[.\\s]+/, '').trim();
                            return text;
                            """,
                                row,
                            )
                            or ""
                        )
                    except Exception:
                        q_text = ""
                    if not q_text:
                        try:
                            q_el = row.find_element(By.TAG_NAME, "p")
                            q_text = q_el.text.strip()
                        except Exception:
                            q_text = row.text.strip().split("\n")[0]

                    radios = row.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                    checkboxes = row.find_elements(
                        By.CSS_SELECTOR, "input[type='checkbox']"
                    )
                    ans = self._find_answer(
                        q_text, num_options=len(checkboxes or radios)
                    )

                    try:
                        option_texts = (
                            self.driver.execute_script(
                                """
                            var tds = arguments[0].querySelectorAll('td');
                            var td = null;
                            for (var j = 0; j < tds.length; j++) {
                                if (tds[j].querySelector('ol, ul, input')) {
                                    td = tds[j];
                                    break;
                                }
                            }
                            if (!td) {
                                var candidates = arguments[0].querySelectorAll('td[align="left"]');
                                for (var k = 0; k < candidates.length; k++) {
                                    if (!candidates[k].hasAttribute('nowrap')) {
                                        td = candidates[k];
                                        break;
                                    }
                                }
                            }
                            if (!td) td = arguments[0].querySelector('td');
                            if (!td) return [];
                            var items = td.querySelectorAll('ol li, ul li');
                            var texts = [];
                            for (var i = 0; i < items.length; i++) {
                                var clone = items[i].cloneNode(true);
                                var removeNodes = clone.querySelectorAll('input, script, style');
                                for (var r = 0; r < removeNodes.length; r++) {
                                    removeNodes[r].remove();
                                }
                                texts.push((clone.textContent || '').replace(/\\s+/g, ' ').trim());
                            }
                            if (texts.length === 0) {
                                var choiceInputs = td.querySelectorAll('input[type="radio"], input[type="checkbox"]');
                                for (var c = 0; c < choiceInputs.length; c++) {
                                    var inp = choiceInputs[c];
                                    var labelText = '';
                                    if (inp.id) {
                                        var lbl = td.querySelector('label[for="' + inp.id.replace(/"/g, '\\"') + '"]');
                                        if (lbl) labelText = (lbl.textContent || '').trim();
                                    }
                                    if (!labelText && inp.parentElement && inp.parentElement.tagName === 'LABEL') {
                                        var pClone = inp.parentElement.cloneNode(true);
                                        var pInps = pClone.querySelectorAll('input, script, style');
                                        for (var p = 0; p < pInps.length; p++) pInps[p].remove();
                                        labelText = (pClone.textContent || '').trim();
                                    }
                                    if (!labelText) {
                                        var sib = inp.nextSibling;
                                        while (sib && sib.nodeName !== 'INPUT' && sib.nodeName !== 'BR') {
                                            labelText += (sib.textContent || '');
                                            sib = sib.nextSibling;
                                        }
                                        labelText = labelText.trim();
                                    }
                                    texts.push(labelText.replace(/\\s+/g, ' ').trim());
                                }
                            }
                            return texts;
                            """,
                                row,
                            )
                            or []
                        )
                    except Exception:
                        option_texts = []

                    parsed_items.append({
                        "idx": q_idx,
                        "row": row,
                        "q_text": q_text,
                        "option_texts": option_texts,
                        "radios": radios,
                        "checkboxes": checkboxes,
                        "ans": ans,
                        "ans_source": "題庫" if ans is not None else None,
                    })
                except Exception as e:
                    logger.warning(f"   ⚠️ 解析第 {q_idx + 1} 題失敗：{e}")

            # 🛡️ 送 AI 批次前先預驗題庫答案是否真能對上當前頁面選項；
            # 若題庫命中舊格式或選項已改寫導致對不上，清空 ans 改由 AI 批次補答（不靜默略過）。
            for item in parsed_items:
                if item["ans"] is not None and not _can_resolve_exam_answer(
                    item["ans"],
                    item["option_texts"],
                    len(item["radios"]),
                    len(item["checkboxes"]),
                ):
                    logger.warning(
                        f"   ⚠️ 第 {item['idx'] + 1} 題題庫答案（{str(item['ans'])[:30]!r}）無法對應目前選項（選項數={len(item['checkboxes'] or item['radios'])}），改由 AI 覆核"
                    )
                    item["ans"] = None
                    item["ans_source"] = None

            # ⚡ 10 題合一整卷 AI 批次作答（僅發送 1 次 API 請求，節省 90% 額度）
            items_needing_ai = [item for item in parsed_items if needs_ai_review(item['ans'], fail_count if ai_enabled else 0)]
            if ai_enabled and items_needing_ai:
                batch_questions = []
                opt_labels = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]
                for item in items_needing_ai:
                    opts_list = []
                    radios_count = len(item["radios"])
                    ai_options = item["option_texts"] if any(item["option_texts"]) else (
                        ["正確（是）", "錯誤（否）"] if radios_count == 2 else []
                    )
                    for o_idx, o_txt in enumerate(ai_options):
                        label = opt_labels[o_idx] if o_idx < len(opt_labels) else str(o_idx + 1)
                        opts_list.append({"label": label, "text": o_txt, "val": str(o_idx + 1)})

                    is_tf = len(opts_list) == 2 and any(k in item["q_text"] or k in "".join(o["text"] for o in opts_list) for k in ["是非", "是否", "對錯", "○", "╳", "⭕", "❌"])
                    q_type = "是非" if is_tf else ("多選" if item["checkboxes"] else "單選")
                    batch_questions.append({
                        "index": item["idx"] + 1,
                        "name": f"q_{item['idx'] + 1}",
                        "type": q_type,
                        "is_multiple": bool(item["checkboxes"]),
                        "q_text": item["q_text"],
                        "options": opts_list,
                        "raw_item": item,
                    })

                try:
                    from quiz_bank import ai_batch_solve_quiz
                    for item in items_needing_ai:
                        item['ans'] = None
                    batch_res = ai_batch_solve_quiz(course.get('caption', 'e等公務員測驗'), batch_questions, self.config)
                    if batch_res.get("success") and batch_res.get("parsed_answers"):
                        for b_q in batch_questions:
                            q_num = str(b_q["index"])
                            ans_choice = batch_res['parsed_answers'].get(b_q['name'])
                            if ans_choice:
                                item = b_q["raw_item"]
                                matched_opt = next((o for o in b_q["options"] if o["label"].upper() == str(ans_choice).upper() or o["val"] == str(ans_choice)), None)
                                if matched_opt:
                                    item["ans"] = matched_opt["val"]
                                    # 🛡️ 軌道 B：滿分存庫優先儲存標準選項文字（若有），徹底抗選項隨機重排
                                    opt_text = (matched_opt.get("text") or "").strip()
                                    _ai_answered[item["q_text"]] = opt_text if opt_text else matched_opt["val"]
                                else:
                                    item["ans"] = ans_choice
                                    texts = [o['text'] for o in b_q['options'] if o['val'] in ans_choice] if isinstance(ans_choice, list) else []
                                    _ai_answered[item["q_text"]] = json.dumps(texts, ensure_ascii=False) if texts else str(ans_choice)
                                item["ans_source"] = "AI"
                                logger.info(f"   🤖 AI 批次解答 [{q_num}/{len(rows)} 題]：{item['ans']!r}")
                    else:
                        self._last_exam_ai_outage = bool(batch_res.get("transient"))
                        logger.warning(f"   ⚠️ AI 批次作答未取得有效答案：{batch_res.get('error')}；保留草稿，不猜答或交卷")
                except Exception as batch_err:
                    logger.warning(f"   ⚠️ AI 批次作答異常：{batch_err}；保留草稿，不猜答或交卷")

            if len(parsed_items) != len(rows) or any(item['ans'] is None for item in parsed_items):
                if not self._last_exam_ai_outage:
                    self._mark_exam_manual_review(course, '題目未完整解析或仍缺有效答案，保留草稿，禁止交卷')
                return False

            for item in parsed_items:
                q_idx = item["idx"]
                row = item["row"]
                q_text = item["q_text"]
                option_texts = item["option_texts"]
                radios = item["radios"]
                checkboxes = item["checkboxes"]
                ans = item["ans"]
                ans_source = item.get("ans_source")

                try:
                    logger.debug(f"   題目: {q_text[:50]!r}")
                    logger.debug(f"   選項: {[t[:20] for t in option_texts]!r}")
                    logger.debug(f"   答案: {ans!r}")

                    if checkboxes:
                        n = len(checkboxes)
                        if ans is not None:
                            ans_text = (
                                ans
                                if isinstance(ans, str)
                                else (ans[0] if isinstance(ans, list) else str(ans))
                            )
                            ans_norm = ans_text.strip()
                            ALL_ABOVE_PATTERNS = [
                                "以上皆是",
                                "以上皆可",
                                "以上皆正確",
                                "以上皆對",
                                "all of the above",
                                "ll of the above",
                            ]
                            is_all_above = any(
                                p in ans_norm for p in ALL_ABOVE_PATTERNS
                            )

                            if is_all_above:
                                expected_letters = [chr(ord('A') + i) for i in range(n)]
                            else:
                                expected_letters = answer_values(ans, {chr(65 + i): text for i, text in enumerate(option_texts[:n])}, multiple=True)
                                if not expected_letters:
                                    expected_letters = _parse_multiple_choice_answers(ans, num_options=n)

                            # 若未直接解析出字母且有選項文字，透過選項文字雙向包含反推
                            if not expected_letters and option_texts:
                                for i, opt_t in enumerate(option_texts[:n]):
                                    opt_clean = (opt_t or "").strip()
                                    if opt_clean and (opt_clean in ans_norm or ans_norm in opt_clean):
                                        expected_letters.append(chr(ord('A') + i))
                                expected_letters = sorted(list(set(expected_letters)))

                            valid_letters = {chr(ord('A') + i) for i in range(n)}
                            expected_set = {ch for ch in expected_letters if ch in valid_letters}

                            # 在該題自己的 checkbox group 內逐一勾選
                            for i, cb in enumerate(checkboxes):
                                let = chr(ord('A') + i)
                                cb_val = (cb.get_attribute("value") or "").strip().lower()

                                # 該題 checkbox group 中的字母代號 (第 0 個為 A, 第 1 個為 B...)
                                should_check = (let in expected_set)

                                # 若 expected_set 包含特定 value 比對 (如 value 為 A/B/C/D 或特殊代碼)
                                if not should_check:
                                    if cb_val and cb_val in [l.lower() for l in expected_set]:
                                        should_check = True

                                is_checked = bool(self.driver.execute_script("return arguments[0].checked;", cb))
                                if should_check and not is_checked:
                                    self.driver.execute_script("arguments[0].click();", cb)
                                elif not should_check and is_checked:
                                    self.driver.execute_script("arguments[0].click();", cb)

                            # click 後重新讀取 checked 集合
                            actual_letters = []
                            for i, cb in enumerate(checkboxes):
                                if bool(self.driver.execute_script("return arguments[0].checked;", cb)):
                                    actual_letters.append(chr(ord('A') + i))
                            actual_set = set(actual_letters)

                            exp_str = ",".join(sorted(expected_set)) if expected_set else "無"
                            act_str = ",".join(sorted(actual_set)) if actual_set else "無"
                            source_tag = f"[{ans_source}]" if ans_source else "[已知答案]"

                            # 實際集合必須與預期集合完全一致，否則不得記錄「已填答」
                            if expected_set and actual_set == expected_set:
                                logger.info(f"   📝 第{q_idx + 1}題 {source_tag} 預期={exp_str}，實際={act_str}")
                                answered += 1
                            else:
                                logger.warning(f"   ⚠️ 第{q_idx + 1}題 {source_tag} 填答驗證失敗！預期={exp_str}，實際={act_str}")
                                skipped += 1

                    elif radios:
                        idx = None
                        if ans is not None:
                            # 🛡️ 軌道 B：文字本位（Text-Content-First）優先比對，抗選項隨機重排
                            idx = match_radio_option_index(ans, option_texts, len(radios))


                        if idx is not None and idx < len(radios):
                            self.driver.execute_script(
                                "arguments[0].click();", radios[idx]
                            )
                            if self.driver.execute_script('return arguments[0].checked;', radios[idx]) is True:
                                answered += 1
                            else:
                                skipped += 1
                            if ans is not None:
                                source_tag = f"[{ans_source}]" if ans_source else "[已知答案]"
                                logger.info(f"   📝 作答進度：[{q_idx + 1}/{len(rows)} 題] 已填答 {source_tag}")
                        else:
                            logger.warning(
                                f"   ⚠️ 第 {q_idx + 1} 題單選答案無法比對，略過：{q_text[:30]!r} ans={str(ans)[:30]!r} 選項數={len(radios)}"
                            )
                            skipped += 1

                except Exception as e:
                    logger.debug(f"   ⚠️ 作答某題時發生錯誤: {e}")
                    skipped += 1

            logger.info(f"   📝 作答完成：{answered} 題已答，{skipped} 題略過")
            if not can_submit(len(rows), answered, skipped=skipped) or not self._verify_exam_ready(course, rows):
                self._mark_exam_manual_review(course, '填答讀回驗證未通過，保留草稿，禁止交卷')
                return False

            # ── 6b. 傳送缺題通知到 GAS Relay → Telegram（須明確啟用雲端同步；絕不傳送帳號）──
            if _missing and is_cloud_sync_enabled(self.config):
                # 去重（同一次考試同一題可能出現多次）
                _seen = set()
                _missing_dedup = []
                for _m in _missing:
                    _key = _m.get("question", "")
                    if _key not in _seen:
                        _seen.add(_key)
                        _missing_dedup.append(_m)

                try:
                    _GAS_URL = resolve_gas_url(self.config)
                except ValueError as _url_err:
                    logger.warning(f"   ⚠️ GAS 網址遭安全規則拒絕，略過缺題回報：{_url_err}")
                    _GAS_URL = ""

                if _GAS_URL:
                    _course_name = course.get("caption", "未知課程")
                    _username = str(self.config.get("name") or "").strip() or "匿名"
                    _payload = {
                        "course": _course_name,
                        "username": _username,
                        "missing": _missing_dedup,
                    }

                    import threading as _threading
                    import requests as _req

                    def _post_gas(url, payload):
                        try:
                            _req.post(url, json=payload, timeout=20)
                            logger.info(f"   📨 已回報 {len(payload['missing'])} 題缺題（{payload['username']}）")
                        except Exception as _e:
                            logger.debug(f"   缺題回報失敗: {_e}")

                    _threading.Thread(
                        target=_post_gas, args=(_GAS_URL, _payload), daemon=True
                    ).start()
                    logger.info(f"   📨 缺題回報已背景送出（{len(_missing_dedup)} 題）")

            # ── 7. 點「送出答案，結束測驗」──
            # 頁面有兩個 submit 按鈕：
            #   - form[name='responseForm']（save_answer.php，target='submitTarget'）
            #     點擊後會出現 alert，接受後整頁跳轉到 view_result.php
            #   - form[name='buttonLine']（exam_start.php，target=''）→ 退出考試按鈕，不送答案
            # 需要點 responseForm 的按鈕。
            time.sleep(1)
            try:
                # 明確切回考試視窗（以防 step 6 中 JS click 意外改變了 focus）
                try:
                    self.driver.switch_to.window(exam_window)
                except Exception:
                    pass

                cur_url = self.driver.current_url
                logger.info(f"   📝 送出前 URL: {cur_url}")

                result = self.driver.execute_script(
                    """
                    var btns = document.querySelectorAll('input[type="submit"]');
                    var info = [];
                    var clicked = null;
                    // 優先找 form[name='responseForm'] 的 submit（送出答案）
                    for (var i = 0; i < btns.length; i++) {
                        var b = btns[i];
                        var style = window.getComputedStyle(b);
                        var hidden = (style.display === 'none' || style.visibility === 'hidden');
                        var formName = b.form ? (b.form.name || b.form.id || '') : '';
                        info.push({i: i, value: b.value, display: style.display, formName: formName, hidden: hidden});
                        if (!hidden && formName === 'responseForm' && clicked === null) {
                            b.click();
                            clicked = 'btn_' + i + '_responseForm';
                        }
                    }
                    // fallback: 點第一個非 hidden 的 submit
                    if (clicked === null) {
                        for (var j = 0; j < btns.length; j++) {
                            var b2 = btns[j];
                            var style2 = window.getComputedStyle(b2);
                            if (style2.display !== 'none' && style2.visibility !== 'hidden') {
                                b2.click();
                                clicked = 'btn_' + j + '_fallback';
                                break;
                            }
                        }
                    }
                    return {total: btns.length, info: info, clicked: clicked};
                    """
                )
                if result is None:
                    # None 通常表示 click 觸發了頁面跳轉（form submit 成功），繼續執行
                    logger.info(
                        "   📝 execute_script 返回 None（頁面已跳轉，推測 submit 成功）"
                    )
            except Exception as e:
                logger.warning(f"   ⚠️ 送出按鈕處理失敗: {e}")
                return False

            # ── 8. 處理「你確定要繳交嗎？」alert ──
            time.sleep(1)
            if self._accept_alert():
                logger.info("   📝 已確認繳交")
            else:
                logger.warning("   ⚠️ 未出現繳交確認框")

            # 等待結果頁載入
            time.sleep(3)

            # ── 9. 讀取成績，判斷是否通過 ──
            self._last_exam_submitted = True
            passed = self._read_exam_result(course, _ai_answered=_ai_answered, main_window=main_window)

            # ── 10. 明確不及格時才嘗試讀取正確答案（成績未知時不誤觸發） ──
            if not passed and not getattr(self, "_last_exam_score_unknown", False):
                time.sleep(1)
                try:
                    self.driver.switch_to.window(exam_window)
                    cur_exam_url = self.driver.current_url
                    # 若已在 view_result.php，直接讀取
                    if "view_result" in cur_exam_url:
                        self._harvest_correct_answers(cur_exam_url)
                    else:
                        # 從 exam_start_url 推算 view_result URL
                        # exam_start.php?{course_id}+{attempt}+{token}+0
                        # → view_result.php?{course_id}+{attempt}+{token}
                        m = re.search(r"exam_start\.php\?(.+?)\+0$", exam_start_url)
                        if m:
                            base = exam_start_url.split("/learn/")[0]
                            vr_url = f"{base}/learn/exam/view_result.php?{m.group(1)}"
                            logger.debug(f"   步驟10 推算 view_result URL: {vr_url!r}")
                            self.driver.get(vr_url)
                            time.sleep(2)
                            self._harvest_correct_answers(vr_url)
                        else:
                            logger.debug(
                                f"   步驟10 無法從 exam_start URL 推算 view_result（格式不符）: {exam_start_url!r}"
                            )
                except Exception as e:
                    logger.debug(f"   步驟10 公布答案失敗: {e}")

            return passed

        except Exception as e:
            logger.error(f"   ❌ 自動作答發生錯誤: {e}")
            return False

        finally:
            # 關閉所有多餘視窗（考試視窗、查看結果視窗），切回主視窗
            try:
                for h in list(self.driver.window_handles):
                    if h != main_window:
                        try:
                            self.driver.switch_to.window(h)
                            self.driver.close()
                        except Exception:
                            pass
            except Exception:
                pass
            try:
                self.driver.switch_to.window(main_window)
            except Exception:
                pass
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass

    def auto_questionnaire(self, course):
        """考試通過後，自動填寫問卷/評價。回傳 True=完成, False=失敗/跳過"""
        # 💡 防呆檢查：若該課程已填寫問卷（fill == "1"），直接跳過不重複送出
        if str(course.get("fill", "0")) == "1":
            logger.info(f"   ✅ 「{course.get('caption', '')}」問卷先前已完成，直接跳過。")
            return True
        if not course.get("write_questionnaire") and str(course.get("criteria_survey", "0")) in ("0", "", "False"):
            logger.info(f"   ℹ️ 「{course.get('caption', '')}」無問卷要求，直接跳過。")
            return True

        logger.info("   📋 開始自動填寫問卷流程...")
        main_window = self.driver.current_window_handle

        try:
            # ── 1. 切回主視窗，點左側 sidebar「問卷/評價」──
            self.driver.switch_to.window(main_window)
            self.driver.switch_to.default_content()

            clicked_q = False
            try:
                self.driver.switch_to.frame("mooc_sysbar")
                q_link = self.driver.find_element(
                    By.CSS_SELECTOR,
                    "a[href*='questionnaire/questionnaire_list.php']",
                )
                self.driver.execute_script("arguments[0].click();", q_link)
                logger.info("   📋 已點擊「問卷/評價」")
                clicked_q = True
            except Exception:
                # 嘗試在 default_content 尋找問卷連結
                self.driver.switch_to.default_content()
                try:
                    q_link = self.driver.find_element(
                        By.CSS_SELECTOR,
                        "a[href*='questionnaire'], a[href*='survey'], a[href*='feedback'], a[onclick*='questionnaire'], a[onclick*='survey']"
                    )
                    self.driver.execute_script("arguments[0].click();", q_link)
                    logger.info("   📋 已點擊「問卷/評價」")
                    clicked_q = True
                except Exception as e:
                    logger.warning(f"   ⚠️ 找不到問卷連結: {e}")
                    return False

            # ── 2 & 3. 切到 s_main 並等待問卷狀態／「填寫問卷」按鈕載入完成 ──
            q_status, q_btn = self._wait_s_main_action_or_status(
                done_keywords=("已完成", "已填寫", "已填畢"),
                none_keywords=("目前沒有任何問卷", "尚無問卷", "沒有問卷", "無須填寫", "無需填寫"),
                timeout=12.0,
            )
            if q_status == "stopped":
                return False
            if q_status in ("done", "none"):
                logger.info("   📋 無可填寫的問卷（已確認完成或平臺無問卷）")
                return True
            if q_status != "button" or not q_btn:
                logger.warning("   ⚠️ 找不到「填寫問卷」按鈕（問卷頁未載入完成或版面不符），待人工確認")
                return False

            # ── 3. 點「填寫問卷」──
            self.driver.execute_script("arguments[0].click();", q_btn)
            self._auto_hide_popups_if_needed(settle=True)
            logger.info("   📋 已點擊「填寫問卷」")
            time.sleep(3)

            # ── 4. 切換到新跳出的問卷視窗 ──
            all_handles = self.driver.window_handles
            q_window = next((h for h in all_handles if h != main_window), None)
            if not q_window:
                logger.warning("   ⚠️ 未偵測到問卷視窗")
                return False

            self.driver.switch_to.window(q_window)
            self._auto_hide_popups_if_needed(settle=True)
            logger.info("   📋 已切換至問卷視窗")
            time.sleep(2)

            # ── 5. 填寫問卷（radio 選 value=1，checkbox 選第一個，textarea 跳過）──
            rows = self.driver.find_elements(
                By.CSS_SELECTOR, "tr.bg03.font01, tr.bg04.font01"
            )
            answered = 0
            for row in rows:
                try:
                    # checkbox：勾選第一個（value="1"）
                    checkboxes = row.find_elements(
                        By.CSS_SELECTOR, "input[type='checkbox']"
                    )
                    if checkboxes:
                        self.driver.execute_script(
                            "arguments[0].click();", checkboxes[0]
                        )
                        answered += 1
                        continue

                    # radio：選第一個選項
                    radios = row.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                    if radios:
                        self.driver.execute_script("arguments[0].click();", radios[0])
                        answered += 1
                        continue

                    # textarea：跳過

                except Exception as e:
                    logger.debug(f"   ⚠️ 填寫某題時發生錯誤: {e}")

            logger.info(f"   📋 問卷填寫完成：{answered} 題已填")

            # ── 6. 點「確定繳交」──
            time.sleep(1)
            try:
                # 先嘗試精確 value 匹配，fallback 用 JS click 任何可見 submit
                submitted_q = self.driver.execute_script(
                    """
                    var btns = document.querySelectorAll('input[type="submit"]');
                    for (var i = 0; i < btns.length; i++) {
                        var style = window.getComputedStyle(btns[i]);
                        if (style.display !== 'none' && style.visibility !== 'hidden') {
                            btns[i].click();
                            return btns[i].value || 'btn_' + i;
                        }
                    }
                    return null;
                    """
                )
                if submitted_q:
                    logger.info(
                        f"   📋 已點擊「確定繳交」（{submitted_q!r}），等待確認框..."
                    )
                elif submitted_q is None:
                    # None = page navigated during click (submit succeeded)
                    logger.info("   📋 問卷已送出（頁面已跳轉）")
                else:
                    logger.warning("   ⚠️ 找不到「確定繳交」按鈕")
                    return False
            except Exception as e:
                logger.warning(f"   ⚠️ 找不到「確定繳交」按鈕: {e}")
                return False

            # ── 7. 處理「你確定要繳交嗎？」alert（並攔截必填缺漏警語）──
            time.sleep(1)
            alert_msg = ""
            try:
                WebDriverWait(self.driver, 3).until(EC.alert_is_present())
                alert_msg = self._accept_alert_if_present()
            except Exception:
                pass
            if alert_msg:
                if any(kw in alert_msg for kw in ("請填", "必填", "未填", "漏填", "不可為空", "尚有")):
                    logger.warning(f"   ⚠️ 問卷送出遭平臺退回：{alert_msg}")
                    return False
                logger.info("   📋 已確認繳交")
            else:
                logger.warning("   ⚠️ 未出現繳交確認框")

            # ── 8. 處理「更新完畢。」alert ──
            time.sleep(2)
            if self._accept_alert():
                logger.info("   📋 問卷已完成（更新完畢）")
            else:
                logger.warning("   ⚠️ 未出現「更新完畢」確認框")

            return True

        except Exception as e:
            logger.error(f"   ❌ 自動填寫問卷發生錯誤: {e}")
            return False

        finally:
            # 關閉問卷視窗，切回主視窗
            try:
                if self.driver.current_window_handle != main_window:
                    self.driver.close()
            except Exception:
                pass
            try:
                self.driver.switch_to.window(main_window)
            except Exception:
                pass

