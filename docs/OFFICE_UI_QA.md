# 2D Q 版辦公室靜態 UI 驗證

日期：2026-10-20。基準：`main` / `6ae6750f6afa698731eb7a9e9ca02c1b3dfb4766`。版本：`V2.0.1`（未變更）。

## 基準與範圍

- 任務開始時工作樹乾淨，`main` 與本機 `origin/main` 對齊。
- GitHub Release API 已確認 V2.0.1 為最新正式版本；V2.0.0 亦為正式版本，未回到 V1.1.0 重做。
- V2.0.0 Tag：`7b0f083ff63545196bfd27449d82093764c8e312`；V2.0.1 Tag：`affef266f8482d8b5b2e91396f5c490301b59a25`。
- HEAD 相較 V2.0.0 原有 21 個檔案差異、相較 V2.0.1 原有 18 個檔案差異，皆為已提交的既有修正；本輪未回復或混入其他未提交工作。
- 已讀取全域／專案 AGENTS、HANDOFF、README、version、課程模型與 UI 測試；專案沒有 MEMORY 或既有實作計畫。
- `app.py`、Selenium、登入、Session、SCORM、計時、測驗、問卷、SQLite、GAS、Gemini、更新驗證邏輯與版本均未修改。

## 修改檔案與素材

| 檔案 | 用途 |
|---|---|
| `ui.py` | 緊湊人物摘要、已載入課程完成比例、原生版面與主題接線、高 DPI 尺寸、帳號顯示收斂、首次使用橫幅 |
| `utils/office_theme.py` | 奶油白、鼠尾草綠、木棕與藍灰 QSS、靜態人物等比例載入 |
| `icons/office/office_assistant.png` | 使用者概念圖裁切的 122 × 105 透明 PNG |
| `icons/office/README.md` | 裁切座標、來源、限制與用途 |
| `tests/test_office_theme.py` | 3 項新增的接線、摘要更新與素材／帳號顯示測試 |
| `tools/office_ui_qa.py` | 合成資料與原生 Windows Qt 的解析度／縮放檢查 |
| `docs/OFFICE_UI_QA.md` | 本次驗證與未驗證範圍 |
| `HANDOFF.md` | 維護交接斷點 |

附件是完整 JPEG 介面概念圖，並非透明 Sprite Sheet；本輪依指定方向只擷取小型人物與筆電，沒有下載其他美術、沒有新增執行階段依賴。背景與控制項由 Qt Layout／QSS 繪製，沒有固定全圖背景或絕對座標控制項。沒有新增動畫、粒子或遊戲引擎。

## 介面前後差異

原本莫蘭迪灰色工作台改為奶油紙張、木色邊框、綠色選中分頁及具立體邊緣的圓角按鈕。靜態人物保留在緊湊摘要內，表格五欄、狀態圖示、進度時數、原因、下一步與日誌功能仍在。總完成比例只統計已收到狀態的課程，同 ID 更新不重複計數；原本的研習進度條更新語意保留。

- [修改前 1366×768／100%](../dist/ui-qa/before-1366-768-1.0-courses.png)
- [修改後 1366×768／100%](../dist/ui-qa/after-1366-768-1.0-courses.png)
- [修改後 1366×768／150%](../dist/ui-qa/after-1366-768-1.5-courses.png)
- [設定頁](../dist/ui-qa/after-1366-768-1.5-settings.png)
- [Debug Log](../dist/ui-qa/after-1366-768-1.5-log.png)
- [Portable 主視窗與首次使用橫幅](../dist/ui-qa/portable-main-smoke.png)

截圖與矩陣位於 Git 忽略的 `dist/ui-qa/`，僅含合成資料；不納入版本庫。

## 驗證結果

