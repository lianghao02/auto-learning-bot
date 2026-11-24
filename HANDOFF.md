# HANDOFF

## 核心元資料 (Metadata)
- **Repository**：lianghao02/auto-learning-bot
- **Branch**：main
- **Commit SHA**：`5cefc669`（V2.2.0 後文件基準；工作目錄含 V2.2.1 候選維護修補待提交）
- **Skill Version**：lianghao-development v1.0.0
- **Task Type**：FIX
- **Local Path Hint**：07_auto-learning-bot

---

## 目前狀態
2026-11-24：基於 **V2.2.0** 實機執行日誌回饋與全專案 AUDIT 健檢，完成雙平臺穩定性、Gemini 3.5 Flash-Lite 升級與安全防線修補（尚未 commit，待使用者確認是否提交或發布 V2.2.1）。

## 本輪已完成修補 (Completed)
1. **e 等公務園登入、彈窗、下架課與測驗／問卷完整性**：
   - 支援我的E政府跨站 SSO 長時間跳轉等待與平臺 Fancybox 公告彈窗自動關閉。
   - 新增 `_wait_s_main_action_or_status()` 輪詢等待 `s_main` 框架載入；問卷逾時與必填 Alert 均回傳 `False`，不假宣告完課；連續 2 次找不到「進行測驗」按鈕標記待查核避免無限重抓。
   - 新增 `_detect_unavailable_course_on_info_page()`：於 `/info/` 介紹頁即時判讀平臺已下架／非上課期間課程（以無可用上課入口為前提防止誤殺），免除 15 秒空等並獨立摘要，不污染測驗待查核清單。
   - 測驗題庫預驗與模糊比對收緊：送 AI 前以 `_can_resolve_exam_answer()` 預驗題庫答案是否能對應當前頁面選項，無法對應者自動改納 AI 批次覆核；`_find_answer()` 模糊門檻提高至 `0.90`，強制檢查否定詞簽章一致且禁止單／多選題模糊配至純是非題。
   - 交卷結果頁未顯示單次分數時，自動回 `s_main` 測驗清單複查是否「已通過」（確認通過即接續填問卷；無滿分證據仍不寫入題庫）；抓正解僅限明確不及格且改用瀏覽器同源 `fetch` 根除跨分站 `school_hash` 衝突。
2. **Gemini 模型與備援鏈升級**：
   - 預設主模型升級至 `gemini-3.5-flash-lite`（舊設定自動平滑升級），跨節點備援鏈為 `gemini-3.5-flash-lite` → `gemini-3.6-flash` → `gemini-3.5-flash`，並對 3.5-flash-lite／3.6+ 自動省略已棄用的 `temperature` 參數。
3. **臺北 E 大長時數 Session 逾時自動恢復與執行鎖強化**：
   - `get_course_list()`、`get_course_modules()` 與 `get_scorm_player_url()` 偵測到登入逾時重導或首頁 `row_count=0` 時，自動重新登入並重建 `sso_moodle` 工作階段重試一次（單次上限）。
   - `.taipei_eda_course.lock` 移至 `data/` 目錄並改用 `psutil.pid_exists()` 取代 `os.kill(pid, 0)`。
4. **系統可靠性、資料安全與日誌治理**：
   - `usage_tracker.py` 將 `device_id` 獨立存於 `data/device_id.txt`，未開啟雲端同步時直接略過，徹底消除背景心跳讀寫例外覆寫 `config.json`（帳密與金鑰）之風險。
   - 拆出 `_close_driver_only()` 供 `_try_auto_healing()` 與停滯重啟使用，保留 `self.running` 與日誌 Handler；補齊 `no such window` 視窗關閉自動恢復。
   - 修復 `app.py` 備援題庫未定義 `base_dir` 之 `NameError`、`_update_db_from_gas()` 補齊 `GLOBAL_DB_LOCK` 與 `closing()`、`debug_*.log` 延後至 `run()` 建立（消除 0 bytes 空檔）並剝除 ANSI 色碼、弱參考集中管理 `atexit`/`signal`、`update_debug.log` 增加 1MB 輪替、`log_feed.py` 排除 WebDriver stacktrace 灌水 `issue_count`。

## 異動檔案 (Changed Files)
- 核心程式：`app.py`、`quiz_bank.py`、`taipei_eda_course.py`、`ui.py`、`usage_tracker.py`、`utils/log_feed.py`。
- 測試：`tests/test_ai_outage_handling.py`、`tests/test_egov_entry_and_usage.py`、`tests/test_log_feed.py`、`tests/test_quiz_safety_boundaries.py`、`tests/test_security.py`、`tests/test_taipei_scan_safety.py`。
- 文件：`HANDOFF.md`（另 `00_Dev-Control-Center/IMPROVEMENTS.md` 同步更新版本紀錄）。

## 驗證結果 (Validation)
- `python_embed\python.exe -B -s -W error -m py_compile`：全數修改檔零警告通過。
- `pwsh -NoProfile -File setup_and_run.ps1 -CheckOnly`：通過（Python 3.13.0，套件相依完整）。
- `pwsh -NoProfile -File scripts/run_tests.ps1`：全套 `unittest` 100% 通過（193 項測試）。
- `git diff --check`：通過。

## Git 狀態與下一步建議動作
- **Branch**：`main`（尚未 commit / push，保留供使用者實機驗收）。
- **下一步建議**：實機執行雙平臺確認剛交卷之兩門課問卷補填與整體流程順暢後，可提交變更並依需求打包發布 `V2.2.1`。
