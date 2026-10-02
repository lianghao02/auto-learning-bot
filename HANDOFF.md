# HANDOFF

## 目前狀態
可交付（V2.0.1 正式發布完成，包含 Compact Ribbon 緊湊操作列、In-Row Focus 表格行內焦點、抗隨機重排題庫核心，全套 70 項測試通過，可攜版完成建置）

## 本輪目標
執行 **V2.0.1 正式版本發布（Release）流程**：
1. 解決既有使用者因版本號未遞增而無法觸發軟體內建「自動更新」之問題。
2. 推進版本號至 `V2.0.1`，讓所有使用者啟動時皆能即時收到更新通知並升級至最新工作台。
3. 重新建置免安裝可攜版 `AdminEfficiencyPilot_V2.0.1_Portable.zip` 並產生 SHA-256 校驗檔。
4. 建立 Git Tag `V2.0.1`，推送至遠端並建立 GitHub Release `V2.0.1`。

## 已完成
### 1. 全域版本號單一真理（Source of Truth）推進
- `version.txt`：`V2.0.1`
- `app.py`：`AdminEfficiencyPilot.VERSION`（動態讀取 `version.txt`）= `V2.0.1`
- `ui.py`：視窗標題與版本徽章動態對齊 = `V2.0.1`
- `README.md` & `CHANGELOG.md`：全面更新至 `V2.0.1` 規格與操作指引

### 2. 工作台 UI/UX 緊湊化與功能強化
- **Compact Ribbon（操作儀表列）**：合併平臺摘要與控制列，移除獨立佔位之卡片，垂直空間釋放逾 150px。
- **In-Row Focus（表格行內焦點）**：於課程佇列表格實作進行中課程前綴標記（`▶ `）、粗體字型、莫蘭迪淡雅背景色（`#EAF1EE`）與完整 Tooltip。
- **測驗模式選單文案收斂**：精簡文案並維持底層鍵值相容 `["sqlite", "interactive", "skip", "gemini_direct"]`。
- **日誌工具列**：於詳細執行紀錄頁籤新增 `[📋 複製紀錄]`、`[📁 開啟日誌資料夾]`、`[🧹 清空畫面]` 功能。
- **語言標準化**：介面、日誌、註解與說明文件 100% 採用台灣標準繁體中文。

### 3. 可攜版發行資產建置
- 執行 `scripts/build_portable_release.py`，成功打包：
  - `dist/AdminEfficiencyPilot_V2.0.1_Portable.zip`（451,351,609 bytes）
  - SHA-256 校驗碼：`3394045934b0c906be59b595d79cc9be33263028c376326fdb24b2ecc576922f`
- 清理 `dist/` 內舊版 V2.0.0 打包暫存。

### 4. 驗證結果
- **自動化測試**：`pwsh -NoProfile -File scripts/run_tests.ps1`，**70 項測試 100% 通過（OK）**。
- **Runtime 離線驗證**：嵌入式 Python 3.13 離線匯入與執行正常。

## 刻意未修改
- 未改動核心業務邏輯：維持 Selenium 自動化流程、SCORM 倒數、題庫查詢與 AI 批次作答。
- 未更換底層技術棧（維持 Python 3.13 + 原生 PySide6）。

## 尚未完成
- 無阻斷性與重要問題。

## Git 狀態
- Commit：`8f0af0df`
- Push：是（已成功推送至 `origin/main`，遠端完全同步）
- Working Tree：Clean
- Branch：main
- Tag：`V2.0.1`（已推播至遠端）
- Release：[GitHub Release V2.0.1](https://github.com/lianghao02/auto-learning-bot/releases/tag/V2.0.1) 正式發布完成（狀態：Latest）

## 下一步
1. 既有使用者啟動軟體時，將可自動偵測到 `V2.0.1` 並觸發一鍵更新升級。
2. 隨時可執行 `run.bat` 或免安裝可攜版於桌面體驗最新商業級緊湊工作台。
