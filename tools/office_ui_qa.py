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
    for log_line in [
        r"18:43:27 [INFO] 🔑 已確認背景 Driver 進程狀態（版本相符 155.x）: D:\drivers\chromedriver.exe",
        r"18:43:34 [INFO] ✅ 臺北E大登入成功",
        r"18:45:03 [INFO] 📋 [1/14] 正在協助研習：Word密技大公開",
        r"18:45:18 [WARNING] ⚠️ 詳程【單元尚未載入認證介面，正在重試】",
        r"18:46:22 [INFO] 📚 研習進度：00:34:39 / 01:03:00 [##########----------] 55.0%",
        r"18:47:13 [INFO] 進入單元：電子郵件格式設計與技巧...",
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
