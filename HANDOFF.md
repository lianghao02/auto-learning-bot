# HANDOFF

## 核心元資料 (Metadata)
- **Repository**：lianghao02/auto-learning-bot
- **Branch**：main
- **Commit SHA**：`595a2a74`（雙平臺穩定性與安全修補基準；工作目錄含模組化拆分與 `PySide6-Essentials` 瘦身待提交）
- **Skill Version**：lianghao-development v1.0.0
- **Task Type**：IMPROVE
- **Local Path Hint**：07_auto-learning-bot

---

## 目前狀態
2026-11-24：在 `595a2a74` 穩定基準之上，完成四階段**零介面變動、100% 向下相容**之架構模組化拆分與相依套件瘦身，並通過離線 UI 檢測與全套單元測試（尚未 commit，待使用者確認是否提交推送）。

## 本輪已完成工作 (Completed)
1. **階段 1 — 相依套件瘦身（`PySide6-Essentials`）**：
   - `requirements.txt` 與 `requirements-release.txt` 改用 `PySide6-Essentials==6.11.2`，移除未使用的 `PySide6` meta-package 與 `PySide6-Addons`（保留 `ddddocr` 必要的 `opencv-python`）。
   - `python_embed\Lib\site-packages` 體積由 `968.0 MB` 降至 `576.5 MB`（淨減少 `391.5 MB`）。
2. **階段 2 — 介面檔 `ui.py` 模組化拆分**：
   - `ui.py` 由 3,259 行降至 957 行（保留 `ImmersivePage`、`MainWindow` 與所有原名公開匯出門面）。
   - 拆出 `ui_parts/shared.py`（共用樣式、版本更新解析與動態設定橋接）、`ui_parts/dialogs.py`（`UpdateDialog`、`InteractiveQuizDialog`）、`ui_parts/panels.py`（`PlatformTabPanel`、`AccountSettingsTabPanel`）。
3. **階段 3 — 核心檔 `app.py` 模組化拆分**：
   - `app.py` 由 5,392 行降至 1,369 行（保留 `AdminEfficiencyPilot` 主協調器、`run()` 主迴圈、`_PACKAGE_DASHBOARD_SCRIPT` 與原名公開符號匯出）。
   - 拆出 `egov/helpers.py`（純函式與測試 mock 穿透代理）、`egov/question_store.py`（SQLite 題庫與 AI 單題查詢）、`egov/auth.py`（eCPA／我的E政府登入、彈窗關閉、Session 保養與 Auto-Healing）、`egov/exam_survey.py`（自動測驗、AI 批次補答、交卷判分、`s_main` 複查、同源 `fetch` 抓正解與問卷）、`egov/study.py`（課程 API、`/info/` 下架判讀、教室定位與時數累積迴圈）。
4. **階段 4 — 可攜版打包設定與文件同步**：
   - `scripts/build_portable_release.py` 之 `APP_DIRS` 與建置期匯入檢查納入 `egov` 與 `ui_parts`。
   - `tests/test_portable_update.py` 新增打包目錄完整性與精簡 Qt 套件檢查回歸測試。
   - 同步更新 `docs/upstream-maintenance.md`、`CHANGELOG.md` 與 `HANDOFF.md`。

## 異動檔案 (Changed Files)
- 相依與打包：`requirements.txt`、`requirements-release.txt`、`scripts/build_portable_release.py`。
- 介面模組：`ui.py`、`ui_parts/__init__.py`、`ui_parts/shared.py`、`ui_parts/dialogs.py`、`ui_parts/panels.py`。
- e 等核心模組：`app.py`、`egov/__init__.py`、`egov/helpers.py`、`egov/question_store.py`、`egov/auth.py`、`egov/exam_survey.py`、`egov/study.py`。
- 測試與文件：`tests/test_portable_update.py`、`docs/upstream-maintenance.md`、`CHANGELOG.md`、`HANDOFF.md`。

## 驗證結果 (Validation)
- `python_embed\python.exe -B -s -W error -m py_compile`：全專案修改檔零警告通過，AST 未定義名稱掃描為 0。
- `pwsh -NoProfile -File setup_and_run.ps1 -CheckOnly`：通過（Python 3.13.0，`pip check` 無相依破損）。
- `tools/office_ui_qa.py`（`QT_QPA_PLATFORM=offscreen`）：通過（`1366x720`，`errors: []`，`table_rows_visible: 13`）。
- `pwsh -NoProfile -File scripts/run_tests.ps1`：全套 `unittest` 100% 通過（194 項測試）。
- `git diff --check`：通過。

## Git 狀態與下一步建議動作
- **Branch**：`main`（HEAD 為 `595a2a74`，本次模組化拆分與瘦身變更待使用者確認後 commit / push）。
- **下一步建議**：確認提交推送後，可實機執行雙平臺或直接執行 `scripts/build_portable_release.py` 產出瘦身後的可攜式發行包。
