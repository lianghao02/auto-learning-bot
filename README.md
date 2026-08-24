# 行政效能領航員（auto-learning-bot）

[![Version](https://img.shields.io/badge/version-V3.0.0-blue.svg)](https://github.com/lianghao02/auto-learning-bot)
[![Python](https://img.shields.io/badge/Python-3.13-green.svg)](https://www.python.org/)
[![Driver](https://img.shields.io/badge/Driver-Selenium-purple.svg)](https://www.selenium.dev/)

行政效能領航員提供「臺北 E 大」與「e 等公務園」的公務數位研習輔助流程，支援時數累積、人機協同測驗助理、平台已加入課程的自動處理、問卷自動填寫與 SQLite 本機題庫持久化管理。

## 下載、依賴與啟動

- **系統**：Windows 10/11、Chrome 或 Edge；主要開發、自癒與可攜發行環境統一為 Python 3.13。
- **推薦啟動**：下載 ZIP、解壓後先將 `config.json.example` 複製為 `config.json`，再雙擊 `RUN.bat`。沒有 Python 時會自動建立 `python_embed`。
- **手動安裝**：`py -3.13 -m venv .venv`，啟用後執行 `python -m pip install -r requirements.txt`，再執行 `python ui.py`。
- **執行依賴**：PySide6、Selenium、requests、psutil、NumPy、OpenCV、ddddocr 等，版本範圍都在 `requirements.txt`。
- **敏感資料**：`config.json`、登入資訊、題庫與執行紀錄不可提交到 GitHub；平台流程變更時仍需人工確認。

## 🌟 V3.0.0 重要功能與更新亮點

- 🎓 **人機協同測驗助理 (Interactive Quiz Assistant v2)**：
  - 遇到測驗時自動彈出輔助視窗，提供「📋 一鍵複製 AI 提問 Prompt」。
  - 視窗內建 **「🌐 開啟 ChatGPT」** 與 **「✨ 開啟 Gemini」** 快捷按鈕，以系統原生雙層機制秒開預設瀏覽器。
  - 答案回貼區強制純文字防富文本污染，全面支援 Markdown 粗體（`**1. B**`）、清單項目（`- 1. B`）、表格列（`| 1 | B |`）與中英文引導詞。
  - 新增 **即時解析回饋標籤（Live Parsing Feedback）**，貼上瞬間立即顯示 `✅ 已成功辨識 X/Y 題解答`。
  - 內建 **180 秒倒數計時（分秒動態顯示 03:00）**、暫停倒數與逾時明確決策提示（重設計時／跳過／結束執行），防範掛網無人操作時卡死。
  - 作答完畢後自動將題目與解答沉澱至本機 SQLite 題庫 [`questions.db`](questions.db)。
- 🛡️ **全域人機作答排隊互斥鎖（Anti-Crash Queue Lock）**：
  - 雙開「臺北 E 大」與「e 等公務園」同時觸發測驗時，由全域排隊鎖進行安全調度，保證同時間僅有一個對話框活躍，徹底消除 Qt 雙重模態事件循環（Nested QEventLoop）崩潰與閃退。
- 🎯 **課程完成條件精準判定**：
  - 依個別課程實際要求確認研習時數、測驗及格（若有測驗）與問卷完成（若有問卷）；避免測驗 0 分但問卷已填的課程被誤判完成。
- 📦 **組裝／套裝課程優化處理**：
  - e 等公務園報名組裝課程後，平臺會自動加入子課程；本程式直接依 API 課程清單處理，避免重複掃描與重複報名。子課程缺漏時才使用修復備援。
- 📊 **測驗即時成績判定與分數通知**：
  - 測驗交卷後即時解析分數與狀態，於日誌明確顯示 `🎉 測驗結果：及格 / 通過 【得分：XX 分】` 或 `❌ 測驗結果：不及格 / 未通過 【得分：XX 分】`。

## 🚀 執行方式

1. 複製 `config.json.example` 為 `config.json`，依帳號設定內容。
2. 以 Windows 執行 `run.bat`，或使用已安裝依賴的 Python 執行 `ui.py`。
3. 在平臺頁籤選擇「測驗處理模式」後按「▶️ 開始執行」：
   - `🤖 全自動（題庫優先 + AI 補答）`：優先查詢本機 SQLite 題庫，未收錄題目自動調用 AI API 補答。
   - `🎓 人機協同作答（彈窗回貼）`：遇到測驗時彈出輔助視窗，提供一鍵複製 Prompt、秒開 ChatGPT/Gemini 與答案回貼。
   - `⏭️ 跳過測驗，先做問卷`：時數達標後跳過測驗，優先嘗試完成問卷。

## ⚠️ 注意事項

- 平臺可能限制測驗未通過時不可填問卷；程式會記錄結果後繼續下一門，不會假定問卷一定可填。
- 請勿在同一臺電腦同時啟動兩個臺北 E 大流程。
- `config.json` 可能包含未加密帳密或 API 金鑰，請勿提交或轉傳該檔案。

## 🧪 開發驗證

主要開發、測試與可攜發行版本基準統一為 Python 3.13。

```powershell
python -m unittest discover -s tests -v
python -m py_compile app.py ui.py utils/helpers.py
```
