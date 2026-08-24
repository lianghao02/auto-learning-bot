# 實作計畫

## 目標與驗收條件

- 以單一版本來源建立 Python 3.13 Windows 可攜版。
- 將程式檔、種子題庫與使用者資料明確分流，更新不得覆蓋個人資料。
- GitHub Release 檢查支援 ETag、Markdown 發布說明與 Release asset digest。
- Portable ZIP 更新須經 staging、Zip Slip 防護、內容驗證、同磁碟切換與失敗還原。
- Python 3.13 語法檢查、既有測試、新增安全測試與可攜版打包演練通過。

## 不做範圍

- 不安裝或升級本機套件。
- 不修改全域設定或 Skill。
- 不 commit、push 或發布 GitHub Release。
- 不登入或操作實際研習平台。

## 現況與限制

- 核心版本目前為 V3.0.1；封裝腳本改由 `version.txt` 動態取得版本。
- `python_embed` 已是 Python 3.13；封裝腳本已改為動態建立 `python313._pth`。
- 更新介面已改接 GitHub Release Portable ZIP，舊 EXE／Google Drive 更新流程已移除。
- 設定、題庫與日誌已分流至 `data/`，舊版根目錄資料採複製相容，不搬移或刪除。

## 已確認決策

- 版本以 `version.txt` 為封裝與 Release 資產名稱的單一來源。
- 採 `data/` 作為新安裝的使用者資料目錄，並保留舊版根目錄資料的自動遷移／相容讀取。
- 發行包內使用 `assets/questions_seed.db` 提供初始題庫，不將執行中的 `questions.db` 當成使用者資料打包。
- 更新器以 GitHub Release asset 的 `digest` 為自動更新必要條件；缺少 digest 時只允許手動下載。
- staging 以短名稱建立於安裝目錄內，並支援 Windows extended path，確保同磁碟切換且避免深層套件路徑超過 `MAX_PATH`。

## 工作清單

- [x] 建立共用應用程式／資料路徑工具並導入設定、題庫與日誌｜路徑單元測試
- [x] 修正 Python 3.13 runtime、動態版本、種子題庫與 ZIP 雜湊輸出｜打包演練
- [x] 將 UpdateDialog 接入實際流程並安全顯示 Markdown｜UI 離屏建立測試
- [x] 實作 Release API ETag、精確 ZIP 資產選擇與 digest 傳遞｜回應解析測試
- [x] 實作 Portable ZIP 安全解壓與內容驗證｜惡意 ZIP 與完整產物測試
- [x] 實作外部更新腳本的同磁碟切換、備份與 rollback｜成功／故障模擬更新測試
- [x] 執行完整測試與語法檢查｜Python 3.13 指令結果

## 風險與因應

- 舊版資料位於根目錄：採相容尋址與一次性複製，避免直接搬移或刪除。
- Windows 檔案占用：更新器等待主 PID 結束後才切換，逾時則停止並保留舊版。
- Release digest 缺失：禁止自動安裝並導向手動下載。
- 原子切換後新版無法啟動：由更新器執行啟動健康檢查，失敗時還原舊目錄。

## 驗證紀錄

- Python 3.13 語法檢查：通過。
- `python -m unittest discover -s tests -v`：32 項全部通過。
- PowerShell 來源與封裝腳本 parser：通過。
- Windows PowerShell 5.1 隔離更新演練：成功切換與故障 rollback 均通過。
- 最終 Portable runtime：Python 3.13.0，PySide6、Selenium、requests、OpenCV、NumPy、ddddocr、psutil 匯入通過。
- 最終 ZIP：6,434 筆項目；無頂層 `data/`、個人 `config.json`、執行中 `questions.db`、日誌、`__pycache__` 或 bytecode。
- 最終 ZIP 完整 staging、內部 manifest 驗證及暫存清理：通過。
- 最終 ZIP SHA-256：`8892599a369cdba544288ee07f6340bbf61df912fc6b9f03aa4b38f991be8eb3`。

## 剩餘問題

- 尚未對真實已安裝使用者資料執行就地更新；已以隔離目錄與實際 Python 3.13 runtime 完成等價切換／還原演練。
