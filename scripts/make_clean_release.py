import os
import shutil

src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parent_dir = os.path.dirname(src_dir)
release_dir = os.path.join(parent_dir, "auto-learning-bot_Release")

# 若已存在先刪除
if os.path.exists(release_dir):
    shutil.rmtree(release_dir, ignore_errors=True)

os.makedirs(release_dir, exist_ok=True)

# 必須複製的資料夾與檔案
items_to_copy = [
    "python_embed",
    "drivers",
    "icons",
    "patches",
    "scrapers",
    "tools",
    "utils",
    "answers.json",
    "app.py",
    "config.json.example",
    "questions.db",
    "quiz_bank.py",
    "requirements.txt",
    "run.bat",
    "taipei_eda_course.py",
    "ui.py",
    "usage_tracker.py",
    "version.txt",
    "README.md"
]

print("=== Start packaging clean release ===")

for item in items_to_copy:
    s = os.path.join(src_dir, item)
    d = os.path.join(release_dir, item)
    if os.path.exists(s):
        if os.path.isdir(s):
            shutil.copytree(s, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log"))
        else:
            shutil.copy2(s, d)
        print(f"Copying: {item}")

print(f"\n[OK] Release directory created successfully at:\n{release_dir}")
