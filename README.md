# 行政效能領航員（Admin Efficiency Pilot）

[![Version](https://img.shields.io/badge/version-V2.0.1-blue.svg)](https://github.com/lianghao02/auto-learning-bot/releases/tag/V2.0.1)
[![Python](https://img.shields.io/badge/Python-3.13-green.svg)](https://www.python.org/)
[![Driver](https://img.shields.io/badge/Driver-Selenium-purple.svg)](https://www.selenium.dev/)
[![Tests](https://img.shields.io/badge/tests-project%20runner-blue.svg)](scripts/run_tests.ps1)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue.svg)](https://www.microsoft.com/windows)

行政效能領航員提供「臺北 E 大」與「e 等公務園」的公務數位研習輔助流程，支援時數累積、Gemini 批次極速智慧作答、人機協同測驗助理、跳過測驗自動補做問卷、文字本位抗重排題庫核心，以及 SQLite 本機資料庫持久化管理。

---

## 專案概念與開發原因

行政效能領航員整合公務研習平臺的課程狀態、瀏覽器工作階段與測驗輔助流程。開發動機是跨平臺反覆登入、查看進度及處理重複題目耗時，需要集中且可觀察的工作台。

採 Selenium 驅動瀏覽器，搭配本機資料保存與選用 AI／共用題庫服務。使用者仍須確認課程要求與答案；工具的完成訊息不能取代研習平臺的正式紀錄。

**典型流程**：設定帳號與服務 → 選擇平臺及模式 → 查看執行狀態 → 人工處理例外 → 回平臺確認時數／成績。

## 📥 快速下載與使用（一般使用者推薦）

**一般使用者無需安裝 Python 或任何開發環境，直接下載免安裝可攜版即可使用：**

1. 前往 **[GitHub Releases 最新發行頁面](https://github.com/lianghao02/auto-learning-bot/releases/latest)**。
2. 在 **Assets** 區塊點擊下載：
   👉 **`AdminEfficiencyPilot_V2.0.1_Portable.zip`**
3. **解壓縮**：將下載的 ZIP 壓縮檔完整解壓縮至本機任意資料夾（建議放置於桌面或非系統槽，避免路徑權限問題）。
4. **啟動**：進入解壓縮後的資料夾，直接雙擊 **`行政效能領航員.exe`**（自帶專屬圖示，點擊直接啟動，無 CMD 黑窗）；亦可雙擊 **`啟動程式.bat`**。
   - 💡 可雙擊 **`建立桌面捷徑.bat`** 一鍵在桌面建立專屬圖示捷徑。
5. **設定**：首次啟動後，點選左側導覽列 **「⚙️ 帳號與系統設定」** 輸入您的帳號密碼並儲存，即可切換至平臺頁籤開始研習。

---

## 🔑 設定 Google Gemini API Key

本系統可使用設定的 Gemini／AI 服務輔助解析題目。可用模型、回應時間與正確率依服務和題目而異；題庫保存也需要備份，不能視為永久保存保證。

1. **前往申請網站**：使用瀏覽器開啟 [Google AI Studio (aistudio.google.com)](https://aistudio.google.com/app/apikey)（以一般 Google 帳號登入）。
2. **建立金鑰**：點擊藍色 **「Create API key」** 按鈕。
3. **複製金鑰**：複製產生的 API Key（以 `AIzaSy...` 開頭）。
4. **貼入軟體**：打開軟體 ➜ 點選左側導覽列 **「⚙️ 帳號與系統設定」** ➜ 於 **「⚙️ 全域與 AI 服務設定」** 區塊貼上 Gemini API Key ➜ 點擊下方 **「儲存設定」**。

> **服務額度與資料傳輸**：
> - 使用前請在自己的 Google／AI 服務帳號確認模型、配額、計費與資料使用條款；本工具不保證固定免費額度或不會產生費用。
> - API Key 保存於本機 `data/config.json`，呼叫服務時仍須提供認證。請勿公開設定檔，日誌送出前亦應自行檢查遮罩結果。
> - AI 模式會將題目交給所設定的服務；共用題庫流程也可能向 GAS 傳送題目、課程與使用者名稱。這不是完全離線工具。

---

## 🚀 測驗處理模式說明

啟動後可於平臺操作列之「測驗處理方式」下拉選單依需求切換作答模式：

1. ⚡ **智慧秒答（題庫優先 + AI 輔助）**：
   優先使用題庫，未命中時依流程呼叫 AI 輔助解析，再處理作答與文字化入庫。不同平臺的題庫來源及流程可能不同；耗時、正確率與通過結果不保證，請確認實際成績。
2. 🎓 **人機協同作答**：
   遇到測驗時自動彈出輔助視窗，提供「✨ Gemini 智慧作答」、一鍵複製題目提示詞或手動微調作答等輔助功能。
3. ⏭️ **跳過測驗（自動補作問卷）**：
   若選擇略過測驗，程式檢查並嘗試接續處理問卷；是否可填問卷、是否取得時數仍依平臺規則與成績判定，需自行回平臺確認。

---

## 🌟 V2.0.1 商業級介面與核心功能特色

- 🎨 **現代自適應工作台（Compact Ribbon & In-Row Focus）**：
  - 徹底重構主視窗架構，全面移除舊版絕對座標與靜態貼圖外殼，完美適應 Windows 高 DPI（125%、150%）顯示環境。
  - 操作儀表列（Compact Ribbon）緊湊整合平臺摘要與控制按鈕，垂直視野釋放逾 150px。
  - 課程清單表格實作進行中課程行焦點高亮（`▶ ` 前綴、莫蘭迪色系背景、粗體引導與詳細 Tooltip）。
  - 詳細執行紀錄分頁新增「📋 複製紀錄」、「📁 開啟日誌資料夾」與「🧹 清空畫面」工具列。
- 🧠 **文字本位抗選項隨機重排題庫核心 (Text-Content-First)**：
  - 以選項真實文字內容為最高優先配對依據，徹底解決平臺隨機打亂選項順序（Shuffled）導致盲目選錯的歷史缺陷。
  - 支援滿分 AI 解答真實文字標準化入庫，長效跨次數累積高品質題庫資產。
- 🎯 **雙平臺自動研習全流程**：
  - 完整支援「臺北 E 大」與「e 等公務園」，具備自動登入、上課累積時數、測驗作答、問卷提交與結案回跳。
- 🔄 **無人值守容錯與 Session 自我修復**：
  - 閒置逾時自動重登、SSO 憑證過期重新同步、待處理課程配額雙重容錯防護，支援長達數小時之穩定無人值守運作。
- 🛡️ **本機資料隔離與隱私安全**：
  - 帳號密碼與 API Key 的設定保存在本機 `data/config.json`；登入與服務呼叫仍涉及網路認證。可攜版更新將 `current/` 與 `data/` 分離，但個人設定和題庫仍需備份。

---

## 📜 歷史開發版本紀錄（里程碑）

<details>
<summary>點擊展開查看歷史版本紀錄（V1.1.0 / v1.0.0 / V3.2.0 / V3.1.0）</summary>

### 🏆 V1.1.0
- 平臺工作台控制列融合（Ribbon Integration），整合測驗選單與執行控制項。
- 帳號與全域設定重構為雙卡片左右並列，支援 `QScrollArea` 滾動保護。
- 頂部 Header 收斂多餘按鈕，統一由左側導航進入。

### 🏆 v1.0.0
- 首次對外正式穩定版（Stable Release）。
- 建立雙平臺全流程、SQLite 題庫優先與 Gemini 批次秒答機制。

### V3.2.0 內部開發版本
- Google Gemini 2.0 Flash 批次極速作答引擎（整卷 10 題合一發送）。
- 內建免費額度滑動窗口限速防護鎖（Rate Limiter，5 RPM 安全限速）。
- 動態及格門檻多重判定機制（60、70、75、80、100 分支援）。
- 答案解析引擎擴充支援 5 選項題型（E、F...）與數字代號。

### V3.1.0 內部開發版本
- 主動定期 Session 保養與 Cookie 深度清理重登機制。
- 平臺重新導向異常 (ERR_TOO_MANY_REDIRECTS) 防護與死循環阻斷。

</details>

---

## 🛠️ 開發者與原始碼手動安裝

如果您是開發者，希望透過原始碼直接執行或二次開發：

### 系統與環境需求
- **作業系統**：Windows 10 / 11 64-bit
- **瀏覽器**：Google Chrome 或 Microsoft Edge
- **Python 版本**：Python 3.13 (64-bit)

### 原始碼安裝步驟

```powershell
# 1. 複製儲存庫
git clone https://github.com/lianghao02/auto-learning-bot.git 07_auto-learning-bot
cd 07_auto-learning-bot

# 2. 依既有啟動器建立／檢查 embedded 環境，不開啟介面
pwsh -NoProfile -File setup_and_run.ps1 -NoLaunch

# 3. 唯讀確認環境；套件操作應綁定同一 embedded 直譯器
pwsh -NoProfile -File setup_and_run.ps1 -CheckOnly

# 4. 啟動圖形介面（首次啟動將自動於 data/ 目錄初始化設定）
python_embed\python.exe -B -s ui.py
```

---

## 📦 可攜版資料架構與自動更新

- **資料隔離架構**：
  - 程式主體位於 `current/`。
  - 個人設定、題庫與日誌位於同層獨立之 `data/`。
  - 自動更新時僅切換 `current/` 程式目錄，**絕不會覆蓋或遺失 `data/` 中的個人帳密與題庫**。
- **SHA-256 完整性校驗**：
  - 每一次發行皆隨附 `.zip.sha256` 驗證碼，確保執行檔未遭篡改。

---

## ⚠️ 注意事項與隱私安全

1. **帳密安全**：`config.json` 包含個人登入資訊或 API Key，請妥善保管，**嚴禁將個人 config.json 提交或公開至 GitHub**。
2. **多開限制**：請勿在同一臺電腦同時啟動兩個相同平臺的研習流程，避免瀏覽器 Session 互相搶佔與中斷。
3. **平臺機制**：部分公務課程可能要求測驗及格後方可填寫問卷，程式會依平臺實際回應彈性記錄與處理。

---

## 🧪 測試與驗證

本專案提供專屬測試執行器，具備 UTF-8 控制台編碼防禦與 Python 隔離環境注入：

```powershell
# 透過專案執行器進行測試，數量及結果以本次輸出為準
pwsh -NoProfile -File scripts/run_tests.ps1

# 亦可透過 Python unittest 模組執行
python_embed\python.exe -B -s -m unittest discover -s tests -v
```

## 環境檢查與隔離

使用既有啟動入口，或以 `setup_and_run.ps1 -CheckOnly` 唯讀健檢。embedded／測試／下一次發布及更新後重啟均明確使用 `-s`，正常啟動不改寫 `._pth`。依賴操作只能針對專案直譯器之 `-m pip`；不調整全域 PATH 或全域套件。requirements.txt 鎖定來源環境，requirements-release.txt 維持正式發布角色。舊發布包本輪未重建，需下次受控發布套用隔離修正。

## 已知 Bug、限制與疑難排解

以下區分已確認問題、功能限制及待驗證項目；歷史修正不代表舊發行包已自動更新，也不代表本次文件更新重新完成所有功能測試。

| 狀態 | 情境 | 處理方式 |
|---|---|---|
| 相容限制 | 平臺頁面、SSO 流程、Chrome／Driver 版本變動。 | 記錄失敗步驟與版本，先確認登入與瀏覽器環境；不要同時啟動同平臺的多個流程。 |
| 服務限制 | AI 回答可能錯誤，API 也可能逾時、限流或停用模型。 | 改用人工協同並確認答案；額度、模型與費用依所設定服務的帳號狀態查核。 |
| 資料傳輸 | AI 與 GAS 共用題庫涉及外部連線。 | 使用前確認資料可傳送範圍；不能把本機 config 保存等同所有資料只留在本機。 |

文字本位配對用來處理選項隨機重排；重新導向與工作階段問題的修正紀錄見 [CHANGELOG.md](CHANGELOG.md)。目前 [quiz_bank.py](quiz_bank.py) 的共用題庫回報可傳送課程、題目／選項及 username；AI 模式會將題目交給設定的服務。請勿在 Bug 附件中公開帳密、Cookie 或 API Key。

### 問題回報

請提供使用版本／啟動方式、作業系統與相關環境、重現步驟、預期及實際結果，以及去識別的錯誤訊息或最小樣本。先保留現場與來源資料；不要附真實案件、完整帳號、密碼、Token 或 API Key。版本修正以對應原始碼與發行包為準。
