# 行政效能領航員（Admin Efficiency Pilot）

[![Version](https://img.shields.io/badge/version-V2.0.0-blue.svg)](https://github.com/lianghao02/auto-learning-bot/releases/tag/V2.0.0)
[![Python](https://img.shields.io/badge/Python-3.13-green.svg)](https://www.python.org/)
[![Driver](https://img.shields.io/badge/Driver-Selenium-purple.svg)](https://www.selenium.dev/)
[![Tests](https://img.shields.io/badge/tests-70%20passed-brightgreen.svg)](https://github.com/lianghao02/auto-learning-bot)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue.svg)](https://www.microsoft.com/windows)

行政效能領航員提供「臺北 E 大」與「e 等公務園」的公務數位研習輔助流程，支援時數累積、Gemini 批次極速智慧作答、人機協同測驗助理、跳過測驗自動補做問卷、文字本位抗重排題庫核心，以及 SQLite 本機資料庫持久化管理。

---

## 📥 快速下載與使用（一般使用者推薦）

**一般使用者無需安裝 Python 或任何開發環境，直接下載免安裝可攜版即可使用：**

1. 前往 **[GitHub Releases 最新發行頁面](https://github.com/lianghao02/auto-learning-bot/releases/latest)**。
2. 在 **Assets** 區塊點擊下載：
   👉 **`AdminEfficiencyPilot_V2.0.0_Portable.zip`**
3. **解壓縮**：將下載的 ZIP 壓縮檔完整解壓縮至本機任意資料夾（建議放置於桌面或非系統槽，避免路徑權限問題）。
4. **啟動**：進入解壓縮後的資料夾，直接雙擊 **`行政效能領航員.exe`**（自帶專屬圖示，點擊直接啟動，無 CMD 黑窗）；亦可雙擊 **`啟動程式.bat`**。
   - 💡 可雙擊 **`建立桌面捷徑.bat`** 一鍵在桌面建立專屬圖示捷徑。
5. **設定**：首次啟動後，點選左側導覽列 **「⚙️ 帳號與系統設定」** 輸入您的帳號密碼並儲存，即可切換至平臺頁籤開始研習。

---

## 🔑 如何取得免費 Google Gemini API Key（30 秒完成）

本系統支援直連 Google 官方最新 **Gemini 2.0 Flash / 1.5 Flash** 批次作答，1 秒內全自動解析整份試卷並永久記憶進本機題庫：

1. **前往申請網站**：使用瀏覽器開啟 [Google AI Studio (aistudio.google.com)](https://aistudio.google.com/app/apikey)（以一般 Google 帳號登入）。
2. **建立金鑰**：點擊藍色 **「Create API key」** 按鈕。
3. **複製金鑰**：複製產生的 API Key（以 `AIzaSy...` 開頭）。
4. **貼入軟體**：打開軟體 ➜ 點選左側導覽列 **「⚙️ 帳號與系統設定」** ➜ 於 **「⚙️ 全域與 AI 服務設定」** 區塊貼上 Gemini API Key ➜ 點擊下方 **「儲存設定」**。

> 💡 **0 元防扣款與資安保證**：
> - **完全免費**：Google 官方提供每分鐘 15 次、每日 1,500 次之免費額度（Free Tier），**免綁信用卡**。
> - **無扣款風險**：只要您的 Google 專案未綁定信用卡，超額時 Google 只會回傳 429 暫停服務，**絕無任何帳單或扣款風險**。
> - **金鑰安全**：API Key 僅保存在本機 `data/config.json`，執行日誌自動遮罩（Masking），絕不上傳第三方伺服器。

---

## 🚀 測驗處理模式說明

啟動後可於平臺操作列之「測驗處理方式」下拉選單依需求切換作答模式：

1. ⚡ **智慧秒答（題庫優先 + AI 輔助）**：
   優先查詢本機 SQLite 題庫（0 秒）；題庫未收錄之題目自動呼叫 Gemini 批次極速解析（約 1 秒），自動勾選交卷，並將滿分解答標準文字化寫入本機題庫。
2. 🎓 **人機協同作答**：
   遇到測驗時自動彈出輔助視窗，提供「✨ Gemini 智慧作答」、一鍵複製題目提示詞或手動微調作答等輔助功能。
3. ⏭️ **跳過測驗（自動補作問卷）**：
   若選擇略過測驗，程式自動檢查並接續完成該課程之滿意度問卷調查，事後僅需自行補考測驗即可 100% 完課取得時數。

---

## 🌟 V2.0.0 商業級介面與核心功能特色

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
  - 帳號密碼與 API Key 僅留存於本機 `data/config.json`，更新程式時僅替換 `current/`，個人資料與題庫絕不遺失。

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
git clone https://github.com/lianghao02/auto-learning-bot.git
cd 07_auto-learning-bot

# 2. 建立 Python 3.13 虛擬環境
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. 安裝相依套件
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. 啟動圖形介面（首次啟動將自動於 data/ 目錄初始化設定）
python ui.py
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
# 執行完整 70 項自動化單元與回歸測試套件
pwsh -NoProfile -File scripts/run_tests.ps1

# 亦可透過 Python unittest 模組執行
python -m unittest discover -s tests -v
```