- 修改前完整測試：80 項通過；最後完整測試：83 項通過，0 失敗／錯誤。
- 指令：`python_embed/python.exe -B -s -m unittest discover -s tests -q`。
- 新增及既有 UI 測試涵蓋雙平臺開始／停止與瀏覽器切換的 callback、模式鎖定、摘要狀態替換、設定暫存讀寫／密碼遮蔽、Log 複製與開啟資料夾接線。
- 變更 Python 檔案以內建 `compile()` 編譯檢查通過；`git diff --check` 通過。
- `pwsh -NoProfile -File setup_and_run.ps1 -CheckOnly` 通過，無相依衝突。
- 使用 Windows Qt 平臺搭配 `QT_SCALE_FACTOR=1/1.25/1.5`，保留 48 實體像素作標題列／工作列預留。原生渲染檢查主要按鈕均在視窗內，設定頁保留捲動。

| 模擬實體解析度 | Qt 縮放 | 完整可見課程列數 | 主要操作邊界 |
|---|---|---|---|
| 1366 × 768 | 100% | 14 | 通過 |
| 1366 × 768 | 125% | 8 | 通過 |
| 1366 × 768 | 150% | 5 | 通過 |
| 1920 × 1080 | 100% | 26 | 通過 |
| 1920 × 1080 | 125% | 18 | 通過 |
| 1920 × 1080 | 150% | 13 | 通過 |

同尺寸可比較組合的舊版列數為 13、8、23、16、12，新版為 14、8、26、18、13。舊版 1366×768／150% 被最小版面撐到 969×529 邏輯像素，超過可用的 911×480，無法作等尺寸比較；新版可在 911×480 顯示 5 列完整課程並保留全部主要按鈕。

### Portable

- 既有 `scripts/build_portable_release.py` 成功，不修改發布流程；重建後的程式、主題與人物 PNG 和工作樹一致。
- 產物：`dist/AdminEfficiencyPilot_V2.0.1_Portable.zip`（本機 UI 測試包，並非新 Release）。
- SHA-256：`75771b043586a39d2f9e9fc4c95110cc371d537cf1c9e42f1a0e3cbad9650f4e`。
- ZIP 已確認包含人物素材，沒有 `config.json` 或 `.log`。
- 使用 Portable 自帶 runtime，從含中文／空白的其他工作目錄建立真正 MainWindow，Qt 150%、911×480；GUI 子行程結束碼 0，三分頁及人物載入正常，首次使用橫幅可見，主要按鈕未裁切。
- 真實手動更新檢查已連線 GitHub，回到「已是最新版」結果且按鈕恢復可用。更新對話框顯示以 Mock 接收，未執行更新安裝；遙測與啟動自動檢查在 Smoke Test 停用，個人設定／快取均使用暫存目錄。
- 第一個 Smoke Test 的外層輸出曾遇 CP950 無法輸出 emoji；GUI 本身結束碼為 0。改用 UTF-8 後重跑，外層與 GUI 均結束碼 0。

## 未驗證與限制

- 未登入真實研習平臺執行雙開／停止、線上課程、測驗與問卷 E2E；本輪以既有核心回歸與 UI callback 測試確認相容性。
- 縮放是 Windows 原生 Qt 渲染與 Qt scale factor；未逐一切換 Windows 系統縮放、未完成 Win10／Win11 雙機驗收或未安裝全域 Python 的獨立乾淨電腦驗收。
- Smoke Test 直接使用打包 runtime 建立 GUI，沒有以滑鼠雙擊 EXE／BAT 或驗證系統列互動。
- 未實際安裝新版更新；保留原有 SHA-256 驗證機制與回歸測試。
- 既有測試仍有 webdriver_mgr 與日誌檔案的 ResourceWarning，修改前即存在，未擴大處理核心檔案。
- JPEG 裁切人物有原始暖色邊緣；以小型裝飾顯示，未宣稱是原生獨立 Sprite 素材。

## Git 與停止點

`main`，本輪未提交、未 Push、未新增 Release；只保留上述 8 個檔案的本輪修改。停止擴大 UI 優化，進入維護；正式發行資格仍待上述實機驗收，不將模擬渲染或 Mock 當作完整端到端驗收。
