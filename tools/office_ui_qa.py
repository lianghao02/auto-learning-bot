"""以合成資料檢查不同解析度與 Qt 縮放，輸出畫面供人工檢視。"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument("--baseline", action="store_true")
parser.add_argument("--width", type=int, default=1366)
parser.add_argument("--height", type=int, default=768)
parser.add_argument("--scale", type=float, default=1)
args = parser.parse_args()
os.environ["QT_QPA_PLATFORM"] = "windows" if os.name == "nt" else "offscreen"
os.environ["QT_SCALE_FACTOR"] = str(args.scale)
from PySide6.QtWidgets import QApplication, QPushButton
app = QApplication([])
import ui
if args.baseline:
    code = subprocess.check_output(["git", "show", "HEAD:ui.py"], cwd=ROOT).decode("utf-8")
    exec(compile(code, str(ROOT / "ui.py"), "exec"), ui.__dict__)
app.setStyleSheet(ui.GLOBAL_QSS)
from models.course_state import CourseState, CourseStatus
output = ROOT / "dist" / "ui-qa"
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as tmp, patch("ui.CONFIG_PATH", str(Path(tmp)/"config.json")):
    page = ui.ImmersivePage(lambda: None)
    page.resize(round(args.width/args.scale), round((args.height-48)/args.scale))
    page.show()
    panel = page.taipei_panel
    panel.update_account_info("示範使用者", "")
    for i in range(16):
        status = list(CourseStatus)[i % len(CourseStatus)]
        panel._handle_course_state_update(CourseState(str(i), f"示範課程 {i+1}：行政實務與資安研習", "taipei_eda", status=status, progress_pct=50 if status == CourseStatus.LEARNING else 0, reason="示範狀態說明", next_step="依目前狀態繼續處理"))
    panel.set_running_state(True, "● 研習中：正在處理課程")
    panel.log_view.clear()
    # 混合臺北E大（無時間戳 print）與 e等公務園（logging）兩種原始格式
    for log_line in [
        "12:21:41 [WARNING] ⚠️ 研習期間被平臺登出（Alert Text: 請先登入會員）",
        "12:21:48 [INFO] 🔑 使用我的E政府登入...",
        "12:21:56 [INFO] ✅ E政府登入成功",
        "12:23:19 [INFO] 📋 重新登入後課程總數：682 筆",
        "=== 測驗 (course_id=3180) ===",
        "  [題庫] 從 GAS 載入 10 題（course_id=3180）",
        "  ✓ [庫] 學習一種面對問題的新觀點，就是把注意力放在探討如何「解決... → val=1",
        "  ✓ [庫] 一個人通常有固定的表達方式或手勢動作，只要我們細心觀察，... → val=0",
        "  [成績1] 分數 得80.00分(滿分為100.00分)（80 分｜及格：是）",
        "  🎉 測驗達標通過！【分數 得80.00分(滿分為100.00分)】（門檻: 70 分）",
        "┌────────────────────────────────────────────┐",
        "│ 🎯 行政效能領航員 - 即時研習成效儀表板 │",
        "│ 📚 最新完成課程：【個案談判技巧與實務演練】",
        "│ 🏆 測驗成果：✅ 及格 ｜ 問卷：✅ 已完成",
        "└────────────────────────────────────────────┘",
        "處理: 媒體互動技巧",
        "  🎯 依課程特定要求設定目標時數：120 分鐘",
        "  📊 研習進度：00:00:05 / 02:06:00 [--------------------] 0.1%",
        "  📍 進入單元：一、前言...",
        "      ⚠️ 點擊失敗，跳過",
        "      ⚠️ 點擊失敗，跳過",
        "      ⚠️ 點擊失敗，跳過",
        "  📊 研習進度：00:34:39 / 02:06:00 [######--------------] 27.5%",
        "  📍 進入單元：二、認識媒體與媒體重要性...",
        "  📊 研習進度：00:58:45 / 02:06:00 [#########-----------] 46.6%",
        "  📍 進入單元：九、如何面對媒體...",
    ]:
        panel._append_text_safe(log_line)
    errors=[]
    for tab, label in [(0,"courses"),(1,"egov"),(2,"settings"),(0,"log")]:
        page.tabs.setCurrentIndex(tab)
        panel.workspace_tabs.setCurrentIndex(1 if label=="log" else 0)
        app.processEvents()
        prefix = "before" if args.baseline else "after"
        page.grab().save(str(output/f"{prefix}-{args.width}-{args.height}-{args.scale}-{label}.png"))
        for btn in page.findChildren(QPushButton):
            if not btn.isVisible():
                continue
            # 設定捲動區外的按鈕可透過捲動到達，不要求同時顯示。
            if page.settings_panel.isAncestorOf(btn):
                continue
            point=btn.mapTo(page, btn.rect().topLeft())
            if point.x()<0 or point.y()<0 or point.x()+btn.width()>page.width() or point.y()+btn.height()>page.height():
                errors.append(f"{label}: 按鈕超出可視範圍 {btn.text()}")
    result={"size":[page.width(),page.height()],"scale":args.scale,"errors":errors,"table_rows_visible":panel.course_table.viewport().height()//panel.course_table.verticalHeader().defaultSectionSize()}
    print(json.dumps(result,ensure_ascii=True))
    page.close()
    if errors:
        raise SystemExit(1)
