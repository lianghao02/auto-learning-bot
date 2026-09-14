# 行政效能領航員（auto-learning-bot）

[![Version](https://img.shields.io/badge/version-v2.0.0-blue.svg)](https://github.com/lianghao02/auto-learning-bot/releases/tag/v2.0.0)
[![Python](https://img.shields.io/badge/Python-3.13-green.svg)](https://www.python.org/)
[![Driver](https://img.shields.io/badge/Driver-Selenium-purple.svg)](https://www.selenium.dev/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue.svg)](https://www.microsoft.com/windows)

行政效能領航員提供「臺北 E 大」與「e 等公務園」的公務數位研習輔助流程，支援時數累積、Gemini 批次智慧極速作答、人機協同測驗助理、跳過測驗自動完成問卷、平台已加入課程自動處理與 SQLite 本機題庫持久化管理。

---

## 📥 快速下載與使用（一般使用者推薦）

**一般使用者無需安裝 Python 或任何開發環境，直接下載免安裝可攜版即可使用：**

1. 前往 **[GitHub Releases 最新發行頁面](https://github.com/lianghao02/auto-learning-bot/releases/latest)**。
2. 在 **Assets** 區塊點擊下載：
   👉 **`AdminEfficiencyPilot_V2.0.0_Portable.zip`**
3. **解壓縮**：將下載的 ZIP 壓縮檔完整解壓縮至本機任意資料夾（建議放置於桌面或非系統槽）。
4. **啟動**：進入解壓縮後的資料夾，直接雙擊 **`行政效能領航員.exe`**（自帶專屬圖示，點擊直接啟動，無 CMD 黑窗）；亦可雙擊 **`啟動程式.bat`**。
   - 💡 可雙擊 **`建立桌面捷徑.bat`** 一鍵在桌面建立專屬圖示捷徑。
5. **設定**：首次啟動後，於「帳號與系統設定」輸入您的帳號密碼並儲存，即可在平臺頁籤開始研習。

---

## 🔑 如何取得免費 Google Gemini API Key（30 秒完成）

本系統支援直連 Google 官方最新 **Gemini 2.0 Flash** 批次作答，1 秒內全自動解析整份考卷並永久記憶進本機題庫：

1. **前往申請網站**：使用瀏覽器開啟 [Google AI Studio (aistudio.google.com)](https://aistudio.google.com/app/apikey)（以一般 Google 帳號登入）。
2. **建立金鑰**：點擊藍色 **「Create API key」** 按鈕。
3. **複製金鑰**：複製產生的 API Key（以 `AIzaSy...` 開頭）。
4. **貼入軟體**：打開軟體 ➜ 點擊右上角「⚙️ 系統設定」➜ 於「AI 補答設定」貼上金鑰並點擊「確定」。

> 💡 **0 元防扣款與資安保證**：
> - **完全免費**：Google 官方提供每分鐘 15 次、每日 1,500 次之免費額度（Free Tier），**免綁信用卡**。
> - **無扣款風險**：只要您的 Google 專案未綁定信用卡，超額時 Google 只會回傳 429 暫停服務，**絕無任何帳單或扣款風險**。
> - **金鑰安全**：API Key 僅保存在本機 `data/config.json`，日誌自動脫敏（Masking），絕不上傳第三方伺服器。

---

## 🚀 測驗處理模式說明

啟動後可在主介面依需求切換作答模式：

1. ⚡ **全自動（題庫優先 + Gemini 批次秒答）**：
   優先查詢本機 SQLite 題庫（0 秒）；未收錄之題目自動呼叫 Gemini 2.0 Flash 批次解析（1 秒），自動勾選交卷並寫入 SQLite 題庫。
2. 🎓 **人機協同作答（彈窗回貼 ＋ ✨ Gemini 一鍵作答）**：
   遇到測驗時自動彈出輔助視窗，提供「✨ Gemini 1 秒智慧作答」、「一鍵複製 Prompt」與「秒開 ChatGPT / Gemini」等快捷功能。
3. ⏭️ **跳過測驗，自動補填問卷**：
   若點擊跳過測驗，程式自動檢查並接續完成該課程的「滿意度問卷調查」，事後僅需補考測驗即可 100% 完課拿時數。

---

## 🌟 v1.0.0 正式穩定版功能與特色

- 🎯 **雙平臺自動研習全流程**：支援「臺北 E 大」與「e 等公務園」，具備自動登入、上課掛時數、測驗作答、問卷提交與結案回跳。
- ⚡ **雙作答引擎（SQLite 題庫優先 ＋ Gemini 批次秒答）**：
  - 優先秒級命中本地題庫；未命中之題目自動打包發送 Google Gemini 批次解答（0.8 ~ 1.2 秒），並自動結構化存入 `questions.db`。
- 🔄 **自我修復與 Session 恢復防護機制**：
  - 閒置登出自動重登、SSO 憑證過期重新同步、API 課程清單自動恢復，支援長達數小時之穩定無人值守運作。
- 🖥️ **GUI 即時狀態同步與動態成果儀表板**：
  - 工作臺精確呈現課程階段（`▶ 研習中` ➜ `✅ 已完成`），終端機輸出清晰之研習成效儀表板，即時監控 API 呼叫量與配額健康狀態。
- 🛡️ **安全無虞之本地架構**：
  - API Key 與帳密僅留存本機 `data/config.json`，日誌完全脫敏，絕不上傳任何第三方。

---

## 📜 歷史開發版本紀錄（里程碑）

<details>
<summary>點擊展開查看歷史內部版本紀錄（V3.2.0 / V3.1.0）</summary>

### V3.2.0 內部開發版本亮點
- ✨ **Google Gemini 2.0 Flash 批次極速作答引擎**：考卷 10 題合一發送，JSON 結構化解析並自動標準化寫入本機 SQLite `questions.db`。
- 🛡️ **內建免費額度滑動窗口限速防護鎖（Rate Limiter）**：預設安全限速 5 RPM，自動排隊延遲。
- 📋 **跳過測驗自動補填問卷機制**：點擊「立即跳過測驗」時，自動接續執行課程問卷調查並提交。
- 🖥️ **人機協同助理彈窗升級**：彈窗新增「✨ Gemini 1 秒智慧作答」專屬按鈕，開啟時自動將 Prompt 預載至剪貼簿。
- 🎯 **動態及格門檻多重判定機制**：支援 60、70、75、80、100 分等多種平臺及格標準。
- 🤖 **AI 測驗助理多選項（E、F...）與數字代號解析升級**：答案解析引擎支援 5 選項題型與數字代號。
- 🛡️ **非上課期間與尚未上架課程彈窗攔截**：捕捉「目前課程尚未上架」彈窗並永久跳過。
- 🏢 **加盟機關課程導航與開放式「認證」按鈕識別**：排除入口首頁與學員統計頁。

### V3.1.0 內部開發版本亮點
- 🧹 **主動定期 Session 保養與 Cookie 深度清理重登機制**：每連續研習滿 5 小時自動啟動深度清理並重新 SSO 登入。
- 🛡️ **平臺重新導向異常 (ERR_TOO_MANY_REDIRECTS) 防護與死循環阻斷**：偵測平臺重新導向次數過多故障並自動略過。

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
# 1. 複製專案庫
git clone https://github.com/lianghao02/auto-learning-bot.git
cd 07_auto-learning-bot

# 2. 建立 Python 3.13 虛擬環境
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. 安裝相依套件
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. 複製設定檔範本並填入設定
copy config.json.example config.json

# 5. 啟動圖形介面
python ui.py
```

---

## 📦 可攜版資料架構與自動更新

- **資料隔離架構**：
  - 程式主體位於 `current/`。
  - 個人設定、題庫與日誌位於同層獨立之 `data/`。
  - 自動更新時僅切換 `current/` 程式目錄，**絕不會覆蓋或遺失 `data/` 中的個人帳密與題庫**。
- **SHA-256 完整性校驗**：
  - 每一次發行皆隨附 `SHA256SUMS.txt` 與 `.zip.sha256` 驗證碼，確保執行檔未遭篡改。

---

## ⚠️ 注意事項與隱私安全

1. **帳密安全**：`config.json` 包含個人登入資訊或 API Key，請妥善保管，**嚴禁將個人 config.json 提交或公開至 GitHub**。
2. **多開限制**：請勿在同一臺電腦同時啟動兩個相同平臺的研習流程，避免瀏覽器 Session 互相搶佔與中斷。
3. **平臺機制**：部分公務課程可能要求測驗及格後方可填寫問卷，程式會依平臺實際回應彈性記錄與處理。

---

## 🧪 測試與驗證

```powershell
python -m unittest discover -s tests -v
python -m py_compile app.py ui.py utils/helpers.py
```
