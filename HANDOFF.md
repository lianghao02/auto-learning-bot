# HANDOFF

## 核心元資料 (Metadata)
- **Repository**：lianghao02/auto-learning-bot
- **Branch**：main
- **Commit SHA**：2294ecf9（本輪基準 SHA）
- **Skill Version**：v1.0.0
- **Task Type**：IMPROVE
- **Local Path Hint**：07_auto-learning-bot

---

## 目前狀態
1. 依最新全域開發憲法 v8.5、`product-design` 與 `windows-tool-ux` 完成全面審查與 P2/P3 改善。
2. 臺北 E 大 SCORM 播放器按鈕過濾、e等公務園 `/info/` 介紹頁完成狀態精準判定、測驗前教室狀態防禦均正常運作。
3. 單元測試擴充至 80 項，全數通過；`setup_and_run.ps1 -CheckOnly` 通過。

## 本輪目標
1. 對齊 `AGENTS.md` 技術棧描述（`PySide6 (Qt)`）與移除 `setup_and_run.ps1` 跨專案硬編碼路徑。
2. 補齊 `PlatformTabPanel` 課程狀態工作台之空狀態（Empty State）、掃描載入中狀態（Loading State）、`CourseStatus.color_hex` 語意色票與異常列珊瑚紅警示高亮（`#FDF2F2`）。
3. 強化 `AccountSettingsTabPanel`：新增密碼與 API Key 顯示／隱藏切換按鈕（`👁️`）、新增「雲端共用題庫同步與匿名統計（GAS 連線）」開關（連動 `quiz_bank.py` 與 `usage_tracker.py`），並實作未儲存變更偵測（`has_unsaved_changes`）與啟動前自動套用防呆。
4. 收斂 `GLOBAL_QSS` 莫蘭迪預設樣式，並修正視窗最小化行為（保留於 Windows 工作列，僅點擊 `X` 時縮至系統列）。

## 已完成 (Completed)
1. **文件與啟動器可攜性合規**：
   - `AGENTS.md` 主力 GUI 技術棧由 `Tkinter` 更正為 `PySide6 (Qt)`。
   - `setup_and_run.ps1` 移除對 `01_AG-MONITOR-Smart-Video-Screening` 之硬編碼路徑，改為動態探索鄰近目錄 `python_embed\_sqlite3.pyd`。
2. **工作台狀態視覺與空狀態補齊 (`ui.py`)**：
   - 新增 `empty_state_lbl` 空狀態與掃描中動態提示列，首筆課程進入時自動隱藏。
   - `course_table` 狀態欄套用 `CourseStatus.color_hex` 前景色與粗體；`MANUAL_REVIEW` 與 `ERROR` 異常列套用 `#FDF2F2` 警示底色。
   - 收斂 `GLOBAL_QSS`，解決原生對話框按鈕文字偏左與過度放大問題。
3. **設定面板防呆、密碼切換與雲端同步開關 (`ui.py`, `quiz_bank.py`, `usage_tracker.py`)**：
   - 為臺北 E 大密碼、e 等公務員密碼與 Gemini API Key 加上 `👁️` 明文／密碼切換按鈕。
   - 新增 `cloud_sync_cb` 開關（`cloud_sync_enabled`），支援停用外部 GAS 共用題庫與匿名統計連線。
   - 新增 `has_unsaved_changes()` 與啟動前靜默驗證儲存，防止修改設定後未按儲存即啟動導致設定未生效。
   - 修正 `MainWindow.changeEvent`，讓點擊 `_` 最小化維持於工作列，僅點擊 `X` 時縮至系統列。
4. **單元測試全數回歸通過**：
   - 新增 `test_empty_state_banner_transitions`、`test_account_settings_unsaved_changes_and_cloud_sync_toggle` 與異常列色票斷言。
   - 80 項單元測試全數 PASS。

## 異動檔案 (Changed Files)
- `AGENTS.md`
- `setup_and_run.ps1`
- `ui.py`
- `quiz_bank.py`
- `usage_tracker.py`
- `tests/test_interactive_quiz_dialog.py`
- `HANDOFF.md`

## 刻意未修改 (Do Not Do / Deliberately Omitted)
- 未修改個人帳號密碼、本機題庫資料與外部 API 設定。
- 未拆解穩定運作中之 `app.py` 單體檔案，維持最小必要修改原則。

## 尚未完成 (Remaining Work)
- **P1 (阻斷/必須)**：無。
- **P2 (重要/當次)**：無。
- **P3 (建議/後續)**：持續依平臺改版情況微調與維護。

## 驗證結果 (Validation)
- 執行 `.\python_embed\python.exe -B -s -m unittest discover -s tests -v`：80 項測試全數 PASS（0 失敗、0 錯誤）。
- 執行 `pwsh -NoProfile -File setup_and_run.ps1 -CheckOnly`：Runtime 與套件相依檢查通過。

