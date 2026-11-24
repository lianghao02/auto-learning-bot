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


class EgovStudyMixin:
    """課程清單抓取、介紹頁下架判讀、教室視窗定位與時數累積流程。"""

    def fetch_course_list(self, year=None):
        cur_year = year or time.strftime("%Y")
        courses_map = {}
        # 💡 查詢所有課程類型：包含單門(single)、MOOCs(mooc/moocs)、開放式(open)、微學習(micro)、組裝(package)、直播(live)與不限類型("")
        # 同時涵蓋當前年度與跨年度("")課程，確保所有已選修之 MOOCs 與一般課程皆 100% 納入
        type_list = ["", "mooc", "moocs", "single", "open", "micro", "package", "live"]
        year_list = [cur_year, ""]

        for y in year_list:
            for c_type in type_list:
                for page in range(1, 35):
                    payload = f"year={y}&keyword=&course_type={c_type}&page={page}&orderby=&sort="
                    try:
                        resp = self.http_session.post(
                            self.api_url, data=payload, timeout=10
                        )
                        data = resp.json().get("data", [])
                        if not data or len(data) == 0:
                            break
                        for item in data:
                            cid = str(item.get("course_id", "") or item.get("id", ""))
                            key = cid or item.get("caption", "")
                            if key and key not in courses_map:
                                courses_map[key] = item
                    except Exception as e:
                        logger.debug(f"讀取 [y={y}, type={c_type}] 第 {page} 頁課程: {e}")
                        break
        return list(courses_map.values())

    def fetch_course_list_checked(self, year=None):
        courses = self.fetch_course_list(year)
        count = len(courses)
        should_retry = 0 < count < 5
        if self._last_course_count and 0 < count < self._last_course_count:
            should_retry = True

        if should_retry:
            logger.warning(
                f"⚠️ 課程 API 只回 {count} 筆"
                + (
                    f"（前次 {self._last_course_count} 筆）"
                    if self._last_course_count
                    else ""
                )
                + "，先同步 session 後重抓。"
            )
            try:
                self.sync_session()
            except Exception:
                pass
            time.sleep(2)
            try:
                retry_courses = self.fetch_course_list(year)
            except Exception:
                retry_courses = courses
            if len(retry_courses) > count:
                logger.info(f"✅ 課程 API 重抓成功：{count} → {len(retry_courses)} 筆")
                courses = retry_courses
                count = len(courses)

        if count > self._last_course_count:
            self._last_course_count = count
        return courses

    def _is_open_course(self, course):
        course_type = str(course.get("course_type", "") or "").strip().lower()
        if course_type:
            return any(k in course_type for k in [
                "開放式", "單門課程", "微學習", "組合課程", "單門",
                "組裝課程", "套裝課程", "直播課程", "直播", "隨選視訊",
                "mooc", "moocs", "磨課師", "一般課程"
            ])
        course_type_cd = str(course.get("course_type_cd", "") or "").strip().lower()
        if course_type_cd:
            return any(k in course_type_cd for k in [
                "single", "open", "micro", "package", "live", "broadcast", "mooc", "moocs"
            ])
        return True

    def _is_playable_course(self, course):
        """檢查是否為具有實體播放時數之單門/微學習/直播課程（排除純組裝套裝容器本身）。"""
        course_type = str(course.get("course_type", "") or "").strip()
        course_type_cd = str(course.get("course_type_cd", "") or "").strip().lower()
        if course_type in {"組裝課程", "套裝課程"} or course_type_cd == "package":
            return False
        return True

    def _is_exam_passed(self, c):
        """檢查該課程之測驗是否已達到及格標準。"""
        # 1. 取得通過狀態文字與標記
        pass_status = str(
            c.get("exam_pass_status", "")
            or c.get("pass_status", "")
            or c.get("status_text", "")
            or ""
        ).strip().lower()

        # 若平臺明確標註未通過/不及格/未達標，必定為未通過（如臺灣藍碳 60 分未達 75 分門檻）
        if any(w in pass_status for w in ["未通過", "不及格", "fail"]):
            return False

        # 2. 取得及格門檻標準（預設 60 分，支援 criteria_exam_score, criteria_score, pass_score 等欄位）
        pass_score = 60.0
        for f in [
            "criteria_exam_score",
            "criteria_score",
            "pass_score",
            "exam_pass_score",
            "criteria_test_score",
        ]:
            val = c.get(f)
            if val is not None and str(val).strip() not in ("", "--", "None", "null", "0", "0.0"):
                try:
                    pass_score = float(val)
                    break
                except Exception:
                    pass

        # 3. 若有測驗分數，比對是否達到及格門檻
        score_val = c.get("exam_score")
        if score_val is not None and str(score_val).strip() not in ("", "--", "None", "null", "未填", "未測驗"):
            try:
                score_num = float(score_val)
                if score_num < pass_score:
                    return False
                return True
            except Exception:
                pass

        # 4. 明確測驗通過標記
        if pass_status in ["1", "pass", "passed", "已通過", "及格"]:
            return True

        # 5. 若無測驗分數且有測驗要求（criteria_exam_score > 0 或 write_exam == 1 或 exam_exists == 1）
        has_exam_req = (
            (c.get("criteria_exam_score") and str(c.get("criteria_exam_score")).strip() not in ("", "0", "0.0", "--"))
            or str(c.get("write_exam", "0")) == "1"
            or str(c.get("exam_exists", "0")) == "1"
        )
        if has_exam_req:
            return False

        # 無任何測驗要求之課程視為測驗通過
        return True

    def _is_course_completed(self, c) -> bool:
        """檢查課程是否已由平臺確認全數修畢（時數達標且通過，或時數/測驗/問卷全數完成）。"""
        rss_sec = to_sec(c.get("rss", "00:00:00"))
        crit_sec = to_sec(c.get("criteria_content_hour", "00:00:00"))

        # 1. 基礎閱讀時數必須達標 100%
        if crit_sec > 0 and rss_sec < crit_sec:
            return False

        # 2. 若平臺明確標註未通過/不及格
        pass_status = str(
            c.get("exam_pass_status", "")
            or c.get("pass_status", "")
            or c.get("status_text", "")
            or ""
        ).strip().lower()
        if any(w in pass_status for w in ["未通過", "不及格", "fail"]):
            return False

        # 3. 若有測驗要求，測驗必須及格（不可只依賴 status=1 報名狀態）
        if not self._is_exam_passed(c):
            return False

        # 4. 若有問卷要求，問卷必須已填寫
        q_req = bool(c.get("write_questionnaire", ""))
        if q_req and str(c.get("fill", "0")) != "1":
            return False

        return True

    def _mark_exam_manual_review(self, course, reason):
        """記錄本次無法完成的測驗，避免重複卡住且禁止宣告全部完成。"""
        course_id = str(course.get("course_id", ""))
        if course_id:
            self._exam_manual_review[course_id] = {
                "caption": course.get("caption", course_id),
                "reason": reason,
            }
        logger.warning(f"   ⚠️ 測驗待處理：{course.get('caption', course_id)}｜{reason}")

    def _record_unavailable_course(self, course, reason):
        """記錄平臺已下架或非開課期間課程，本輪跳過且不與測驗失敗混淆。"""
        course_id = str(course.get("course_id", ""))
        caption = course.get("caption", course_id)
        if course_id:
            self._completed_in_session.add(course_id)
            self.__dict__.setdefault("_unavailable_in_session", {})[course_id] = {
                "caption": caption,
                "reason": reason,
            }
        logger.info(f"   ⏩ 課程「{caption}」{reason}，本輪自動略過。")

    def auto_enroll_package_subcourses(self, courses) -> bool:
        """組裝課程子課程缺漏時的手動修復備援；正常執行流程不會自動呼叫。"""
        if not self.driver or not self.running:
            return False
        if getattr(self, "_package_preflight_completed", False):
            return False

        packages_dict = {}
        dashboard_completed_ids = set()

        # 優先從「我的課程儀表板 -> 組裝課程 (tab=4)」遍歷所有分頁掃描進行中之組裝課程
        try:
            self.driver.get("https://elearn.hrd.gov.tw/mooc/user/learn_dashboard.php?tab=4")
            self.safe_sleep(3)
            for dash_page in range(1, 31):
                if not self.running:
                    break
                logger.info(f"   🔎 組裝課程儀表板掃描：第 {dash_page} 頁")
                pkg_cards = self.driver.execute_script(get_package_dashboard_script())
                if pkg_cards:
                    for pc in pkg_cards:
                        pid = str(pc.get("id", ""))
                        if not pid:
                            continue
                        if pc.get("is100"):
                            dashboard_completed_ids.add(pid)
                            logger.info(f"   ⏩ 組裝課程【{pc.get('title')}】進度已達 100%（全數修畢），直接略過。")
                        elif pid not in self._expanded_packages:
                            packages_dict[pid] = pc.get("title") or pid

                has_next = self.driver.execute_script("""
                    var nextBtns = document.querySelectorAll(
                        '.pagination a, .pagination button, .pagination input, .pagination span, .page-link, a.next, li.next a, [aria-label="Next"], [aria-label="下一頁"], [rel="next"], [class*="next"], [class*="Next"]'
                    );
                    for (var i = 0; i < nextBtns.length; i++) {
                        var btn = nextBtns[i];
                        var t = (btn.innerText || btn.value || btn.textContent || '').trim();
                        var label = (btn.getAttribute('aria-label') || btn.getAttribute('title') || '').trim();
                        var className = String(btn.className || '') + ' ' + String(btn.parentElement ? btn.parentElement.className : '');
                        var hasRightIcon = !!btn.querySelector('.fa-angle-right, .fa-chevron-right, .glyphicon-chevron-right, .icon-right, .fa-step-forward, .fa-forward');
                        var disabled = btn.classList.contains('disabled') ||
                                       (btn.parentElement && btn.parentElement.classList.contains('disabled')) || btn.disabled ||
                                       btn.getAttribute('aria-disabled') === 'true';
                        if (!disabled && (
                            t === '>' || t === '>|' || t === '›' || t === '»' || t.indexOf('下一頁') !== -1 || t.indexOf('Next') !== -1 ||
                            label.indexOf('下一頁') !== -1 || label.indexOf('Next') !== -1 ||
                            /(^|\\s)(next|pagination-next)(\\s|$)/i.test(className) ||
                            hasRightIcon || t === String(arguments[0] + 1)
                        )) {
                            btn.click();
                            return {clicked: true, text: t || label || '圖示下一頁'};
                        }
                    }
                    return {clicked: false, text: ''};
                """, dash_page)
                if not has_next or not has_next.get("clicked"):
                    break
                logger.info(f"   ➡️ 已切換組裝課程儀表板下一頁：{has_next.get('text')}")
                self.safe_sleep(2)
        except Exception as e:
            logger.debug(f"組裝課程儀表板 (tab=4) 掃描略過: {e}")

        # 無論儀表板掃到幾筆，一律與 API 回傳的組裝課程聯集去重，避免漏課。
        for c in courses:
            c_id = str(c.get("course_id", "") or c.get("id", ""))
            c_caption = str(c.get("caption", ""))
            c_type = str(c.get("course_type", ""))
            c_type_cd = str(c.get("course_type_cd", "")).lower()

            if (
                c_type_cd == "package"
                or any(k in c_type for k in ["組裝", "套裝", "組合"])
                or any(k in c_caption for k in ["組裝", "套裝", "組合"])
            ) and c_id and c_id not in dashboard_completed_ids and c_id not in self._expanded_packages:
                packages_dict.setdefault(c_id, c_caption or c_id)

        if not packages_dict:
            self._package_preflight_completed = True
            return False

        expanded_any = False
        for pkg_id, pkg_name in list(packages_dict.items()):
            if not self.running:
                break
            if pkg_id in self._expanded_packages:
                continue

            try:
                # ── 步驟 A：進入母套裝頁面 ──
                pkg_url = f"https://elearn.hrd.gov.tw/info/{pkg_id}"
                self.driver.get(pkg_url)
                self.safe_sleep(3)

                logger.info(f"📦 【母課程】ID={pkg_id}｜{pkg_name}，正在展開內部子課程...")

                # ── 步驟 B：切換至「課程資訊」頁籤 ──
                switched_tab = self.driver.execute_script("""
                    var tabs = document.querySelectorAll('a, li, button, span, .nav-tabs li');
                    for (var i = 0; i < tabs.length; i++) {
                        var t = (tabs[i].innerText || tabs[i].textContent || '').trim();
                        if (t.indexOf('課程資訊') !== -1) {
                            tabs[i].click();
                            return true;
                        }
                    }
                    return false;
                """)
                if switched_tab:
                    logger.info("   📑 已切換至「課程資訊」頁籤")
                self.safe_sleep(2)

                # ── 步驟 C：萃取「課程清單」中所有子課程連結（排除右側推薦） ──
                sub_courses = self.driver.execute_script("""
                    var pkgId = arguments[0];
                    var results = [];
                    var seen = {};

                    var mainArea = document.querySelector('.course-list, .tab-content, #tab2, #collapseList, .content-container, .main-content') || document.body;
                    var links = mainArea.querySelectorAll('a');

                    for (var i = 0; i < links.length; i++) {
                        var a = links[i];
                        var href = a.href || '';
                        var text = (a.innerText || a.textContent || '').trim();

                        var inSidebar = a.closest('.sidebar, .recommend, .col-md-4, .col-lg-3, .col-sm-4, #recommend, .side-bar');
                        if (inSidebar) continue;

                        if (href && (href.indexOf('/info/') !== -1 || href.indexOf('course_id=') !== -1)) {
                            if (pkgId && href.indexOf('/info/' + pkgId) !== -1) continue;
                            if (!seen[href]) {
                                seen[href] = true;
                                results.push({href: href, text: text});
                            }
                        }
                    }
                    return results;
                """, pkg_id)

                if sub_courses:
                    logger.info(f"   📋 【子課程清單】母課程 ID={pkg_id}，共 {len(sub_courses)} 門。")
                    processed_subcourses = 0
                    for s_idx, sub in enumerate(sub_courses):
                        if not self.running:
                            break
                        sub_url = sub.get("href", "")
                        sub_text = sub.get("text", f"子課程 {s_idx + 1}")
                        logger.info(f"   👉 【子課程 {s_idx + 1}/{len(sub_courses)}】{sub_text[:35]}")

                        try:
                            self.driver.get(sub_url)
                            self.safe_sleep(2)
                            result = self.driver.execute_script("""
                                var statusBox = document.querySelector('.course-status, [class*="status"], .sidebar, .col-md-4, .col-lg-3, div[class*="sidebar"]') || document.body;
                                var statusText = statusBox.innerText || '';

                                // 1. 檢查右側狀態欄是否顯示「通過狀態：已通過」
                                if (
                                    statusText.indexOf('通過狀態：已通過') !== -1 ||
                                    statusText.indexOf('通過狀態: 已通過') !== -1 ||
                                    (statusText.indexOf('已通過') !== -1 && statusText.indexOf('閱讀時數') !== -1)
                                ) {
                                    return {action: 'already_passed', text: '已通過'};
                                }

                                // 2. 優先尋找「報名課程」按鈕
                                var btns = document.querySelectorAll('button, a.btn, a, input[type="button"], input[type="submit"]');
                                for (var i = 0; i < btns.length; i++) {
                                    var t = (btns[i].innerText || btns[i].value || btns[i].textContent || '').trim();
                                    if (
                                        t === '報名課程' ||
                                        t === '我要報名' ||
                                        t === '確認報名' ||
                                        t === '選課' ||
                                        t === '加入課程' ||
                                        (t.indexOf('報名') !== -1 && t.indexOf('名額') === -1)
                                    ) {
                                        btns[i].click();
                                        return {action: 'enrolled', text: t};
                                    }
                                }

                                // 3. 檢查是否已在學習中（顯示「上課去」）
                                for (var i = 0; i < btns.length; i++) {
                                    var t = (btns[i].innerText || btns[i].value || btns[i].textContent || '').trim();
                                    if (['上課去', '進入課程', '開始上課'].indexOf(t) !== -1) {
                                        return {action: 'in_progress', text: t};
                                    }
                                }

                                return {action: 'none', text: ''};
                            """)
                            self.safe_sleep(1.5)
                            self._accept_alert_if_present()

                            if not result:
                                logger.info("      ℹ️ 子課程已在研習清單中或已自動選入")
                            elif result.get("action") == "already_passed":
                                processed_subcourses += 1
                                logger.info(f"      ✅ 子課程【{sub_text[:30]}】已取得認證（通過狀態：已通過），跳過。")
                            elif result.get("action") == "enrolled":
                                logger.info(f"      📝 報名前狀態：{result.get('text')}；正在回讀平台狀態確認。")
                                self.driver.get(sub_url)
                                self.safe_sleep(2)
                                post_result = self.driver.execute_script("""
                                    var bodyText = document.body ? document.body.innerText : '';
                                    var btns = document.querySelectorAll('button, a.btn, a, input[type="button"], input[type="submit"]');
                                    var labels = [];
                                    for (var i = 0; i < btns.length; i++) {
                                        var t = (btns[i].innerText || btns[i].value || btns[i].textContent || '').trim();
                                        if (t) labels.push(t);
                                    }
                                    var inProgress = labels.some(function(t) {
                                        return ['上課去', '進入課程', '開始上課'].indexOf(t) !== -1;
                                    });
                                    var stillEnroll = labels.some(function(t) {
                                        return t === '報名課程' || t === '我要報名' || t === '確認報名' || t === '選課' || t === '加入課程';
                                    });
                                    var passed = bodyText.indexOf('通過狀態：已通過') !== -1 ||
                                                 bodyText.indexOf('通過狀態: 已通過') !== -1;
                                    return {in_progress: inProgress, still_enrollable: stillEnroll, passed: passed, buttons: labels.slice(0, 12)};
                                """)
                                if post_result.get("in_progress") or post_result.get("passed"):
                                    processed_subcourses += 1
                                    logger.info("      ✅ 報名後驗證成功：已轉為可上課／已通過狀態。")
                                else:
                                    logger.warning(
                                        f"      ⚠️ 報名後未確認成功（仍可報名={post_result.get('still_enrollable')}，按鈕={post_result.get('buttons')}），保留供下一輪重試。"
                                    )
                            elif result.get("action") == "in_progress":
                                processed_subcourses += 1
                                logger.info(f"      ℹ️ 子課程已在研習清單中（{result.get('text')}），進行中。")
                            else:
                                logger.warning("      ⚠️ 無法判斷子課程目前狀態，保留供下一輪重試。")

                        except Exception as sub_e:
                            logger.warning(f"      ⚠️ 子課程登記異常: {sub_e}")

                    if processed_subcourses == len(sub_courses):
                        self._expanded_packages.add(pkg_id)
                        expanded_any = True
                        logger.info(f"   ✅ 母課程 ID={pkg_id} 已處理 {processed_subcourses}/{len(sub_courses)} 門子課程，本次不再重複展開。")
                    else:
                        logger.warning(f"   ⚠️ 母課程 ID={pkg_id} 僅處理 {processed_subcourses}/{len(sub_courses)} 門子課程，保留供下一輪重試。")

                else:
                    logger.warning(f"   ⚠️ 未能從套裝 {pkg_name} 課程資訊中解析出子課程連結，保留供下一輪重試。")

                # ── 步驟 D：返回母套裝頁面點擊「上課去」確保整體啟動 ──
                try:
                    self.driver.get(pkg_url)
                    self.safe_sleep(2)
                    self.driver.execute_script("""
                        var btns = document.querySelectorAll('button, a.btn, a');
                        for (var i = 0; i < btns.length; i++) {
                            var t = (btns[i].innerText || btns[i].textContent || '').trim();
                            if (['上課去', '進入課程', '報名'].some(k => t.indexOf(k) !== -1)) {
                                btns[i].click();
                                break;
                            }
                        }
                    """)
                    self.safe_sleep(2)
                    self._accept_alert_if_present()
                except Exception:
                    pass

            except Exception as e:
                logger.warning(f"⚠️ 展開組裝課程 {pkg_name} 時發生異常: {e}")

        # 展開完畢後返回統計頁並同步 session
        if expanded_any:
            try:
                self.driver.get(self.stat_url)
                self.safe_sleep(2)
                self.sync_session()
            except Exception:
                pass

        self._package_preflight_completed = True
        logger.info("📦 組裝課程前置檢查完成；本次執行不再重複掃描。")
        return expanded_any


    def _resolve_hahow_device_sessions(self) -> bool:
        """若外購平臺 Hahow 遇到登入裝置數量上限（device_sessions），自動登出舊裝置並點擊『繼續』"""
        if not self.driver:
            return False
        curr_h = None
        try:
            curr_h = self.driver.current_window_handle
        except Exception:
            pass

        try:
            for handle in list(self.driver.window_handles):
                try:
                    self.driver.switch_to.window(handle)
                    url = self.driver.current_url or ""
                    if "hahow.in" in url:
                        handled = self.driver.execute_script("""
                            var text = document.body ? document.body.innerText : '';
                            if (location.href.indexOf('device_sessions') !== -1 || text.indexOf('登入數量上限') !== -1 || text.indexOf('登出下面其中') !== -1) {
                                var logoutBtns = document.querySelectorAll('button, a.btn');
                                for (var i = 0; i < logoutBtns.length; i++) {
                                    var t = (logoutBtns[i].innerText || logoutBtns[i].textContent || '').trim();
                                    if (t === '登出') {
                                        logoutBtns[i].click();
                                        break;
                                    }
                                }
                                return true;
                            }
                            return false;
                        """)
                        if handled:
                            time.sleep(1.5)
                            self.driver.execute_script("""
                                var continueBtns = document.querySelectorAll('button, a.btn');
                                for (var j = 0; j < continueBtns.length; j++) {
                                    var ct = (continueBtns[j].innerText || continueBtns[j].textContent || '').trim();
                                    if (ct === '繼續' && !continueBtns[j].disabled) {
                                        continueBtns[j].click();
                                        break;
                                    }
                                }
                            """)
                            logger.info("   🔓 偵測到 Hahow 裝置數量上限，已自動排除舊裝置並點擊「繼續」進入平臺！")
                            time.sleep(2)
                            return True
                except Exception:
                    continue
        finally:
            if curr_h:
                try:
                    self.driver.switch_to.window(curr_h)
                except Exception:
                    pass
        return False

    def _is_course_already_completed_on_info_page(self):
        """精準檢查當前 /info/ 頁面是否平臺已明確記錄為已通過/修畢。
        嚴禁僅因課程介紹、注意事項中含有『無法重複取得時數』等靜態文字而誤判！
        """
        if not self.driver:
            return False
        try:
            # 1. 優先檢查右側「我的課程狀態」區塊中的「通過狀態」
            status_box_text = self.driver.execute_script("""
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var t = (all[i].innerText || '').trim();
                    if (t.indexOf('我的課程狀態') !== -1 && t.indexOf('通過狀態') !== -1) {
                        return t;
                    }
                }
                return '';
            """) or ""

            if status_box_text:
                import re
                if re.search(r'通過狀態\s*[:：]\s*(已通過|通過|及格)', status_box_text):
                    return True
                if "通過狀態" in status_box_text and any(k in status_box_text for k in ["--", "未通過", "未完成"]):
                    return False

            # 2. 檢查頁面彈窗或專屬通知（Alert / Dialog / Modal）
            personal_alert = self.driver.execute_script("""
                var modals = document.querySelectorAll('.modal, .alert-danger, .alert-warning, div[role="dialog"]');
                for (var m = 0; m < modals.length; m++) {
                    var mt = (modals[m].innerText || '').trim();
                    if (mt.indexOf('您已完成此課程') !== -1 && mt.indexOf('無法重複取得時數') !== -1) {
                        return mt;
                    }
                }
                return '';
            """) or ""
            if personal_alert:
                return True
        except Exception:
            pass
        return False

    def _detect_unavailable_course_on_info_page(self) -> str | None:
        """在 /info/ 課程介紹頁即時判讀課程是否已下架或非開課期間。

        僅在畫面上沒有任何可用上課入口按鈕時才認定下架，避免被課程簡介內的靜態文字誤判。
        """
        if not self.driver:
            return None
        try:
            cur_u = str(getattr(self.driver, "current_url", "") or "")
            if "/info/" not in cur_u:
                return None
            snapshot = self.driver.execute_script(
                """
                function isVisible(el) {
                    var style = window.getComputedStyle(el);
                    return el.getClientRects().length > 0 && style.display !== 'none' &&
                        style.visibility !== 'hidden' && style.visibility !== 'collapse';
                }
                function getLabel(el) {
                    return (el.innerText || el.value || el.textContent || '').replace(/\\s+/g, ' ').trim();
                }
                var entryLabels = ['上課去', '進入課程', '開始上課', '前往教室', '繼續學習', '觀看影片', '前往研習', '開始學習', '前往學習'];
                var hasActiveEntry = false;
                var disabledLabels = [];
                var controls = document.querySelectorAll('button, a.btn, a, input[type="button"], input[type="submit"], span.btn, div.btn');
                for (var i = 0; i < controls.length; i++) {
                    var el = controls[i];
                    if (!isVisible(el)) continue;
                    var lbl = getLabel(el);
                    var clean = lbl.replace(/\\s+/g, '');
                    var isDisabled = !!el.disabled || el.getAttribute('aria-disabled') === 'true' ||
                        (el.className && String(el.className).indexOf('disabled') !== -1);
                    if (isDisabled) {
                        if (lbl) disabledLabels.push(lbl);
                        continue;
                    }
                    var href = (el.getAttribute('href') || '').toLowerCase();
                    var onclick = (el.getAttribute('onclick') || '').toLowerCase();
                    if (entryLabels.some(function(k) { return clean.indexOf(k) !== -1; }) ||
                        onclick.indexOf('goclass') !== -1 || onclick.indexOf('gotocourse') !== -1 ||
                        href.indexOf('action=learn') !== -1) {
                        hasActiveEntry = true;
                        break;
                    }
                }
                var bodyText = document.body ? (document.body.innerText || '') : '';
                return {
                    hasActiveEntry: hasActiveEntry,
                    disabledLabels: disabledLabels,
                    bodyText: bodyText
                };
                """
            )
            if not isinstance(snapshot, dict):
                return None
            return _match_unavailable_course_reason(
                snapshot.get("bodyText", ""),
                snapshot.get("disabledLabels") or (),
                bool(snapshot.get("hasActiveEntry", False)),
            )
        except Exception:
            return None

    def find_classroom_window(self):
        """Return the browser window that owns the course frame tree or MOOCs/Hahow player."""
        if not self.driver:
            return None
        self._resolve_hahow_device_sessions()
        try:
            handles = list(self.driver.window_handles)
        except Exception:
            return None

        # 1. 第一優先：尋找傳統 frameset 教室（s_catalog / pathtree）
        for handle in reversed(handles):
            try:
                self.driver.switch_to.window(handle)
                self.driver.switch_to.default_content()
                self.driver.switch_to.frame("s_catalog")
                self.driver.switch_to.frame("pathtree")
                self.driver.switch_to.default_content()
                return handle
            except Exception:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
                continue

        # 2. 第二優先：尋找外購平臺 / 現代播放器視窗（如 Hahow, /learn/, /controllers/, 具備 <video> 或播放器之獨立分頁）
        for handle in reversed(handles):
            try:
                self.driver.switch_to.window(handle)
                self.driver.switch_to.default_content()
                url = self.driver.current_url or ""
                # 排除純登入頁、首頁或學習概況/儀表板總覽頁與純介紹頁（/info/）
                if any(k in url for k in ["Clogin.aspx", "egov_login.php", "learn_stat.php", "learn_dashboard.php", "mooc/index.php", "/info/"]):
                    continue
                # 若 URL 包含課程相關路徑（hahow、learn、course、controllers）或頁面含有播放器特徵
                is_player_url = any(k in url for k in ["hahow.in", "/learn/", "/course/", "/controllers/", "player"])
                has_player_or_units = self.driver.execute_script("""
                    return !!(
                        document.querySelector('video, audio, .video-js, #player, .player, [class*="unit"], [class*="chapter"], [class*="lecture"], [class*="LectureItem"], [class*="node"], a[onclick*="play"]') ||
                        window.API || window.LMSCommit
                    );
                """)
                if is_player_url or has_player_or_units:
                    return handle
            except Exception:
                continue

        # 3. 第三優先：若有多個視窗且非 stat/首頁/登入/介紹頁面，回傳最後開啟之視窗作為 fallback
        if len(handles) > 1:
            for handle in reversed(handles):
                try:
                    self.driver.switch_to.window(handle)
                    url = self.driver.current_url or ""
                    if not any(
                        k in url
                        for k in [
                            "learn_stat.php",
                            "learn_dashboard.php",
                            "mooc/index.php",
                            "Clogin.aspx",
                            "egov_login.php",
                            "/info/",
                        ]
                    ):
                        return handle
                except Exception:
                    pass

        # 4. 保底：若只有 1 個視窗且非 stat/首頁/登入/介紹頁面
        if len(handles) == 1:
            try:
                self.driver.switch_to.window(handles[0])
                url = self.driver.current_url or ""
                if not any(
                    k in url
                    for k in [
                        "learn_stat.php",
                        "learn_dashboard.php",
                        "mooc/index.php",
                        "Clogin.aspx",
                        "egov_login.php",
                        "/info/",
                    ]
                ):
                    return handles[0]
            except Exception:
                pass

        return None


    def get_progress_api(self, course_id):
        cache_key = str(course_id)
        now = time.time()
        cached = getattr(self, "_progress_cache", {})
        if cache_key in cached:
            result, ts = cached[cache_key]
            if now - ts < 30:
                return result
        try:
            current_year = time.strftime("%Y")
            # 多頁查詢，避免課程在 page>1 時查不到進度
            for _page in range(1, 21):
                payload = f"year={current_year}&keyword=&course_type=single&page={_page}&orderby=&sort="
                resp = self.http_session.post(
                    self.api_url, data=payload, timeout=10
                )
                data = resp.json().get("data", [])
                for c in data:
                    if str(c.get("course_id")) == str(course_id):
                        cur_s = to_sec(c.get("rss", "00:00:00"))
                        target_s = to_sec(
                            c.get("criteria_content_hour", "00:30:00")
                        ) * self.config.get("target_percentage", 1.0)
                        result = {
                            "cur_str": sec_to_str(cur_s),
                            "target_str": sec_to_str(target_s),
                            "cur_sec": cur_s,
                            "target_sec": target_s,
                        }
                        if not hasattr(self, "_progress_cache"):
                            self._progress_cache = {}
                        self._progress_cache[cache_key] = (result, now)
                        return result
                if len(data) < 50:
                    break  # 最後一頁，不再繼續
        except Exception as e:
            logger.debug(f"進度查詢失敗: {e}")
        return None

    def study_process(self, course):
        if not self._is_open_course(course) or not self._is_playable_course(course):
            logger.info(
                f"⏭️ 略過非播放/組裝容器課程：{course.get('caption', course.get('course_id', '未知課程'))}"
            )
            return "SKIP"

        logger.info(
            f"📖 [{self.current_idx}/{self.total_courses}] 正在協助研習：{Fore.YELLOW}{course['caption']}{Style.RESET_ALL}"
        )
        session_start = time.time()
        last_prog_sec = -1
        last_prog_time = time.time()
        course_success = False

        try:
            # ⭐ 檢查點 1
            if not self.running:
                logger.info("🛑 使用者手動停止（study_process 開始）")
                return "STOP"

            # 確保 driver 在 stat_url（gotoCourse 函式只在該頁面定義）
            self.driver.get(self.stat_url)
            self._auto_hide_popups_if_needed(settle=True)
            if not self.safe_sleep(3):
                return "STOP"

            orig_handles = list(self.driver.window_handles)
            self.driver.execute_script(f"gotoCourse({course['course_id']})")
            self._auto_hide_popups_if_needed(settle=True)
            if not self.safe_sleep(4):
                return "STOP"

            # ⭐ 進入課程後先攔截 alert（如「您非本門課的學生」、「尚未上架且非上課期間」等）
            try:
                WebDriverWait(self.driver, 3).until(EC.alert_is_present())
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                alert.accept()
                logger.warning(f"⚠️ gotoCourse 後偵測到 Alert：{alert_text}")
                if any(
                    kw in alert_text
                    for kw in [
                        "非本門課",
                        "無法上課",
                        "無權限",
                        "不開放",
                        "未選課",
                        "尚未上架",
                        "已下架",
                        "直播已結束",
                        "尚未開始",
                        "非上課期間",
                        "非開放期間",
                        "無法進入教室",
                    ]
                ):
                    logger.warning(f"⚠️ 此課程無法進入（{alert_text}），永久跳過。")
                    self._completed_in_session.add(str(course.get("course_id", "")))
                    return "SKIP"
                elif any(kw in alert_text for kw in ["閒置", "重新登入", "登出"]):
                    return "RELOGIN"
            except Exception:
                pass  # 無 alert，正常繼續

            # ⭐ 檢查點 2
            if not self.running:
                logger.info("🛑 使用者手動停止（進入課程）")
                return "STOP"

            # 若 gotoCourse 開啟了新分頁，切換過去
            new_handles = list(self.driver.window_handles)
            if len(new_handles) > len(orig_handles):
                self.driver.switch_to.window(new_handles[-1])
                self._auto_hide_popups_if_needed(settle=True)

            cur_u = self.driver.current_url or ""
            # 💡 若未直接進入教室且非介紹頁（例如停留在首頁 mooc/index.php 或統計頁），強制導航至 /info/{course_id}
            is_classroom_url = any(
                k in cur_u for k in ["/learn/", "/course/", "/controllers/", "hahow.in"]
            )
            if not is_classroom_url and "/info/" not in cur_u:
                logger.info(
                    f"   🧭 導航至課程資訊頁：https://elearn.hrd.gov.tw/info/{course['course_id']}"
                )
                self.driver.get(f"https://elearn.hrd.gov.tw/info/{course['course_id']}")
                self._auto_hide_popups_if_needed(settle=True)
                self.safe_sleep(3)
                info_alert = self._accept_alert_if_present()
                if info_alert:
                    logger.warning(f"   ⚠️ 課程頁面提示：{info_alert}")
                    if any(
                        kw in info_alert
                        for kw in [
                            "尚未上架",
                            "已下架",
                            "非上課期間",
                            "非開放期間",
                            "無法進入",
                            "不開放",
                            "無法上課",
                        ]
                    ):
                        logger.warning(
                            f"   ⏩ 「{course.get('caption', '')}」尚未上架或非上課期間，自動永久略過。"
                        )
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        return "SKIP"
                cur_u = self.driver.current_url or ""

            # 若停留在 /info/ 介紹頁，先檢查是否平臺已標註修畢/通過，或已下架／非開課期間
            if "/info/" in cur_u:
                if self._is_course_already_completed_on_info_page():
                    logger.info(
                        f"   🎉 課程「{course.get('caption', '')}」平臺已記錄為已修畢（通過狀態已通過），自動標記完成並略過。"
                    )
                    self._completed_in_session.add(str(course.get("course_id", "")))
                    return "SKIP"

                unavail_reason = self._detect_unavailable_course_on_info_page()
                if unavail_reason:
                    self._record_unavailable_course(course, unavail_reason)
                    return "SKIP"

                before_handles = list(self.driver.window_handles)
                clicked = self._click_course_entry(allow_enrollment=True)
                if clicked:
                    logger.info(f"   📝 已點擊「{clicked}」進入課程教室")

                # 💡 攔截點擊後彈出的外購平臺提示 Alert（如「本課程為外購Hahow平臺課程...」）
                time.sleep(1)
                info_alert = self._accept_alert_if_present()
                if info_alert:
                    logger.info(f"   ℹ️ 課程平台轉址提示：{info_alert}")
                    if any(k in info_alert for k in ["外購", "Hahow", "外部平臺"]):
                        logger.warning(f"   ⏩ 「{course.get('caption', '')}」為外購平臺課程，自動略過並優先研習本平臺課程。")
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        try:
                            for h in list(self.driver.window_handles):
                                if orig_handles and h != orig_handles[0]:
                                    self.driver.switch_to.window(h)
                                    self.driver.close()
                            if orig_handles:
                                self.driver.switch_to.window(orig_handles[0])
                        except Exception:
                            pass
                        return "SKIP"

                self.safe_sleep(4)
                try:
                    after_handles = list(self.driver.window_handles)
                    if len(after_handles) > len(before_handles):
                        self.driver.switch_to.window(after_handles[-1])
                        self._auto_hide_popups_if_needed(settle=True)
                except Exception:
                    pass

            for _ in range(10):
                if not self.running:  # ⭐ 檢查點 4
                    logger.info("🛑 使用者手動停止（等待教室載入）")
                    return "STOP"
                time.sleep(1)

            classroom_h = self.find_classroom_window()
            if not classroom_h:
                unavail_reason = self._detect_unavailable_course_on_info_page()
                if unavail_reason:
                    self._record_unavailable_course(course, unavail_reason)
                    return "SKIP"
                logger.warning(
                    f"   ⚠️ 課程「{course.get('caption', '')}」無法載入有效教室介面（停留在介紹頁或首頁），自動略過並標記為待查核。"
                )
                self._mark_exam_manual_review(course, "未能成功載入教室或播放器（停留在介紹/首頁）")
                self._completed_in_session.add(str(course.get("course_id", "")))
                return "SKIP"
            self.driver.switch_to.window(classroom_h)
            self._auto_hide_popups_if_needed(settle=True)

            attempted = set()
            frame_fail_count = 0

            while self.running:
                self._auto_hide_popups_if_needed()
                # 1. 檢查單次累計時數是否超過 2 小時 (7200秒)
                if time.time() - session_start > 7200:
                    logger.warning(
                        "   ⚠️ 單一課程研習已達 2 小時，為避免異常，將切換課程。"
                    )
                    break

                prog = self.get_progress_api(course["course_id"])
                if prog:
                    logger.info(
                        f"   📊 研習進度：{prog['cur_str']} / {prog['target_str']} {draw_bar(prog['cur_sec'], prog['target_sec'])}"
                    )

                    if prog["cur_sec"] > last_prog_sec:
                        last_prog_sec = prog["cur_sec"]
                        last_prog_time = time.time()
                    elif time.time() - last_prog_time > 600:
                        logger.error(
                            "   🛑 進度停滯超過 10 分鐘，正在強制執行重啟救回機制。"
                        )
                        return "STALLED"
                    elif time.time() - last_prog_time > 300:
                        logger.warning("   ⚠️ 進度已停滯 5 分鐘，請注意連線狀態。")

                    if prog["cur_sec"] >= prog["target_sec"]:
                        logger.info(f"   ✨ {Fore.GREEN}時數已達標！{Style.RESET_ALL}")
                        break

                # ⭐ 檢查點 6（frame 操作前）
                if not self.running:
                    logger.info("🛑 使用者手動停止（frame 操作前）")
                    return "STOP"

                try:
                    self.driver.switch_to.window(classroom_h)
                    self.driver.switch_to.default_content()
                except Exception:
                    new_classroom_h = self.find_classroom_window()
                    if new_classroom_h:
                        classroom_h = new_classroom_h
                        self.driver.switch_to.window(classroom_h)
                        self.driver.switch_to.default_content()

                is_traditional_frame = False
                try:
                    self.driver.switch_to.frame("s_catalog")
                    self.driver.switch_to.frame("pathtree")
                    is_traditional_frame = True
                    frame_fail_count = 0
                except Exception:
                    try:
                        self.driver.switch_to.default_content()
                    except Exception:
                        pass

                if is_traditional_frame:
                    all_links = [
                        link
                        for link in self.driver.find_elements(By.TAG_NAME, "a")
                        if link.text.strip()
                    ]
                    links = [
                        link for link in all_links
                        if link.text.strip() not in self.config["blacklist"]
                    ]
                    if not links:
                        all_texts = [link.text.strip() for link in all_links]
                        logger.warning(f"   ⚠️ pathtree 無可選單元，原始清單({len(all_texts)}筆): {all_texts[:20]}")
                    target = next(
                        (link for link in links if link.text not in attempted),
                        random.choice(links) if links else None,
                    )
                    if target is None and links:
                        logger.info("   🔄 所有單元已輪完，重置重新輪...")
                        attempted.clear()
                        target = random.choice(links)

                    if target:
                        if not self.running:
                            logger.info("🛑 使用者手動停止（進入單元前）")
                            return "STOP"

                        u_name = target.text.strip()
                        attempted.add(u_name)
                        logger.info(f"   📍 進入單元：{u_name[:20]}...")
                        self.driver.execute_script("arguments[0].click();", target)

                        w_time = self.config.get("residence_time", 75)
                        st = time.time()
                        while time.time() - st < w_time:
                            if not self.running:
                                logger.info("🛑 使用者手動停止（停留中）")
                                return "STOP"

                            time.sleep(1)
                            self.driver.switch_to.window(classroom_h)
                            self.driver.execute_script(
                                "function deepCommit(win){ try{if(win.API)win.API.LMSCommit('');}catch(e){} if(win.frames){for(let i=0;i<win.frames.length;i++)deepCommit(win.frames[i]);}} deepCommit(window);"
                            )
                    else:
                        for _ in range(30):
                            if not self.running:
                                return "STOP"
                            time.sleep(1)
                else:
                    # ── MOOCs / HTML5 / 微學習單頁教室處理 ──
                    alert_text = self._accept_alert_if_present()
                    err_text = f"{alert_text}"
                    current_url = ""
                    page_src = ""
                    try:
                        current_url = self.driver.current_url or ""
                        page_src = self.driver.page_source or ""
                    except Exception:
                        pass

                    # 💡 檢查是否有瀏覽器重新導向過多 (ERR_TOO_MANY_REDIRECTS) 或網路/伺服器錯誤
                    if (
                        "ERR_TOO_MANY_REDIRECTS" in page_src
                        or "重新導向的次數過多" in page_src
                        or "ERR_TOO_MANY_REDIRECTS" in current_url
                        or "ERR_NAME_NOT_RESOLVED" in page_src
                    ):
                        logger.warning(
                            f"   ⚠️ 「{course.get('caption', '')}」平臺網頁異常（重新導向次數過多 ERR_TOO_MANY_REDIRECTS），自動跳過並優先研習其他課程。"
                        )
                        self._mark_exam_manual_review(course, "平臺網頁異常（ERR_TOO_MANY_REDIRECTS 重新導向過多）")
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        return "SKIP"

                    # 💡 檢查是否為已完成/無法重複取得時數之課程（僅在確認通過或彈窗阻擋時）
                    if "/info/" in current_url and self._is_course_already_completed_on_info_page():
                        logger.info(
                            f"   🎉 課程「{course.get('caption', '')}」平臺已記錄為已修畢（通過狀態已通過），自動標記完成並略過。"
                        )
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        return "SKIP"

                    if self._is_logout_text(err_text) or self._is_logout_text(current_url):
                        logger.warning("🔄 帳號閒置或被重導至首頁/登入頁，停止當前教室並立即觸發重新登入。")
                        return "RELOGIN"

                    # 💡 若跳轉回平臺首頁或統計頁（非教室），停止本課程並略過
                    if any(
                        k in current_url
                        for k in ["mooc/index.php", "learn_stat.php", "learn_dashboard.php"]
                    ):
                        logger.warning(
                            f"   ⚠️ 「{course.get('caption', '')}」教室已關閉或跳轉回平臺首頁，停止本課程並優先研習其他課程。"
                        )
                        self._mark_exam_manual_review(course, "教室未開啟或跳轉回平臺首頁")
                        self._completed_in_session.add(str(course.get("course_id", "")))
                        return "SKIP"

                    frame_fail_count = 0

                    # 💡 若當前停留在 /info/ 介紹頁，嘗試點擊「上課去」進入真實教室
                    if "/info/" in current_url:
                        self.driver.execute_script("""
                            var btns = document.querySelectorAll('button, a.btn, a, input[type="button"], input[type="submit"]');
                            for (var i = 0; i < btns.length; i++) {
                                var t = (btns[i].innerText || btns[i].value || btns[i].textContent || '').trim();
                                var cleanT = t.replace(/\\s+/g, '');
                                var href = (btns[i].getAttribute('href') || '').toLowerCase();
                                var onclick = (btns[i].getAttribute('onclick') || '').toLowerCase();
                                if (['上課去', '進入課程', '開始上課', '前往教室', '繼續學習', '觀看影片', '前往研習', '開始學習', '前往學習', '選課', '我要選課'].some(k => cleanT.indexOf(k) !== -1)) {
                                    btns[i].click();
                                    break;
                                }
                                if (onclick.indexOf('goclass') !== -1 || onclick.indexOf('gotocourse') !== -1 || href.indexOf('action=learn') !== -1) {
                                    btns[i].click();
                                    break;
                                }
                            }
                        """)

                    # 💡 若當前停留在 Hahow /home 首頁，自動點擊當前課程或進入「我的學習」
                    if "hahow.in" in current_url and "/home" in current_url:
                        c_caption = str(course.get("caption", ""))[:8]
                        self.driver.execute_script(f"""
                            var links = document.querySelectorAll('a, button, [role="button"], .card, [class*="item"]');
                            var found = false;
                            for (var i = 0; i < links.length; i++) {{
                                var t = (links[i].innerText || links[i].textContent || '').trim();
                                if ('{c_caption}' && t.indexOf('{c_caption}') !== -1) {{
                                    links[i].click();
                                    found = true;
                                    break;
                                }}
                            }}
                            if (!found) {{
                                for (var j = 0; j < links.length; j++) {{
                                    var txt = (links[j].innerText || links[j].textContent || '').trim();
                                    if (txt.indexOf('我的學習') !== -1) {{
                                        links[j].click();
                                        break;
                                    }}
                                }}
                            }}
                        """)

                    # 尋找真實課程章節單元連結（含 Hahow / MOOCs 現代播放器）
                    moocs_links = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "a.unit-item, .chapter-list a, .tree-node a, a[href*='node'], a[onclick*='play'], a[onclick*='read'], li.leaf a, .course-outline a, .outline a, a.list-group-item, .unit-title, a[href*='catalog'], [class*='unit'] a, [class*='chapter'] a, a[href*='lecture'], [class*='LectureItem'], [class*='lecture-item'], button[class*='lecture'], div[role='button'][class*='item']"
                    )
                    if not moocs_links:
                        moocs_links = self.driver.find_elements(
                            By.XPATH,
                            "//a[contains(@href, 'node') or contains(@href, 'play') or contains(@href, 'unit') or contains(@href, 'catalog') or contains(@href, 'lecture') or contains(@class, 'unit') or contains(@class, 'chapter') or contains(@class, 'lecture')]"
                        )

                    # 排除非課程內容的通用導覽標籤（無效導航）
                    ignored_keywords = [
                        "跳到主要內容", ":::", "網站導覽", "常見問題", "下載專區", "加盟機關",
                        "簡易操作", "隱私權", "安全政策", "版權聲明", "回首頁", "選課中心",
                        "個人資料", "學習概況", "帳號管理", "登出", "登入", "我的課程", "問卷", "測驗"
                    ]
                    filtered_links = []
                    for a in moocs_links:
                        try:
                            t = a.text.strip()
                            if not t or len(t) < 2:
                                continue
                            if any(k in t for k in ignored_keywords):
                                continue
                            if t in self.config.get("blacklist", []):
                                continue
                            filtered_links.append(a)
                        except Exception:
                            continue

                    target = next(
                        (l for l in filtered_links if l.text.strip() not in attempted),
                        random.choice(filtered_links) if filtered_links else None
                    )
                    if target is None and filtered_links:
                        attempted.clear()
                        target = random.choice(filtered_links)

                    if target:
                        u_name = target.text.strip()
                        attempted.add(u_name)
                        logger.info(f"   📍 進入單元（MOOCs/Hahow）：{u_name[:25]}...")
                        try:
                            self.driver.execute_script("arguments[0].click();", target)
                        except Exception:
                            pass
                    else:
                        logger.info("   📍 正在播放課程影音內容（MOOCs/Hahow）...")

                    # 嘗試播放影片與觸發播放器
                    try:
                        self.driver.execute_script("""
                            function playAllVideos(doc) {
                                try {
                                    var vs = doc.querySelectorAll('video');
                                    for (var i = 0; i < vs.length; i++) {
                                        vs[i].muted = true;
                                        if (vs[i].paused) vs[i].play().catch(function(){});
                                    }
                                    var pbtn = doc.querySelector('[aria-label*="Play"], [aria-label*="播放"], button.vjs-big-play-button, .vjs-play-control, [class*="PlayButton"]');
                                    if (pbtn) { pbtn.click(); }
                                } catch(e){}
                                try {
                                    var iframes = doc.querySelectorAll('iframe');
                                    for (var j = 0; j < iframes.length; j++) {
                                        playAllVideos(iframes[j].contentDocument);
                                    }
                                } catch(e){}
                            }
                            playAllVideos(document);
                        """)
                    except Exception:
                        pass

                    w_time = self.config.get("residence_time", 75)
                    st = time.time()
                    while time.time() - st < w_time:
                        if not self.running:
                            logger.info("🛑 使用者手動停止（停留中）")
                            return "STOP"

                        time.sleep(1)
                        self.driver.switch_to.window(classroom_h)
                        self.driver.execute_script("""
                            function deepCommit(win){
                                try{if(win.API)win.API.LMSCommit('');}catch(e){}
                                try{
                                    var v = win.document.querySelector('video');
                                    if (v && v.paused) { v.muted = true; v.play().catch(function(){}); }
                                }catch(e){}
                                if(win.frames){for(let i=0;i<win.frames.length;i++)deepCommit(win.frames[i]);}
                            }
                            deepCommit(window);
                        """)

            # ⭐ 檢查點 11（結束前）
            if not self.running:
                logger.info("🛑 使用者手動停止（課程結束前）")
                return "STOP"

            # 時數達標，嘗試自動作答測驗，通過後填寫問卷（若問卷未完成）
            if self.running:
                is_skip = self.config.get("skip_exam_for_session", False)
                if is_skip:
                    logger.warning("本次已選擇跳過測驗；時數已達標，改為嘗試填寫問卷。")
                    q_ok = True
                    if str(course.get("fill", "0")) != "1":
                        q_ok = self.auto_questionnaire(course)
                        if not q_ok:
                            self._mark_exam_manual_review(course, "問卷填寫失敗，尚未確認完成")
                    else:
                        logger.info(f"   ✅ 「{course.get('caption', '')}」問卷先前已完成，跳過填寫。")

                    if q_ok:
                        c_id = str(course.get("course_id", course.get("id", "")))
                        self._completed_in_session.add(c_id)
                        self._mark_exam_manual_review(course, "本次跳過測驗，尚未確認完課")
                        try:
                            from utils.security import global_quota_tracker
                            from utils.course_dashboard import render_course_completion_card
                            api_after = global_quota_tracker.get_stats().get("used", 0)
                            card = render_course_completion_card(
                                course_name=course.get('caption', ''),
                                has_quiz=True,
                                quiz_passed=False,
                                survey_completed=True,
                                course_completed=False,
                                solve_mode="skipped",
                                course_api_calls=0,
                                today_api_calls=api_after,
                                daily_limit=global_quota_tracker.daily_limit,
                                session_completed=self._session_completed_count,
                                session_quiz_passed=getattr(self, "_session_quiz_passed_count", getattr(self, "_session_passed_count", 0)),
                                session_quiz_total=getattr(self, "_session_quiz_total_count", self._session_completed_count),
                            )
                            logger.info("\n" + card)
                        except Exception as e:
                            logger.warning(f"⚠️ 課程結案摘要產生失敗，不影響課程完成流程：{e}")
                else:
                    self._count_session_quiz_course(str(course.get("course_id", "")))
                    exam_passed = self.auto_exam(course)
                    if self.running and not exam_passed:
                        self._defer_exam_after_ai_outage(course)
                    if self.running and exam_passed:
                        q_ok = True
                        if str(course.get("fill", "0")) != "1":
                            q_ok = self.auto_questionnaire(course)
                            if not q_ok:
                                self._mark_exam_manual_review(course, "問卷填寫失敗，尚未確認完成")
                        else:
                            logger.info(f"   ✅ 「{course.get('caption', '')}」問卷先前已完成，跳過填寫。")

                        if q_ok:
                            c_id = str(course.get("course_id", course.get("id", "")))
                            self._completed_in_session.add(c_id)
                            self._session_completed_count = getattr(self, "_session_completed_count", 0) + 1
                            course_success = True
                            self._session_passed_count = getattr(self, "_session_passed_count", 0) + 1
                            self._session_quiz_passed_count = getattr(self, "_session_quiz_passed_count", 0) + 1
                            try:
                                from utils.security import global_quota_tracker
                                from utils.course_dashboard import render_course_completion_card
                                api_after = global_quota_tracker.get_stats().get("used", 0)
                                course_api = self._course_api_calls.get(str(course.get("course_id", "")), 0)
                                s_mode = "ai" if course_api > 0 else "quiz_bank"
                                card = render_course_completion_card(
                                    course_name=course.get('caption', ''),
                                    has_quiz=True,
                                    quiz_passed=True,
                                    survey_completed=True,
                                    course_completed=True,
                                    solve_mode=s_mode,
                                    course_api_calls=course_api,
                                    today_api_calls=api_after,
                                    daily_limit=global_quota_tracker.daily_limit,
                                    session_completed=self._session_completed_count,
                                    session_quiz_passed=self._session_quiz_passed_count,
                                    session_quiz_total=getattr(self, "_session_quiz_total_count", self._session_completed_count),
                                )
                                logger.info("\n" + card)
                            except Exception as e:
                                logger.warning(f"⚠️ 課程結案摘要產生失敗，不影響課程完成流程：{e}")


            logger.info("   🔄 返回學習概況清單...")
            self.driver.get(self.stat_url)
            if not self.safe_sleep(5):
                return "STOP"
            self.sync_session()
            return "SUCCESS" if course_success else "PENDING"

        except UnexpectedAlertPresentException as e:
            alert_text = ""
            try:
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                alert.accept()
                logger.info(f"ℹ️ 偵測並接受 Alert：{alert_text}")
            except Exception:
                alert_text = str(e)
            if "閒置" in alert_text or "重新登入" in alert_text or "登出" in alert_text:
                logger.warning("🔄 帳號閒置被登出，嘗試重新登入後繼續當前課程...")
                try:
                    self.driver.get(self.stat_url)
                except Exception:
                    pass
                time.sleep(3)
                if self.login():
                    logger.info("✅ 重新登入成功，將重試當前課程。")
                    return "RELOGIN"
                else:
                    logger.error("❌ 重新登入失敗，跳過當前課程。")
                    return "ERROR"
            elif any(kw in alert_text for kw in ["非本門課", "無法上課", "無權限", "不開放", "未選課", "尚未上架", "已下架", "直播已結束"]):
                logger.warning(f"⚠️ 此課程無法上課（{alert_text}），永久跳過。")
                self._completed_in_session.add(str(course.get("course_id", "")))
                try:
                    self.driver.get(self.stat_url)
                except Exception:
                    pass
                time.sleep(3)
                return "SKIP"
            elif any(kw in alert_text for kw in ["外購", "Hahow"]):
                logger.warning(f"   ⏩ 「{course.get('caption', '')}」為外購平臺課程（{alert_text}），自動略過並切換下一門課程。")
                self._completed_in_session.add(str(course.get("course_id", "")))
                try:
                    self.driver.get(self.stat_url)
                except Exception:
                    pass
                time.sleep(2)
                return "SKIP"
            elif any(kw in alert_text for kw in ["平臺", "平台", "閱讀", "磨課師", "提醒", "另開", "視窗", "即將進入"]):
                logger.info(f"   ℹ️ 外部平臺通知已自動確認（{alert_text}），重新進入教室...")
                return "RELOGIN"
            elif "登入" in alert_text:
                # 平臺閒置逾時登出：需真的重新登入，單純重進教室只會讓 API 回 0 筆
                logger.warning(f"   ⚠️ 研習期間被平臺登出（{alert_text}）")
                return "LOGGED_OUT"
            else:
                logger.warning(f"   ⚠️ 研習期間 Alert（{alert_text}），自動確認並重試...")
                return "RELOGIN"

        except Exception as e:
            err_str = str(e)
            if _is_driver_disconnect_error(err_str):
                err_line = (getattr(e, "msg", None) or err_str).splitlines()[0]
                logger.warning(f"   ⚠️ 瀏覽器視窗已關閉或連線中斷：{err_line}")
                return "DRIVER_LOST"
            logger.error(f"   ❌ 研習異常: {e}", exc_info=True)
            try:
                self.driver.get(self.stat_url)
            except Exception:
                pass
            time.sleep(5)
            return "ERROR"

