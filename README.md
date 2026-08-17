# 行政效能領航員（auto-learning-bot）

[![Version](https://img.shields.io/badge/version-V2.4.0-blue.svg)](https://github.com/lianghao02/auto-learning-bot)
[![Python](https://img.shields.io/badge/Python-3.13-green.svg)](https://www.python.org/)
[![Driver](https://img.shields.io/badge/Driver-Selenium-purple.svg)](https://www.selenium.dev/)

行政效能領航員提供「臺北 E 大」與「e 等公務園」的公務數位研習輔助流程，支援時數累積、人機協同測驗助理、平台已加入課程的自動處理、問卷自動填寫與 SQLite 本機題庫持久化管理。

## 下載、依賴與啟動

- **系統**：Windows 10/11、Chrome 或 Edge；主要開發與自癒環境為 Python 3.13。
- **推薦啟動**：下載 ZIP、解壓後先將 `config.json.example` 複製為 `config.json`，再雙擊 `RUN.bat`。沒有 Python 時會自動建立 `python_embed`。
- **手動安裝**：`py -3.13 -m venv .venv`，啟用後執行 `python -m pip install -r requirements.txt`，再執行 `python ui.py`。
- **執行依賴**：PySide6、Selenium、requests、psutil、NumPy、OpenCV、ddddocr 等，版本範圍都在 `requirements.txt`。
- **可攜版打包**：`requirements-release.txt` 與 `scripts/build_portable_release.py` 使用 Python 3.11 建立相容發行包；這和日常 Python 3.13 開發環境是兩條獨立流程。
- **敏感資料**：`config.json`、登入資訊、題庫與執行紀錄不可提交到 GitHub；平台流程變更時仍需人工確認。

## 🌟 V2.4.0 重要功能與更新亮點

- 🎓 **人機協同測驗助理（免 API Key 模式）**：
  - 遇到測驗時自動彈出輔助視窗，提供「📋 一鍵複製 AI 提問 Prompt」。
  - 使用者在 ChatGPT 或 Gemini 網頁版取得答案後，可直接回貼（支援剪貼簿一鍵貼上）。
  - 智慧解析單選、是非（⭕/❌）與多選題，自動精確點選網頁核取方塊並交卷。
  - 內建 **180 秒倒數計時（分秒動態顯示 03:00）**、暫停倒數與逾時明確決策提示（重設計時／跳過／結束執行），防範掛網無人操作時卡死。
  - 作答完畢後自動將題目與解答沉澱至本機 SQLite 題庫 [`questions.db`](questions.db)。
- 📦 **組裝／套裝課程處理**：
  - e 等公務園報名母課程後會由平台自動加入旗下子課程；正常執行直接使用課程 API 清單處理子課程。
  - 不再於每次啟動時重複掃描母課程、展開子課程或再次報名，減少等待時間與錯誤警告。
  - 原有子課程掃描邏輯保留為缺漏時的修復備援，不參與一般自動執行流程。
- 📊 **測驗即時成績判定與分數通知**：
  - 測驗交卷後即時解析分數與狀態，於日誌明確顯示 `🎉 測驗結果：及格 / 通過 【得分：XX 分】` 或 `❌ 測驗結果：不及格 / 未通過 【得分：XX 分】`。
- 🔄 **測驗未及格重考修復與重複學習防護**：
  - 修正先前已考過但不及格（如 30分、50分）時因分數非空被誤判完成的問題，精確納入待重測隊列。
  - 移除過度廣泛的全文搜尋比對，避免課程被誤判下架。

## 🚀 執行方式

1. 複製 `config.json.example` 為 `config.json`，依帳號設定內容。
2. 以 Windows 執行 `run.bat`，或使用已安裝依賴的 Python 執行 `ui.py`。
3. 在平台頁籤依需求勾選執行模式後按「▶️ 開始執行」：
   - `[ ] 本次跳過測驗，先做問卷`：優先處理已達標時數的問卷。
   - `[ ] 人機協同作答（彈窗回貼）`：遇到測驗時彈窗提供題目複製與答案回貼。

## ⚠️ 注意事項

- 平台可能限制測驗未通過時不可填問卷；程式會記錄結果後繼續下一門，不會假定問卷一定可填。
- 請勿在同一臺電腦同時啟動兩個臺北 E 大流程。
- `config.json` 可能包含帳密或 API 金鑰，請勿提交至版本庫。

## 🧪 開發驗證

主要開發與測試版本為 Python 3.13。可攜式發行版目前為了既有二進位套件相容性，仍封裝獨立的 Python 3.11 執行環境，兩者用途不同。

```powershell
python -m unittest discover -s tests -v
python -m py_compile app.py ui.py utils/helpers.py
```
