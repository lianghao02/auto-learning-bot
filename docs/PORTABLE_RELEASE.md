# 可攜式發行流程

## 建置

在專案根目錄執行：

```powershell
python scripts/build_portable_release.py
```

建置結果位於 `dist/`：

- `行政效能領航員_V3.1.0_Portable/`：解壓後的完整離線版本。
- `AdminEfficiencyPilot_V3.1.0_Portable.zip`：交付與發行之可攜壓縮檔。
- `AdminEfficiencyPilot_V3.1.0_Portable.zip.sha256`：ZIP 完整性雜湊。

專案主要開發、測試與可攜式發行流程全面統一為 Windows Python 3.13 64-bit 執行環境。使用者端不需要安裝 Python、pip，也不會於首次啟動時連線下載依賴。

## 降低防毒誤判

- 發行版不使用 PyInstaller `--onefile`，避免自解壓行為。
- 保留 Python 官方 `python.exe`／`pythonw.exe`，程式碼及依賴以一般檔案方式部署。
- 不包含 `.venv`、個人 `config.json`、日誌、快取、爬蟲及開發工具。
- 每次建置均產生 SHA-256，交付時可讓資訊單位先核對與掃描。

無簽章的下載檔仍可能受到 SmartScreen 或機關政策攔截。正式大量部署時，應使用可信任的 Authenticode 程式碼簽章，或請機關資訊單位透過集中軟體派送、允許清單部署。
