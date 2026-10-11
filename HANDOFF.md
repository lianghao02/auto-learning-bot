# HANDOFF

## 核心元資料 (Metadata)
- **Repository**：lianghao02/auto-learning-bot
- **Branch**：main
- **Commit SHA**：2294ecf9（本輪基準 SHA）
- **Skill Version**：v1.0.0
- **Task Type**：FIX
- **Local Path Hint**：07_auto-learning-bot

---

## 目前狀態
1. 臺北 E 大 SCORM 播放器按鈕過濾與重試修復完成。
2. e等公務園+學習平臺誤判「無法重複取得時數」導致未修畢課程被略過之重大 Bug 已修復，按鈕點擊與教室跳轉亦完成強化。
3. 單元測試已擴充至 78 項，全數通過。

## 本輪目標
1. 修復臺北 E 大 SCORM 播放器誤觸講義簡報按鈕問題。
2. 修復 e等公務園（egov）部分未上課程（如安寧緩和療護系列）在 `/info/` 介紹頁因內文含「無法重複取得時數」或「已完成此課程」靜態字串而被誤判為已修畢略過之問題。
3. 修正達標課程執行考試時停留在 `/info/` 頁面導致報錯之防禦邏輯。

## 基準與已確認事實 (Baseline & Confirmed Facts)
- 使用者提供真實截圖顯示：在 `elearn.hrd.gov.tw/mooc/user/learn_dashboard.php` 中「未完成(有時數)」共有 18 門，安寧緩和療護等課程測驗為 0 分、問卷未填、閱讀時數為 0，按鈕為「退選」或「上課去」，通過狀態為 `--`。
- `app.py` 先前直接在 `document.body.innerText` 或 `page_src` 中搜尋 `無法重複取得時數` 與 `已完成此課程`，因公務課程注意事項常態包含此文字，造成衛福部安寧系列 10 門課全數被秒跳過。
- 達標課程若因彈窗或跳轉延遲仍停留在 `/info/` 頁面，先前直接尋找測驗按鈕會拋出 NoSuchElementException。

## 已完成 (Completed)
1. **新增 `_is_course_already_completed_on_info_page` 精準判定**：
   - 鎖定「我的課程狀態」區塊，只有「通過狀態」明確為「已通過」或「通過」才認定為完成；若為 `--` 或「未通過」明確視為未完成。
   - 僅當 Modal / Alert 彈窗內明確提示「您已完成此課程」且「無法重複取得時數」時才視為平臺阻擋。
   - 徹底移除直接在整頁 body 內文粗暴全文搜尋關鍵字的誤殺邏輯。
2. **強化「上課去」與「進入課程」按鈕點擊**：
   - JavaScript 點擊器加入消除空白機制（防範「上 課 去」或換行標籤）。
   - 擴充匹配 `onclick`（如 `goClass`）與 `href`（如 `action=learn`），確保點擊成功率。
3. **測驗前教室狀態防禦**：
   - 在執行已達標測驗前，若確認仍停留在 `/info/` 介紹頁，嘗試尋找教室視窗；若仍未進入教室，記錄待人工查核並暫緩測驗，不再拋出找不到元素的錯誤。
4. **單元測試全數回歸通過**：
   - 新增 `test_info_page_static_text_cannot_mark_course_completed`。
   - 新增 `test_info_page_passed_status_marks_course_completed`。
   - 單元測試累積至 78 項，全數通過。

## 異動檔案 (Changed Files)
- `app.py`
- `taipei_eda_course.py`
- `tests/test_course_completion_logic.py`
- `tests/test_taipei_scan_safety.py`
- `HANDOFF.md`

## 刻意未修改 (Do Not Do / Deliberately Omitted)
- 未修改帳號密碼、題庫資料與外部 API 設定。
- 未更動可攜式打包環境或嵌入式 Python。

## 尚未完成 (Remaining Work)
- **P1 (阻斷/必須)**：無。
- **P2 (重要/當次)**：無。
- **P3 (建議/後續)**：持續依平臺改版情況微調與維護。

## 驗證結果 (Validation)
- 執行 `.\python_embed\python.exe -m unittest discover tests`：78 項測試全數 PASS（0 失敗、0 錯誤）。

## Git 狀態
- 本次修復內容已準備提交並推播至 `origin/main`。

