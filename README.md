# 行政效能領航員（auto-learning-bot）

[![Version](https://img.shields.io/badge/version-V3.1.0-blue.svg)](https://github.com/lianghao02/auto-learning-bot/releases/tag/V3.1.0)
[![Python](https://img.shields.io/badge/Python-3.13-green.svg)](https://www.python.org/)
[![Driver](https://img.shields.io/badge/Driver-Selenium-purple.svg)](https://www.selenium.dev/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue.svg)](https://www.microsoft.com/windows)

行政效能領航員提供「臺北 E 大」與「e 等公務園」的公務數位研習輔助流程，支援時數累積、人機協同測驗助理、平台已加入課程自動處理、問卷自動填寫與 SQLite 本機題庫持久化管理。

---

## 📥 快速下載與使用（一般使用者推薦）

**一般使用者無需安裝 Python 或任何開發環境，直接下載免安裝可攜版即可使用：**

1. 前往 **[GitHub Releases 最新發行頁面](https://github.com/lianghao02/auto-learning-bot/releases/latest)**。
2. 在 **Assets** 區塊點擊下載：
   👉 **`AdminEfficiencyPilot_V3.1.0_Portable.zip`**
3. **解壓縮**：將下載的 ZIP 壓縮檔完整解壓縮至本機任意資料夾（建議放置於桌面或非系統槽）。
4. **啟動**：進入解壓縮後的資料夾，直接雙擊 **`行政效能領航員.exe`**（自帶專屬圖示，點擊直接啟動，無 CMD 黑窗）；亦可雙擊 **`啟動程式.bat`**。
   - 💡 可雙擊 **`建立桌面捷徑.bat`** 一鍵在桌面建立專屬圖示捷徑。
5. **設定**：首次啟動後，於「帳號與系統設定」輸入您的帳號密碼並儲存，即可在平臺頁籤開始研習。

> 💡 **安全說明**：
> - 專屬啟動器 `行政效能領航員.exe` 僅負責無黑窗喚起 Python 核心，**不修改系統登錄檔**、**不需系統管理員權限**、**不需聯網執行 pip**。
> - 內建完整獨立 Python 3.13 執行環境，解壓縮即可獨立執行，綠色環保。若要移除，直接刪除整個資料夾即可。

---

## 🚀 測驗處理模式說明

啟動後可在主介面依需求切換 3 種作答模式：

1. 🤖 **全自動（題庫優先 + AI 補答）**：
   優先查詢本機 SQLite 題庫，若遇未收錄題目且有設定 AI API Key（Gemini / OpenAI），自動呼叫 AI 完成補答。
2. 🎓 **人機協同作答（彈窗回貼）**：
   遇到測驗時自動彈出輔助對話框，提供「一鍵複製 Prompt」與「秒開 ChatGPT / Gemini」快捷按鈕，將 AI 回答貼回視窗即可即時解析並自動作答。
3. ⏭️ **跳過測驗，先做問卷**：
   研習時數達標後自動跳過測驗步驟，優先嘗試填寫問卷以獲取進度。

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
