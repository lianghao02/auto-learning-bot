# 行政效能領航員（auto-learning-bot）

[![Version](https://img.shields.io/badge/version-V3.2.0-blue.svg)](https://github.com/lianghao02/auto-learning-bot/releases/tag/V3.2.0)
[![Python](https://img.shields.io/badge/Python-3.13-green.svg)](https://www.python.org/)
[![Driver](https://img.shields.io/badge/Driver-Selenium-purple.svg)](https://www.selenium.dev/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue.svg)](https://www.microsoft.com/windows)

行政效能領航員提供「臺北 E 大」與「e 等公務園」的公務數位研習輔助流程，支援時數累積、Gemini 批次智慧極速作答、人機協同測驗助理、跳過測驗自動完成問卷、平台已加入課程自動處理與 SQLite 本機題庫持久化管理。

---

## 📥 快速下載與使用（一般使用者推薦）

**一般使用者無需安裝 Python 或任何開發環境，直接下載免安裝可攜版即可使用：**

1. 前往 **[GitHub Releases 最新發行頁面](https://github.com/lianghao02/auto-learning-bot/releases/latest)**。
2. 在 **Assets** 區塊點擊下載：
   👉 **`AdminEfficiencyPilot_V3.2.0_Portable.zip`**
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

## 🌟 V3.2.0 重要功能與更新亮點

- ✨ **Google Gemini 2.0 Flash 批次極速作答引擎**：
  - 考卷題目 10 題合一打包發送，單次測驗僅需 1 次請求，耗時由 10 秒縮短至 **0.8 ~ 1.2 秒**。
  - 採用 JSON 結構化輸出（Structured Output），格式解析準確率達 100%，並自動標準化寫入本機 SQLite `questions.db`。
- 🛡️ **內建免費額度滑動窗口限速防護鎖（Rate Limiter）**：
  - 預設安全限速 5 RPM（每分鐘最多 5 次請求），自動排隊延遲，絕不觸發 Google HTTP 429。
  - API Key 輸出自動脫敏遮罩（如 `AIzaSy***1234`），保障資安無外洩疑慮。
- 📋 **跳過測驗自動補填問卷機制**：
  - 使用者點擊「立即跳過測驗」時，流程不中斷，自動接續執行課程問卷調查並提交。
- 🖥️ **人機協同助理彈窗升級**：
  - 彈窗新增「✨ Gemini 1 秒智慧作答」專屬按鈕，開啟時自動將 Prompt 預載至剪貼簿。
  - 設定面板新增「遇到未知測驗時自動使用 AI 背景作答」開關與官方動態費率指引。


- 🎯 **動態及格門檻多重判定機制**：
  - 支援 60、70、75、80、100 分等多種平臺及格標準，精準對齊各類專題與開放式課程（如「臺灣藍碳發展機會與策略建議」之 75 分門檻）。
  - 將平臺 `pass_status`（未通過/不及格/fail）納入最高優先排外過濾，即使考取 60 分亦絕不誤判為修畢，確保自動進入考試流程補測達標。
- 🤖 **AI 測驗助理多選項（E、F...）與數字代號解析升級**：
  - 答案解析引擎全面放寬正則限制，完整支援 5 選項題型（如「英業達實務案例」等題型包含 `E. 以上皆是`）。
  - 支援 1～9 數字代號自動對應至第 N 個選項代碼（如 `5` 自動對應為 `E`），提升人機協同回貼之容錯率。
- 🛡️ **非上課期間與尚未上架課程彈窗攔截**：
  - 自動捕捉並確認「目前課程尚未上架且非上課期間，無法進入教室介面」等 Alert 彈窗，主動標記並永久跳過，阻斷重登重試無限循環。
- 🏢 **加盟機關課程導航與開放式「認證」按鈕識別**：
  - 排除加盟平臺首頁（`mooc/index.php`）與學員統計頁（`learn_stat.php`），並擴充支援【認證】、【進行測驗】直接作答。

---

## 🌟 V3.1.0 重要功能與更新亮點

- 🧹 **主動定期 Session 保養與 Cookie 深度清理重登機制**：
  - 研習主迴圈新增自動定時維護機制，預設每連續研習滿 **5 小時**（可於 `config.json` 的 `session_refresh_hours` 彈性調整），於課程結算（時數+問卷/測驗）完成後自動啟動。
  - 保養流程主動關閉殘留子分頁，呼叫 `delete_all_cookies()` 與 `http_session.cookies.clear()` 深度清除積累之快取與過期 Session，並重新執行完整登入獲取全新 SSO 憑證。
  - 全面覆蓋「單門逐面上課流程」與「批次問卷/測驗結算流程」，確保長時間掛機（8~24 小時以上）穩定不中斷。
- 🛡️ **平臺重新導向異常 (ERR_TOO_MANY_REDIRECTS) 防護與死循環阻斷**：
  - 自動偵測 Chrome `ERR_TOO_MANY_REDIRECTS`（重新導向次數過多）與 `ERR_NAME_NOT_RESOLVED` 等平臺故障，安全跳過（SKIP）並記錄至待人工查核清單。
  - 排除 `mooc/index.php` 正常路徑之登出誤判，並加入單一課程重登重試防護鎖（連續 2 次異常自動略過），徹底消除無限重登死循環。

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
