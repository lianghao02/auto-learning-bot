# HANDOFF

## 核心元資料 (Metadata)
- **Repository**：lianghao02/auto-learning-bot
- **Branch**：main
- **Commit SHA**：434f87507d6fa9b635e5074e1daf2351a92eada0（本輪提交前基準；最新提交以 `git log -1` 為準）
- **Skill Version**：v1.0.0
- **Task Type**：AUDIT + IMPROVE + FIX
- **Local Path Hint**：07_auto-learning-bot

---

## 目前狀態
可交付（已提交本機，未推送、未發布）

## 本輪目標
1. 分析專案並依使用者提供的雙平臺執行日誌檢查問題。
2. 確認外部 API 是否正常。
3. 日誌台改為最適合的呈現方式（兩平臺格式不一致、心跳訊息洗版）。
4. UI 改為遊戲感更重的 2D Q 版，並重新調整配色。

## 基準與已確認事實 (Baseline & Confirmed Facts)
- 基準 HEAD `434f875`（V2.0.1 + 前一輪 2D Q 版工作台），工作目錄乾淨，86 項測試通過。
- API 實測（2026-10-21）：
  - GAS 共用題庫：HTTP 200，`taipei_quiz_get` course_id=3180 回 10 題。
  - Gemini：設定檔中的 `gemini-2.0-flash-lite` 已下架（404）；程式在批次作答與 fallback 路徑會自動改用 `gemini-3.1-flash-lite`，實測 200 正常。`gemini-3.5-flash` 亦正常。
  - GitHub Release API：HTTP 200，最新 V2.0.1。
  - e等 課程 API 主機可連（未登入回 403 屬正常）；臺北E大、ECPA、我的E政府以 Python requests 驗證憑證失敗，但這些頁面由 Chrome 操作，不影響執行。
- 日誌中 e等「API 回傳 0 筆」是平臺閒置登出所致，第二次重新登入後恢復 682 筆。

## 已完成 (Completed)
- **冒險日誌**：新增 `utils/log_feed.py` 統一解析兩平臺格式；研習心跳改為即時卡片，只留 25% 里程碑；分類膠囊、5 種篩選、重複訊息合併 ×N、警告徽章、捲動時不強制拉回底部。
- **配色與遊戲感**：`utils/office_theme.py` 改為晴空糖果配色（色票集中為常數），墨藍粗外框、厚底按鈕、陽光黃選中分頁、深色日誌。
- **修正**（細節見 CHANGELOG 未發布區塊）：
  - 臺北E大成績解析與審閱頁推算。
  - 審閱頁未公布對錯時不回寫共用題庫。
  - `pending_ai_batch` 作用域錯誤。
  - 儀表板作答方式與通過狀態誤報。
  - 單次研習上限短於目標時數。
  - SCORM 章節點擊失敗刷屏，以及日誌輪替。
  - e等 閒置登出改為直接重新登入。
  - `[DOM]` 診斷訊息降為 DEBUG，並修正舊 Gemini 模型名稱。

## 異動檔案 (Changed Files)
- `quiz_bank.py`、`taipei_eda_course.py`、`app.py`
- `ui.py`、`utils/office_theme.py`、`utils/log_feed.py`（新）、`icons/office/combo-arrow.svg`
- `tests/test_log_feed.py`（新，11 項）、`tests/test_office_theme.py`、`tests/test_interactive_quiz_dialog.py`、`tools/office_ui_qa.py`
- `CHANGELOG.md`、`HANDOFF.md`

## 刻意未修改 (Do Not Do / Deliberately Omitted)
- 未更換自動化引擎，也未修改版本號、`python_embed`、`dist/` 與 `data/config.json`。
- 設定檔中的 `ai_model` 仍是 `gemini-2.0-flash-lite`。程式執行時會自動改用新模型；使用者若在設定頁重新儲存，也會寫回新值。

## 尚未完成 (Remaining Work)
- **P1**：無。
- **P2**：e等「精神疾病與家庭暴力議題」「老人福利服務」停在介紹頁、無法進入教室，需以真實帳號在瀏覽器確認是否為課程未開放或報名狀態問題。
- **P3**：
  - e等 待上課程預覽名稱截斷在 13 字（如「(一般」「《CED」），屬顯示問題。
  - `ui.py` 各元件仍有舊的行內樣式，會被主題覆蓋，日後可再收斂。

## 驗證結果 (Validation)
### 已執行測試與結果
- 執行 `python_embed\python.exe -m unittest discover -s tests`：97 項全部通過（原 86 項，新增 11 項）。新增測試涵蓋：
  - 日誌整理器
  - 成績格式解析
  - 題庫滿分不中斷
  - 審閱頁推算
  - 成績無法判讀時不重考
  - 真的未及格仍重考 3 次
- 執行 `tools/office_ui_qa.py`：1366×768（1.0／1.25／1.5 倍縮放）與 1920×1080 皆為 `errors: []`。已逐張檢視課程表、日誌、設定頁的截圖。
- 以實際 `taipei_eda_course.log` 末 4,000 行餵入日誌整理器：整理為 242 筆，篩選分布合理。
### 尚未驗證項目
- 真實平臺端到端執行，包含成績推算路徑與 e等 閒置重新登入路徑。
### 已知風險 (Known Risks)
- 本機的 `data/logs/taipei_eda_course.log` 已在本輪輪替為 `.log.1`（43MB 舊檔保留，未刪除）。

## Git 狀態
- Commit：見 `git log -1`（fix: 修正臺北E大成績判定並改版冒險日誌與 Q 版配色）
- Push：否
- Working Tree：Clean
- Branch：main

## 下一步建議動作 (Next Recommended Action)
1. 使用者確認畫面與日誌呈現。
2. 提交本輪修改。
3. 以真實帳號跑一輪臺北E大測驗，確認成績判定。

## 發布狀態 (Release Status)
待使用者確認（尚未升版與打包）
