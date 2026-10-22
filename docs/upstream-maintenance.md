# 上游差異與模組維護邊界（2026-10-22）

## 查核基準
- 本地 main：52569e10e，version.txt 為 V2.0.1；原有 UI、日誌、安全與 AI 失敗處理均沿用。
- fetch 後 upstream/main：9360d7c0a（2026-10-22）；共同祖先 38322d2eca68a6e408ce4b6d199f9ed14e1bec53。
- 以固定參照計算，上游獨有 4681 個提交、本地獨有 111 個。上游包含大量題庫與自動審查提交，不能把提交數當成功能數。
- 本輪只 fetch upstream，未 merge、rebase、改遠端或執行平台操作。

上游來源：https://github.com/waynelord0628-beep/auto-learning-bot/tree/9360d7c0a 。本地現況以本機 Git 與程式為準。

## 維護結論
目前已是具有大量本地修正的 fork。採「本地功能獨立維護、上游按具體問題挑選」作為本輪處置，不自動整批合併。這不代表永遠放棄上游；日後採用某筆修正時，先確認本地是否已有等效處理，補可重現案例，再挑選必要部分。

不為縮短 app.py 而拆登入、測驗或研習流程。近期上游確實仍修改這些區域，現在大搬移只會讓後續對照更困難。可在下一次具體需求中抽純函式或穩定的輸入輸出邊界，每次獨立提交。

## 值得另案核對的上游候選
自先前本機 upstream 784f50414 更新至本次參照，核心差異涉及 app.py、quiz_bank.py、taipei_eda_course.py 與新增 utils/ecpa_login.py；不是只有題庫資料。

| 候選 | 固定提交 | 採用前必須證明 |
|---|---|---|
| 臺北多選測驗 | b9bd07d7b | 本地是否缺少同種題型；以去識別 HTML／選項樣本重現，保留既有作答驗證與題庫回寫限制 |
| 拒答重試、只保存已確認回饋 | 3590ef5e0 | 不覆蓋本地 Gemini 備援、逾時延後重考與不猜整卷的修正 |
| 研習時數與章節間完成確認 | ac3ea10dc、b46ebc9ee | 本地課程狀態與既有完成判定是否已涵蓋；不能只看文字警語就判定完成 |
| eCPA 登入流程 | be3aad853 | 登入頁是否實際改變；驗證碼由使用者依平台流程處理，不以文件整理宣稱可自動完成 |

本輪沒有採用上述程式，也沒有以真實帳號驗收，故不得列為已修復或新增功能。

## 模組地圖
| 檔案 | 職責 | 對應驗證 |
|---|---|---|
| app.py | AdminEfficiencyPilot 主協調器、登入、e等課程／測驗／問卷及研習流程 | course_completion_logic、session_refresh、package_enrollment、ai_outage_handling、window_visibility |
| taipei_eda_course.py | 臺北 E 大課程與 SCORM 流程 | taipei_scan_safety、course_completion_logic |
| quiz_bank.py | 本地／共用題庫與 AI 答案處理 | ai_batch_solver、quiz_answer_parsing、interactive_quiz_dialog、security |
| models/course_state.py、utils/course_dashboard.py | 課程狀態與儀表板摘要 | course_state_model、course_dashboard |
| ui.py、utils/office_theme.py | PySide6 工作台與集中配色 | office_theme、interactive_quiz_dialog；介面異動另做 UI QA |
| utils/log_feed.py | 雙平台日誌解析與顯示模型 | log_feed |
| utils/app_paths.py、utils/config_io.py | 路徑、設定與資料庫入口 | app_paths、security |
| utils/security.py、utils/webdriver_mgr.py | 敏感資料防護、URL 驗證與驅動管理 | security、window_visibility |
| utils/portable_update.py、scripts/auto_update.ps1 | 可攜版本更新與交接 | portable_update；Windows 更新流程依既有模擬腳本 |

測試名稱指 tests/test_<名稱>.py。全套沿用 `pwsh -NoProfile -File scripts/run_tests.ps1`，由腳本選擇專案 embedded runtime 與隔離路徑。本輪只核對檔案與測試對應，沒有重新執行整套平台測試。

## 拆分準則
1. 先補行為案例，確認輸入、回傳值、例外與副作用。
2. 純函式優先；共用 self、driver、session、停止旗標與 UI callback 的整段流程先保留。
3. 不互相耦合臺北 E 大與 e等流程，不更換 Selenium。
4. 不移動本機設定、題庫、使用者資料或 embedded 發布環境。
5. 一次一組、獨立提交；不把上游同步、UI 重畫與重構混在同一筆。

## 本輪結果與未完成
本輪新增維護依據與模組地圖，無產品程式變更；upstream 仍保留。上游候選採用、真實平台登入與成績確認，以及新版本發布均未進行。
