# HANDOFF

## 目前狀態
可交付（V2.0.0 版本基線與 main 分支已全面對齊，可攜版重新建置並通過驗證）

## 本輪目標
執行 **P1「版本與分支收斂任務」**：
1. 解決「GitHub Release 為 V2.0.0，但 main 分支與本機工作樹停留在 V1.1.0」之版本治理斷層。
2. 將線上最新 `origin/feature/v2.0-commercial-uiux`（V2.0.0 商業級架構）完整合併回 `main` 主幹。
3. 將本機開發的高價值成果（Compact Ribbon 緊湊操作列、In-Row Focus 表格行內焦點、日誌工具列、台灣繁體中文用語修訂、`scripts/run_tests.ps1` 測試執行器）疊加至 V2.0.0 基線。
4. 清理 `dist/` 歷史過期打包檔，重新產出對齊線上版本號之 `AdminEfficiencyPilot_V2.0.0_Portable.zip`。

## 已完成
### 1. P1 版本與分支完整對齊
- **分支關係收斂**：確認 `feature/v2.0-commercial-uiux` 是自 `main`（`cfb80f0b`）向前線性延伸之 5 個 commit，已成功透過 Fast-Forward 合併回 `main` 主幹分支。
- **全域版本號單一真理（Source of Truth）**：
  - `version.txt`：`V2.0.0`
  - `app.py`：`AdminEfficiencyPilot.VERSION = "V2.0.0"`
  - `README.md` & `CHANGELOG.md`：以 V2.0.0 為主要正式發行版本記錄
  - UI 視窗標題：`行政效能領航員 V2.0.0`
  - GitHub Release：對齊線上 [`V2.0.0`](https://github.com/lianghao02/auto-learning-bot/releases/tag/V2.0.0)

### 2. 核心功能與缺陷修復（繼承自 V2.0.0）
- **文字本位選項配對核心引擎（抗隨機重排題庫）**：
  - `utils/helpers.py` 實作 `match_radio_option_index` 與 `normalize_choice_text`，徹底解決平臺隨機重排選項時因純數字代號導致盲選錯誤的缺陷。
  - e 等公務園 AI 滿分存庫真實文字化（`app.py`）。
- **臺北 E 大待處理課程 NameError 阻斷修復**：
  - `taipei_eda_course.py` 補齊 `global_quota_tracker` 引用與雙重 `try...except` 容錯防禦。
  - 將標準輸出編碼配置標準化為 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`，根除重複建立 `TextIOWrapper` 導致之 `ValueError: I/O operation on closed file`。

### 3. 工作台 UI/UX 緊湊化與功能強化（本輪疊加成果）
- **Compact Ribbon（操作儀表列）**：合併平臺摘要與控制列，移除獨立佔位之 `focus_card`，大幅釋放垂直視野。
- **In-Row Focus（表格行內焦點）**：於課程佇列表格實作進行中課程前綴標記（`▶ `）、粗體字型、莫蘭迪淡雅背景色（`#EAF1EE`）與完整 Tooltip。
- **測驗模式選單文案收斂**：精簡文案並維持底層鍵值相容 `["sqlite", "interactive", "skip", "gemini_direct"]`。
- **日誌工具列**：於詳細執行紀錄頁籤新增 `[📋 複製紀錄]`、`[📁 開啟日誌資料夾]`、`[🧹 清空畫面]` 功能。
- **語言標準化**：介面、日誌與註解 100% 採用台灣標準繁體中文（如「即時除錯日誌」、「更新程式」）。

### 4. 測試套件與發行產物更新
- 新增 `scripts/run_tests.ps1`，提供具備 UTF-8 控制台編碼防禦與 `python_embed` 隔離環境注入之標準測試執行器。
- 清理 `dist/` 資料夾內過期之 8 月底歷史備份檔（`V3.1.0`、`V3.1.1`）。
- 成功重新建置 `dist/AdminEfficiencyPilot_V2.0.0_Portable.zip`（SHA-256: `d6ab5fa5297820bea3c7e205cf3aae759c3dc555a60caa3778592b4006d2defe`）。

## 刻意未修改
- 未改動核心業務邏輯：維持 Selenium 自動化流程、SCORM 倒數、題庫查詢與 AI 批次作答。
- 未更換底層技術棧（維持 Python 3.13 + 原生 PySide6）。

## 尚未完成
- 無阻斷性與重要問題。P1 版本治理錯亂已徹底排除。

## 驗證結果
### 已執行
1. **全套自動化單元與回歸測試**：
   - 指令：`pwsh -NoProfile -File scripts/run_tests.ps1`
   - 結果：`Ran 70 tests in 3.386s, OK`（**全套 70 項測試 100% 全數通過**）。
2. **可攜版獨立 Runtime 啟動檢驗**：
   - 透過 `dist/行政效能領航員_V2.0.0_Portable/current/runtime/python.exe` 實測載入 `ui.MainWindow`。
   - 視窗標題成功輸出：`行政效能領航員 V2.0.0`。
3. **離屏實例化檢驗**：
   - 驗證 Compact Ribbon、In-Row 表格高亮、測驗模式鍵值與無淘汰依賴殘留。

### 尚未驗證
- 實際 Windows 桌面 live 環境人工操作兩小時以上長效掛機。

### 已知風險
- 無阻斷性風險。舊設定檔 `data/config.json` 與題庫資料庫完全向下相容。

## Git 狀態
- Commit：`d3cbbc7a`
- Push：是（已成功推送至 `origin/main`，遠端預設分支與本機完全對齊）
- Working Tree：Clean
- Branch：main
- Release：GitHub Release `V2.0.0` 附件與 Release Notes 已全數更新同步

## 下一步
1. 隨時執行 `run.bat`，即可直接於桌面上體驗完整對齊之 V2.0.0 正式工作台。
2. 進行日常自動研習或長效掛機運作。
