# HANDOFF

## 核心元資料 (Metadata)
- **Repository**：lianghao02/auto-learning-bot
- **Branch**：main
- **Commit SHA**：6d672f9b（本輪提交前基準；包含本交接的最新 SHA 以 Git 記錄為準）
- **Skill Version**：v1.0.0
- **Task Type**：FIX
- **Local Path Hint**：07_auto-learning-bot

---

## 目前狀態
原有兩個未提交檔案的審查與隔離驗證完成，日誌資料夾修正可交付；正式可攜版尚未重新打包。

## 本輪目標
依使用者授權，審查 `ui.py` 與 `utils/app_paths.py` 的既有修改，驗證後提交，完成前輪 GitHub 同步留下的兩個檔案。

## 基準與已確認事實 (Baseline & Confirmed Facts)
- 開始時 main 與 origin/main 一致，只剩上述兩個原有修改；前輪環境修復已提交於 6d672f9b，成果繼承。
- HEAD 的介面以無參數呼叫要求 name 參數的 log_path，日誌按鈕會失敗。
- 既有修改提供 log_dir、log_path 預設 app.log，介面明確指定檔名並建立目錄；原有兩個檔案本輪沒有再改寫。

## 已完成 (Completed)
- 審查日誌路徑、既有指定檔名相容性及可攜版 current／data 分離；沒有發現阻斷性問題。
- 增加 5 項回歸：預設日誌路徑與既有內容保留、指定檔名邊界、可攜版資料位置、真實 Qt 按鈕成功流程、資料夾開啟失敗提示。
- HEAD 隔離對照 10 項中出現 2 失敗、1 錯誤，重現缺少參數及按鈕故障；目前來源完整 75 項全部通過。
- README 記錄已修復問題與舊可攜版尚未包含修正的邊界。

## 異動檔案 (Changed Files)
ui.py、utils/app_paths.py、tests/test_app_paths.py、tests/test_interactive_quiz_dialog.py、README.md、HANDOFF.md。

## 刻意未修改 (Do Not Do / Deliberately Omitted)
未更動課程自動化、AI 作答、帳號設定、全域 Python／PATH、依賴、embedded 環境、個人題庫或正式發布包；不結束現有使用者程式、不解除檔案鎖定、不回復活動中的資料檔案。

## 尚未完成 (Remaining Work)
- **P1 (阻斷/必須)**：無本輪已確認的阻斷性問題。
- **P2 (重要/當次)**：本輪必要修正與驗證已完成；提交與同步的實際證據以 Git 區塊及遠端 SHA 為準。
- **P3 (改善建議/暫緩)**：正式可攜版重新打包與 Win10／乾淨電腦驗收另案處理；全域套件去重維持暫緩。

## 驗證結果 (Validation)
### 已執行測試與結果
- 使用專案 embedded Python 3.13.0，帶 -B／-s，在中文空白路徑的隔離 current 來源快照執行現有 unittest 探索流程；75 項通過，0 失敗、0 錯誤、0 略過。
- Qt 使用 offscreen，實際建立 PlatformTabPanel 並點擊已連接的按鈕；Windows 資料夾開啟器使用 mock，包含失敗處理。網路連線在測試行程內阻斷。
- Python AST 語法解析通過；驗證前後 30 份原始 Python 檔案雜湊一致。
- 7 份可讀個人資料雜湊一致。6 份資料在建立基準時鎖定，沒有起始雜湊；期間原 data 的日誌與 SQLite 檔案有活動變動，WAL／SHM 後續消失，未將其標示雜湊不變，沒有回復或改寫。
- Git fetch 後 ahead／behind 為 0／0；六個檔案的差異格式與新增敏感資料檢核通過。
- 本機詳細證據在控制中心 Git 忽略的 artifacts/07-log-review-372f8afaaff7426082bb214314cc010d，不隨版本庫發布。

### 尚未驗證項目
沒有操作真實研習帳號、呼叫 AI 服務或進行線上課程；未實際開啟檔案總管、重新打包或驗證正式更新切換。

### 已知風險 (Known Risks)
原始碼修正不會自動套用到舊可攜發布包。鎖定與活動中的個人資料沒有完整雜湊基準，不能宣稱全部資料檔案在本輪期間保持不變。

## Git 狀態
- Commit：本輪六個檔案以單一 fix 提交；實際 SHA 見 git log -1。
- Push：依前輪 GitHub 同步授權，正常推送 origin/main，實際遠端 SHA 以 git ls-remote 核對。
- Working Tree：提交前為上述六個檔案；提交與核對完成後應為 Clean，以 git status 實際結果為準。
- Branch：main。

## 下一步建議動作 (Next Recommended Action)
本輪提交與同步完成後停止擴大修改。日後若要求更新可攜成品，再依既有發布門檻重建並驗收；課程流程與資料保持既有邊界。

## 發布狀態 (Release Status)
原始碼可交付；本輪沒有建立新 Release 或取代正式可攜包。
