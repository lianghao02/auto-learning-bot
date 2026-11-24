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


class EgovAuthMixin:
    """WebDriver 啟動、eCPA／我的E政府登入、Session 保養與自癒恢復。"""

    def toggle_chrome_visibility(self, show: bool):
        """控制 Chrome 視窗顯示與隱藏"""
        self._is_chrome_hidden = not show
        if hasattr(self, "driver") and self.driver:
            set_driver_window_visibility(self.driver, show)

    def _auto_hide_popups_if_needed(self, *, settle: bool = False):
        """若目前處於隱藏模式，自動連同新開的考試與問卷彈出視窗一併無痕隱藏"""
        if getattr(self, "_is_chrome_hidden", False) and hasattr(self, "driver") and self.driver:
            try:
                if settle:
                    maintain_driver_windows_hidden(self.driver)
                else:
                    set_driver_window_visibility(self.driver, False)
            except Exception:
                pass

    def _try_auto_healing(self, reason_msg: str) -> bool:
        """全自動靜默修復 (Auto-Healing) 網絡與 WebDriver 連線異常，防護網最多重試 3 次"""
        if not getattr(self, "running", True):
            return False
        if getattr(self, "_auto_healing_count", 0) >= 3:
            logger.error(f"❌ 已達到 Auto-Healing 最大自動修復重連上限 (3 次)，自動安全暫停以保護資源。原因：{reason_msg}")
            return False

        self._auto_healing_count = getattr(self, "_auto_healing_count", 0) + 1
        logger.warning(f"🔄 偵測到連線異常（{reason_msg}），正在啟動全自動靜默修復 (Auto-Healing 第 {self._auto_healing_count}/3 次)...")

        try:
            # 1. 僅清理舊死 Driver 資源（保留 self.running 與日誌 Handler）
            self._close_driver_only()
            time.sleep(2)

            # 2. 重新初始化 WebDriver 引擎
            if not self.init_engine():
                logger.error("❌ Auto-Healing：引擎重建失敗")
                return False

            # 3. 自動重新登入
            if not self.login():
                logger.error("❌ Auto-Healing：重新登入失敗")
                return False

            logger.info("✅ Auto-Healing：瀏覽器連線已成功靜默修復，恢復修課流程！")
            return True
        except Exception as e:
            logger.error(f"❌ Auto-Healing 過程發生例外: {e}")
            return False


    def _get_driver_path(self):
        """取得 ChromeDriver 路徑，子類可覆寫此方法實作不同策略。"""
        return os.path.abspath(download_best_chromedriver())

    def init_engine(self):
        self.kill_orphan_drivers()
        try:
            driver_path = self._get_driver_path()
            if not os.path.exists(driver_path):
                logger.error(f"找不到驅動程式檔案: {driver_path}")
                return False

            logger.info("🚀 正在啟動輔助引擎...")
            options = Options()
            options.add_argument("--mute-audio")
            # 加速啟動
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-background-networking")
            options.add_argument("--disable-sync")
            options.add_argument("--no-first-run")
            options.add_argument("--no-default-browser-check")
            options.add_argument("--disable-default-apps")

            # ⭐ 關鍵：從 self.config 直接讀取
            headless_mode = self.config.get("headless", True)
            self._is_chrome_hidden = bool(headless_mode)

            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-background-timer-throttling")
            options.add_argument("--disable-backgrounding-occluded-windows")
            options.add_argument("--disable-renderer-backgrounding")

            if headless_mode:
                logger.info("⚙️ 使用無痕背景模式（背景執行，可隨時點擊「👁️ 顯示瀏覽器」查看）")
            else:
                logger.info("🖥️ 使用桌面顯示模式（視窗保持可見）")

            self._driver_service = Service(driver_path)
            if sys.platform == "win32":
                import subprocess
                self._driver_service.creation_flags = subprocess.CREATE_NO_WINDOW

            self.driver = webdriver.Chrome(
                service=self._driver_service, options=options
            )
            if self._driver_service.process:
                self._managed_pids.add(self._driver_service.process.pid)

            if headless_mode and sys.platform == "win32":
                set_driver_window_visibility(self.driver, False)

            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            self.wait = WebDriverWait(self.driver, 30)
            logger.info(f"✅ 引擎就緒：{Fore.GREEN}{self.version}{Style.RESET_ALL}")
            return True
        except Exception as e:
            logger.error(f"引擎初始化失敗: {e}")
            return False

    def sync_session(self) -> bool:
        if not self.driver:
            logger.error("sync_session: driver 尚未初始化，無法同步 session")
            return False
        try:
            self.http_session.cookies.clear()
            for cookie in self.driver.get_cookies():
                self.http_session.cookies.set(
                    cookie["name"], cookie["value"], domain=cookie["domain"]
                )

            # 動態獲取 User-Agent 並移除 Headless 標記
            raw_ua = self.driver.execute_script("return navigator.userAgent")
            clean_ua = raw_ua.replace("HeadlessChrome", "Chrome")

            self.http_session.headers.update(
                {
                    "User-Agent": clean_ua,
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Origin": "https://elearn.hrd.gov.tw",
                    "Referer": self.stat_url,
                }
            )
            return True
        except Exception as e:
            logger.error(f"sync_session 失敗: {e}")
            return False

    def _proactive_session_refresh(self) -> bool:
        """🧹 主動定期 Session 保養與全新登入：清除積累之髒污 Cookie，獲取全新 SSO 憑證。"""
        logger.info("🧹 執行主動定期 Session 保養：清理全站 Cookie 並重新登入...")
        try:
            if self.driver:
                try:
                    handles = list(self.driver.window_handles)
                    if len(handles) > 1:
                        for h in handles[1:]:
                            self.driver.switch_to.window(h)
                            self.driver.close()
                        self.driver.switch_to.window(handles[0])
                except Exception:
                    pass
                try:
                    self.driver.delete_all_cookies()
                except Exception:
                    pass

            self.http_session.cookies.clear()
            login_ok = self.login()
            if login_ok:
                self.sync_session()
                self._last_session_refresh_time = time.time()
                self._course_relogin_counts.clear()
                logger.info("✅ 主動 Session 保養與全新登入完成，憑證已刷新。")
                return True
            else:
                logger.warning("⚠️ 主動 Session 保養重登失敗，稍後將依常規機制重試。")
                return False
        except Exception as e:
            logger.warning(f"⚠️ 主動 Session 保養發生異常: {e}")
            return False

    @staticmethod
    def _is_logout_text(text) -> bool:
        text = str(text or "")
        if not text:
            return False
        # 排除正常的 MOOCs 課程/首頁路徑
        if "mooc/index.php" in text and "login" not in text.lower() and "clogin" not in text.lower():
            return False
        return any(kw in text for kw in ("帳號閒置", "系統閒置", "重新登入", "請先登入", "請登入", "登入後再學習", "登入會員", "clogin.aspx", "sys_login.php", "/login.php"))

    def _accept_alert_if_present(self) -> str:
        try:
            alert = self.driver.switch_to.alert
            alert_text = alert.text
            alert.accept()
            return alert_text or ""
        except NoAlertPresentException:
            return ""
        except Exception as e:
            return str(e)


    def recover_login_session(self, reason="session 失效") -> bool:
        logger.warning(f"🔄 {reason}，嘗試重新登入並同步 API session...")
        try:
            self._accept_alert_if_present()
        except Exception:
            pass
        try:
            self.driver.get(self.stat_url)
            self.safe_sleep(2)
        except Exception:
            pass
        if not self.login():
            logger.error("❌ 重新登入失敗，無法恢復 API session。")
            return False
        if not self.sync_session():
            logger.error("❌ 重新登入後 session 同步失敗。")
            return False
        logger.info("✅ 重新登入並同步 session 完成。")
        return True


    @staticmethod
    def _is_elearn_logged_in_url(url: str, check_no_login: bool = False) -> bool:
        """確認已落地 elearn.hrd.gov.tw 且非登入／SSO 認證中繼頁。"""
        lowered = str(url or "").lower()
        if "elearn.hrd.gov.tw" not in lowered:
            return False
        if any(k in lowered for k in ("egov_login", "clogin", "sys_login", "/login.php")):
            return False
        if check_no_login and "login" in lowered:
            return False
        return True

    def _find_first_visible(self, selectors: list, timeout: float = 15.0):
        """在單一總時限內輪詢候選選擇器，回傳第一個可見元素。"""
        deadline = time.time() + max(0.5, float(timeout))
        while time.time() <= deadline:
            if not getattr(self, "running", True):
                return None
            for by_type, val in selectors:
                try:
                    for elem in self.driver.find_elements(by_type, val):
                        if elem and elem.is_displayed():
                            return elem
                except Exception:
                    continue
            time.sleep(0.25)
        return None

    def _detect_egov_login_error(self) -> str:
        """檢查我的E政府頁面是否已回傳明確登入錯誤訊息（避免無謂乾等逾時）。"""
        try:
            url = (self.driver.current_url or "").lower()
            if "cp.gov.tw" not in url:
                return ""
            text = self.driver.execute_script(
                "return document.body ? document.body.innerText : '';"
            ) or ""
        except Exception:
            return ""

        for kw in ("帳號或密碼錯誤", "密碼錯誤", "帳號不存在", "帳號已鎖定", "帳號停用", "登入失敗", "請輸入帳號", "請輸入密碼"):
            if kw in text:
                return kw
        return ""

    def _dismiss_announcement_modals(self) -> int:
        """關閉 e等公務園登入後彈出的最新消息／資安提醒等覆蓋式 Modal（點擊 × / Close）。"""
        if not self.driver:
            return 0
        try:
            closed = self.driver.execute_script(
                r"""
                var count = 0;
                function isVisible(el) {
                    if (!el) return false;
                    var s = window.getComputedStyle(el);
                    return s.display !== 'none' && s.visibility !== 'hidden' &&
                        s.opacity !== '0' && el.getClientRects().length > 0;
                }
                var dialogs = document.querySelectorAll(
                    '.modal.in, .modal.show, .modal[style*="display: block"], ' +
                    'div[role="dialog"], .ui-dialog, .fancybox-container, #fancybox-wrap, .fancybox-wrap'
                );
                for (var i = 0; i < dialogs.length; i++) {
                    var dlg = dialogs[i];
                    if (!isVisible(dlg)) continue;
                    var btns = dlg.querySelectorAll(
                        'button[data-fancybox-close], .fancybox-close-small, .fancybox-close, ' +
                        'button.close, button[data-dismiss="modal"], button[data-bs-dismiss="modal"], ' +
                        'button[aria-label="Close"], .ui-dialog-titlebar-close, ' +
                        'button, a.close, a[role="button"]'
                    );
                    for (var j = 0; j < btns.length; j++) {
                        var b = btns[j];
                        if (!isVisible(b)) continue;
                        var txt = (b.innerText || b.textContent || '').replace(/\s+/g, '').toLowerCase();
                        var aria = (b.getAttribute('aria-label') || b.getAttribute('title') || '').toLowerCase();
                        var cls = (b.className || '').toLowerCase();
                        if (
                            b.hasAttribute('data-fancybox-close') ||
                            cls.indexOf('close') !== -1 ||
                            b.getAttribute('data-dismiss') === 'modal' ||
                            b.getAttribute('data-bs-dismiss') === 'modal' ||
                            aria === 'close' || aria === '關閉' ||
                            txt === 'close' || txt === '×' || txt === '✕' || txt === 'x' || txt === '關閉'
                        ) {
                            b.click();
                            count++;
                            break;
                        }
                    }
                }
                return count;
                """
            )
            if closed:
                logger.info(f"ℹ️ 已自動關閉 {closed} 個平臺公告彈窗")
            return int(closed or 0)
        except Exception:
            return 0

    def _wait_for_redirect_and_sync(
        self,
        success_msg: str,
        check_no_login: bool = False,
        timeout_seconds: int = 180,
    ) -> bool:
        """等待重新導向至 elearn.hrd.gov.tw 後同步 session（登入共用邏輯）"""
        max_steps = max(1, int(timeout_seconds / 0.5))
        start_ts = time.time()
        last_progress_sec = 0

        for _ in range(max_steps):
            if not self.running:
                logger.info("🛑 使用者手動停止（登入中）")
                return False
            try:
                url = self.driver.current_url
            except UnexpectedAlertPresentException:
                alert_text = self._accept_alert_if_present()
                if alert_text:
                    logger.info(f"ℹ️ 登入提示：{alert_text}")
                    if any(kw in alert_text for kw in ("錯誤", "失敗", "鎖定", "停用", "無效")):
                        logger.error(f"❌ 登入遭到拒絕：{alert_text}")
                        return False
                time.sleep(0.5)
                continue
            except Exception:
                time.sleep(0.5)
                continue

            if self._is_elearn_logged_in_url(url, check_no_login=check_no_login):
                logger.info(success_msg)
                self._dismiss_announcement_modals()
                self.driver.get(self.stat_url)
                if not self.safe_sleep(3):
                    return False
                self._dismiss_announcement_modals()
                try:
                    landed_url = self.driver.current_url or ""
                    if not self._is_elearn_logged_in_url(landed_url, check_no_login=True):
                        logger.warning(f"⚠️ 導向學習統計頁後仍停留在登入頁（{landed_url}），判定登入未完成。")
                        return False
                except Exception:
                    pass
                return bool(self.sync_session())

            egov_err = self._detect_egov_login_error()
            if egov_err:
                logger.error(f"❌ 我的E政府回應錯誤：{egov_err}")
                return False

            elapsed = int(time.time() - start_ts)
            if elapsed >= last_progress_sec + 15:
                last_progress_sec = elapsed
                logger.info(f"⏳ 正在等待平臺單一登入回應（已等待 {elapsed} 秒）...")
            time.sleep(0.5)

        logger.error(f"❌ 等待平臺單一登入逾時（超過 {timeout_seconds} 秒，最後頁面: {getattr(self.driver, 'current_url', '')}）")
        return False

    def login(self):
        login_type = self.config.get("login_type", "ecpa")

        if login_type == "egov":
            return self.login_egov()
        else:
            return self.login_ecpa()

    def login_ecpa(self):
        try:
            logger.info("🔑 正在對接 eCPA 登入系統...")
            self.driver.get(self.ecpa_url)
            self.wait.until(EC.presence_of_element_located((By.ID, "aliasid")))

            user_f = self.driver.find_element(By.ID, "aliasid")
            pass_f = self.driver.find_element(By.ID, "pas")

            for c in self.config["account"]:
                user_f.send_keys(c)
                time.sleep(random.uniform(0.01, 0.03))

            for c in self.config["password"]:
                pass_f.send_keys(c)
                time.sleep(random.uniform(0.01, 0.03))

            self.driver.execute_script(
                "document.querySelector('#idarea button').click();"
            )

            return self._wait_for_redirect_and_sync(
                "✅ 系統身分驗證成功！", check_no_login=True
            )

        except Exception as e:
            logger.error(f"登入異常: {e}")
            return False

    def login_egov(self):
        try:
            logger.info("🔑 使用我的E政府登入...")
            try:
                self.driver.set_page_load_timeout(180)
            except Exception:
                pass

            self.driver.get(
                "https://www.cp.gov.tw/portal/Clogin.aspx?ReturnUrl=https://elearn.hrd.gov.tw/egov_login.php&ver=Simple&Level=1"
            )
            if not self.safe_sleep(1):
                return False

            # 💡 檢查點：若已經自動完成 SSO 導回 elearn.hrd.gov.tw 真正已登入頁，直接同步 Session
            cur_url = self.driver.current_url
            if self._is_elearn_logged_in_url(cur_url, check_no_login=True) and "mooc/index.php" not in cur_url:
                logger.info("✅ 偵測到 E政府已具備有效 SSO 授權，直接同步 Session。")
                return self.sync_session()

            user_selectors = [
                (By.ID, "AccountPassword_simple_txt_account"),
                (By.CSS_SELECTOR, "input[placeholder*='帳號']"),
                (By.CSS_SELECTOR, "input[id*='account']"),
                (By.CSS_SELECTOR, "input[type='text']"),
            ]
            pass_selectors = [
                (By.ID, "AccountPassword_simple_txt_password"),
                (By.CSS_SELECTOR, "input[type='password']"),
                (By.CSS_SELECTOR, "input[placeholder*='密碼']"),
                (By.CSS_SELECTOR, "input[id*='password']"),
            ]

            user_f = self._find_first_visible(user_selectors, timeout=15.0)
            if user_f is None and self._is_elearn_logged_in_url(self.driver.current_url, check_no_login=True):
                return self.sync_session()
            pass_f = self._find_first_visible(pass_selectors, timeout=8.0) if user_f else None

            if not user_f or not pass_f:
                if self._is_elearn_logged_in_url(self.driver.current_url, check_no_login=True):
                    return self.sync_session()
                logger.error(f"❌ 找不到我的E政府帳號或密碼輸入框（當前頁面: {self.driver.current_url}）")
                return False

            user_f.clear()
            user_f.send_keys(str(self.config["account"]))
            time.sleep(0.2)

            pass_f.clear()
            pass_f.send_keys(str(self.config["password"]))
            time.sleep(0.2)

            btn_selectors = [
                (By.ID, "AccountPassword_simple_btn_LoginHandler"),
                (By.CSS_SELECTOR, "input[type='submit']"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.CSS_SELECTOR, "a.btn-login"),
                (By.XPATH, "//a[contains(text(), '登入')]"),
                (By.XPATH, "//button[contains(text(), '登入')]"),
                (By.XPATH, "//input[@value='登入']"),
            ]
            login_btn = self._find_first_visible(btn_selectors, timeout=5.0)

            logger.info("📤 已送出我的E政府帳密，等待跨站單一登入跳轉（伺服器回應約需 20～110 秒，請稍候）...")
            if login_btn:
                try:
                    # 透過非阻塞 setTimeout 觸發點擊，讓等待與停止旗標檢查立即接手，不卡在同步 page load
                    self.driver.execute_script(
                        "var btn = arguments[0]; setTimeout(function(){ btn.click(); }, 50);",
                        login_btn,
                    )
                except Exception:
                    try:
                        login_btn.click()
                    except Exception:
                        pass
            else:
                try:
                    pass_f.submit()
                except Exception:
                    pass

            return self._wait_for_redirect_and_sync(
                "✅ E政府登入成功", check_no_login=True, timeout_seconds=180
            )

        except Exception as e:
            logger.error(f"E政府登入失敗: {e}")
            return False

