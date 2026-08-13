# 行政效能領航員（auto-learning-bot）

[![Version](https://img.shields.io/badge/version-V2.2.1-blue.svg)](https://github.com/lianghao02/auto-learning-bot)
[![Python](https://img.shields.io/badge/Python-3.11%2B-green.svg)](https://www.python.org/)
[![Driver](https://img.shields.io/badge/Driver-Selenium-purple.svg)](https://www.selenium.dev/)

行政效能領航員提供臺北 E 大與 e 等公務園的課程學習輔助流程，包含時數累積、測驗與問卷處理，以及本機題庫比對。

## V2.2.1 重點

- 新增「本次跳過測驗，先做問卷」選項；此選項不會寫入帳號或系統設定。
- 僅在課程時數已達標時，才會略過測驗並嘗試填寫問卷；時數不足的課程不會進測驗或問卷，並會跳至下一門。
- 臺北 E 大執行鎖改以執行中的 PID 判斷，不會因流程超過六小時而誤判失效。
- 更新檢查改為目前專案的 GitHub `origin`：`lianghao02/auto-learning-bot`。

## 執行方式

1. 複製 `config.json.example` 為 `config.json`，依帳號設定內容。
2. 以 Windows 執行 `run.bat`，或使用已安裝依賴的 Python 執行 `ui.py`。
3. 在平台頁籤按「開始執行」。如本次只要優先處理已達時數的問卷，可勾選「本次跳過測驗，先做問卷」。

## 注意事項

- 平台可能限制測驗未通過時不可填問卷；程式會記錄結果後繼續下一門，不會假定問卷一定可填。
- 請勿在同一臺電腦同時啟動兩個臺北 E 大流程。
- `config.json` 可能包含帳密或 API 金鑰，請勿提交至版本庫。

## 開發驗證

```powershell
python -m unittest discover -s tests -v
python -m py_compile app.py ui.py taipei_eda_course.py
```
