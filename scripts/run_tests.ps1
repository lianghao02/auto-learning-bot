[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# 設定 UTF-8 編碼環境，防範 Windows CP950/Big5 下 emoji 導致 UnicodeEncodeError
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

$projectRoot = Split-Path -Parent $PSScriptRoot
$embedPython = Join-Path $projectRoot 'python_embed\python.exe'

$pythonCmd = if (Test-Path -LiteralPath $embedPython) {
    $embedPython
} else {
    throw '找不到專案 embedded runtime；不改用全域 Python。'
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "【自動化測試執行器】使用 Python: $pythonCmd" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

# 透過 -c 動態加入專案根目錄至 sys.path，相容 python_embed 隔離環境
$testRunnerCode = @'
import sys
import unittest
from pathlib import Path

# 防護標準輸出編碼
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

root_dir = str(Path('.').resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

loader = unittest.defaultTestLoader
suite = loader.discover(start_dir='tests', pattern='test_*.py')
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
'@

Push-Location $projectRoot
try { & $pythonCmd -B -s -c $testRunnerCode; $testExit = $LASTEXITCODE } finally { Pop-Location }
$LASTEXITCODE = $testExit
if ($LASTEXITCODE -ne 0) {
    Write-Error "測試未全數通過，ExitCode=$LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "`n測試通過：全套單元與回歸測試 100% 通過！" -ForegroundColor Green
exit 0
