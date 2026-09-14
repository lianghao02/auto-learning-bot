# HANDOFF

## 目前狀態
可發布（V2.0.0 可攜版已建置並完成驗證）

## 本輪目標
以 V2.0.0 為新開發階段，同步完成兩大核心軌道任務：
- **軌道 A（UI/UX 商業自適應重構）**：徹底移除 `EntryPage` 靜態貼圖外殼（`login.png`）與 `screen_x=421, screen_y=132` 絕對座標硬編碼、消除 `btn.move` 導致之滑鼠邊界震顫、拔除宇宙粒子死碼、主視窗直連現代控制中心並增加初次引導橫幅。
- **軌道 B（題庫與選項配對演算法核心 — 抗選項隨機重排）**：修復 AI 存庫丟失選項真實文字、單選作答盲目優先使用數字索引 (1/2/3/4) 之核心缺陷，實施「文字內容本位 (Text-Content-First)」動態比對架構。

## 已完成
### 軌道 A：UI/UX 商業自適應重構
1. **`ui.py` 絕對座標與 EntryPage 徹底拔除**：
   - 移除舊版 `EntryPage`、`AddAccountPanel`、`DeleteAccountPanel`、`SettingsPanel`。
   - 建立獨立集中設定讀寫輔助函式 `load_config_data()` 與 `save_config_data()`。
   - 淨化逾 1,600 行歷史殘留死碼。
2. **`MainWindow` 單一現代控制中心架構**：
   - 移除 `self.stack` 多層堆疊與雙層入口，直接將 `ImmersivePage` 作為 Central Widget。
   - 清理重複宣告的 `_request_stop_current_pilot`、`_cleanup_pilot_async`、`closeEvent`。
3. **按鈕互動防震顫優化**：
   - 重構 `add_hover_effect`，徹底移除 `btn.move` 座標位移，改用純 `QGraphicsDropShadowEffect` 柔和陰影與原生 hover。
4. **純粹化莫蘭迪視覺風格**：
   - 徹底移除 `ParticleEffect` 類別及其相關調用與定時器。
5. **初次啟動引導橫幅 (Onboarding Banner)**：
   - 當本機尚未設定任何平臺帳號時，頂部自動顯示溫和的導引卡片，並提供「立即前往設定」按鈕一鍵跳轉至設定分頁。

### 軌道 B：題庫與選項配對演算法核心（抗選項隨機重排）
1. **e 等公務園 AI 滿分存庫真實文字化 (`app.py`)**：
   - 修訂第 1897~1903 行：當 Gemini 命中 `matched_opt` 時，`_ai_answered` 記錄真實選項文字 `opt_text`（若無才退回 val）。測驗獲得 100 分滿分寫入 SQLite 時，題庫保存標準文字而非純數字代號。
2. **文字本位選項配對核心引擎 (`utils/helpers.py` & `app.py`)**：
   - 新增並呼叫 `match_radio_option_index` 與 `normalize_choice_text`。
   - 將「文字匹配（Text Matching）」提升為最高優先級：在選項被平臺隨機重排（Shuffled）時，能依題庫標準解答文字自動精準命中對應的 radio，徹底根除舊版因優先取用數字代號（1/2/3/4）導致盲目選到錯誤位置之根本缺陷。
   - 保留對純數字代號（1/2/3/4）、字母代號（A/B/C/D）與是非題語意（對/是/O vs 錯/否/X）的向下相容。
3. **臺北 E 大動態填答防禦 (`quiz_bank.py`)**：
   - 重構 `_fill_answers` 支援可選 `questions` 參數，當答案包含文字時動態校驗當前頁面選項文字定位 radio，搭配既有 value 與 index 機制形成三層安全防禦。
4. **回歸測試與單元測試擴充 (`tests/test_quiz_answer_parsing.py`)**：
   - 新增 `test_match_radio_option_index_text_first` 驗證選項順序隨機洗牌時 100% 選中正確文字對應 radio。
   - 新增 `test_match_radio_option_index_true_false_semantics` 驗證是非題語意比對。
   - 全套測試增至 67 項，通過率 100%。

5. **版本號全域對齊**：
   - `version.txt`、`app.py`、`CHANGELOG.md`、`README.md` 全數對齊至 `V2.0.0`。

## 刻意未修改
- 未更換底層技術棧（維持 Python 3.13 + PySide6）。
- 未引進外部商業 DRM 授權伺服器。

## 本輪發布補充
- 修正嵌入式 Python 的 `._pth` 匯入路徑，讓可攜版 runtime 能從 `current/runtime/` 正確載入上層程式根目錄中的 `app`、`utils` 與 `models`。
- 已建置 `dist/AdminEfficiencyPilot_V2.0.0_Portable.zip`；SHA-256 為 `e8cfcfae52a9f70eaa3abf1959d7cac26dc3a9978af071f45518314519f0bcdf`。
- 已確認壓縮檔不含使用者 `config.json`、`questions.db` 或執行日誌，且其 runtime 可成功匯入 `app`、`quiz_bank`、`ui`。

## 驗證結果
### 已執行
1. **全套自動化單元與回歸測試**：
   - 指令：`.\\python_embed\\python.exe -m unittest discover -s tests -p "test_*.py"`
   - 結果：`Ran 67 tests in 1.329s, OK`（67 項測試 100% 全數通過）。
3. **可攜版 runtime 匯入檢驗**：
   - 結果：`PORTABLE_IMPORT_OK`。
2. **無介面與離屏實例化檢驗**：
   - 驗證主視窗乾淨初始化、視窗標題包含 `V2.0.0`、預設尺寸為 `1000x670`。
   - 驗證有帳號時引導橫幅自動隱藏；空帳號設定時引導橫幅自動展示。

### 尚未驗證
- 實際 Windows 桌面上人工視覺審查。

### 已知風險
- 無阻斷性風險。舊題庫與舊設定檔 `data/config.json` 完全向下相容。

## Git 狀態
- Commit：本輪 V2.0.0 發布提交已建立（詳見 Git log）
- Push：待推送至 `origin/feature/v2.0-commercial-uiux`
- Working Tree：預期為 Clean
- Branch：feature/v2.0-commercial-uiux

## 下一步
1. 推送 V2.0.0 發布提交至功能分支。
2. 建立 GitHub Release，附上 Portable ZIP 與 SHA-256 校驗檔。
