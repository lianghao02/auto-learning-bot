[CmdletBinding()]
param(
    [string]$TargetProject = '',
    [switch]$NoLaunch,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectDir = $PSScriptRoot
$projectName = Split-Path -Leaf $projectDir
$embedDir = Join-Path $projectDir 'python_embed'
$embedPython = Join-Path $embedDir 'python.exe'
if ($CheckOnly) {
    if (-not (Test-Path -LiteralPath $embedPython -PathType Leaf)) { throw '找不到專案 embedded runtime；檢查模式不會安裝。' }
    & $embedPython -B -s -c "import sys,site,sqlite3; assert sys.version_info[:2] == (3,13); assert not site.ENABLE_USER_SITE; print(sys.version,sys.executable)"
    if ($LASTEXITCODE -ne 0) { throw 'Runtime 檢查失敗。' }
    & $embedPython -B -s -m pip --disable-pip-version-check check
    if ($LASTEXITCODE -ne 0) { throw '套件相依檢查失敗。' }
    return
}

function Set-EmbeddedPythonImportPath {
    param([Parameter(Mandatory = $true)][string]$RuntimeDirectory)

    # Embedded Python 啟用 ._pth 後不會自動加入專案根目錄；必須明確加入
    # runtime 的上層，否則 ui.py 無法匯入同層的 app、utils 與 models。
    $pthFile = Get-ChildItem -LiteralPath $RuntimeDirectory -Filter "*._pth" -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pthFile) {
        $zipName = [IO.Path]::GetFileNameWithoutExtension($pthFile.Name) + '.zip'
        $pthLines = @(
            $zipName,
            '.',
            '..',
            'Lib\site-packages',
            'import site'
        )
        $asciiBytes = [System.Text.Encoding]::ASCII.GetBytes(($pthLines -join "`r`n") + "`r`n")
        [System.IO.File]::WriteAllBytes($pthFile.FullName, $asciiBytes)
    }
}



# 判定進入點檔案
$entryPoint = if (Test-Path -LiteralPath (Join-Path $projectDir 'main.py')) {
    'main.py'
} elseif (Test-Path -LiteralPath (Join-Path $projectDir 'ui.py')) {
    'ui.py'
} elseif (Test-Path -LiteralPath (Join-Path $projectDir 'app.py')) {
    'app.py'
} else {
    'main.py'
}

# 判定需求檔
$reqFile = if (Test-Path -LiteralPath (Join-Path $projectDir 'requirements.txt')) {
    Join-Path $projectDir 'requirements.txt'
} elseif (Test-Path -LiteralPath (Join-Path $projectDir 'requirements-release.txt')) {
    Join-Path $projectDir 'requirements-release.txt'
} elseif (Test-Path -LiteralPath (Join-Path $projectDir 'portable-requirements.txt')) {
    Join-Path $projectDir 'portable-requirements.txt'
} else {
    $null
}

Write-Host '=================================================================' -ForegroundColor Cyan
Write-Host "【智慧自癒啟動系統】專案：$projectName" -ForegroundColor Yellow
Write-Host '=================================================================' -ForegroundColor Cyan

# ----------------------------------------------------------------------
# 階段 1：檢查是否已具備現成的 Python 可攜環境 (嚴格驗證模組)
# ----------------------------------------------------------------------
$isEnvironmentReady = $false
if (Test-Path -LiteralPath $embedPython) {
    $testRun = & "$embedPython" -B -s -c "import sys, sqlite3, PySide6, selenium, requests, colorama, psutil; assert sys.version_info[:2] == (3,13); print('READY')" 2>$null
    if ($testRun -match 'READY') {
        $isEnvironmentReady = $true
    }
}

if (-not $isEnvironmentReady) {
    if (Test-Path -LiteralPath $embedDir) { throw '既有 runtime 驗證失敗；保留現場，不自動刪除或覆寫。' }
    Write-Host "[環境檢查] 偵測到環境尚未就緒，正在啟動自動自癒佈置..." -ForegroundColor Yellow
    Write-Host ''

    # 本機 ZIP：專案、控制中心下載區、可選快取環境變數、使用者下載區。
    $searchPaths = @(
        $projectDir,
        (Join-Path (Split-Path -Parent $projectDir) "00_Dev-Control-Center\downloads"),
        $env:LIANGHAO_DOWNLOAD_CACHE,
        (Join-Path $env:USERPROFILE "Downloads")
    )

    $zipPath = $null
    foreach ($sp in $searchPaths) {
        if ($sp -and (Test-Path -LiteralPath $sp)) {
            $found = Get-ChildItem -LiteralPath $sp -Filter "python-3.13*-embed-amd64.zip" -File -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) {
                $zipPath = $found.FullName
                break
            }
        }
    }

    if (-not $zipPath) {
        $zipPath = Join-Path $projectDir 'python-3.13.0-embed-amd64.zip'
    }

    # ------------------------------------------------------------------
    # 階段 2：取得 ZIP 壓縮包
    # ------------------------------------------------------------------
    if (-not (Test-Path -LiteralPath $zipPath)) {
        $downloadUrl = "https://www.python.org/ftp/python/3.13.0/python-3.13.0-embed-amd64.zip"
        Write-Host "[1/4] 本機未發現 ZIP，正在從 Python 官方下載可攜核心 (11.9 MB)..." -ForegroundColor Green
        Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing
        Write-Host "   下載完成：$zipPath" -ForegroundColor Gray
    } else {
        Write-Host "[1/4] 發現本機 Python ZIP 母檔：$zipPath（略過下載）" -ForegroundColor Green
    }

    # ------------------------------------------------------------------
    # 階段 3：解壓縮至 python_embed
    # ------------------------------------------------------------------
    Write-Host "[2/4] 正在解壓縮可攜核心至 python_embed/ 資料夾..." -ForegroundColor Green
    if (Test-Path -LiteralPath $embedDir) {
        Remove-Item -LiteralPath $embedDir -Recurse -Force
    }
    Expand-Archive -LiteralPath $zipPath -DestinationPath $embedDir -Force

    # ------------------------------------------------------------------
    # 階段 4：解除 ._pth 限制與補全 _sqlite3
    # ------------------------------------------------------------------
    Write-Host "[3/4] 正在解除環境隔離限制並配置 pip 套件管理器..." -ForegroundColor Green
    Set-EmbeddedPythonImportPath -RuntimeDirectory $embedDir

    $targetSqlitePyd = Join-Path $embedDir '_sqlite3.pyd'
    if (-not (Test-Path -LiteralPath $targetSqlitePyd)) {
        $sqliteSources = @(

            (Join-Path (Split-Path -Parent $projectDir) "01_AG-MONITOR-Smart-Video-Screening\python_embed\_sqlite3.pyd"),

            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\DLLs\_sqlite3.pyd")
        )
        foreach ($src in $sqliteSources) {
            if ($src -and (Test-Path -LiteralPath $src)) {
                Copy-Item -LiteralPath $src -Destination $targetSqlitePyd -Force
                $srcDll = Join-Path (Split-Path -Parent $src) 'sqlite3.dll'
                if (Test-Path -LiteralPath $srcDll) {
                    Copy-Item -LiteralPath $srcDll -Destination (Join-Path $embedDir 'sqlite3.dll') -Force
                }
                break
            }
        }
    }

    # 配置 get-pip.py
    $getPipPath = Join-Path $embedDir 'get-pip.py'
    $cachedGetPip = Join-Path (Split-Path -Parent $projectDir) "00_Dev-Control-Center\downloads\get-pip.py"
    if (Test-Path -LiteralPath $cachedGetPip) {
        Copy-Item -LiteralPath $cachedGetPip -Destination $getPipPath -Force
    } else {
        $getPipUrl = "https://bootstrap.pypa.io/get-pip.py"
        try {
            Invoke-WebRequest -Uri $getPipUrl -OutFile $getPipPath -UseBasicParsing
        } catch {
            Write-Host "   無法從網路下載 get-pip.py，將嘗試使用已內建套件機制" -ForegroundColor Yellow
        }
    }

    if (Test-Path -LiteralPath $getPipPath) {
        $oldEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $null = & "$embedPython" -B -s "$getPipPath" --no-warn-script-location 2>$null
        } finally {
            $ErrorActionPreference = $oldEap
        }
    }

    # ------------------------------------------------------------------
    # 階段 5：安裝相依套件 (requirements.txt)
    # ------------------------------------------------------------------
    if ($reqFile -and (Test-Path -LiteralPath $reqFile)) {
        Write-Host "[4/4] 正在自動安裝專案相依套件 ($([IO.Path]::GetFileName($reqFile)))..." -ForegroundColor Green
        $oldEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & "$embedPython" -B -s -m pip install --no-warn-script-location -r "$reqFile"
            if ($LASTEXITCODE -ne 0) { throw '專案套件安裝失敗；保留環境，不宣稱就緒。' }
        } finally {
            $ErrorActionPreference = $oldEap
        }
    }

    Write-Host ''
    Write-Host "【自癒成功】專案環境已 100% 佈置完成！" -ForegroundColor Cyan
    Write-Host '=================================================================' -ForegroundColor Cyan
}

if ($NoLaunch) {
    Write-Host "模式為僅建置環境，已順利完成。" -ForegroundColor Green
    return
}

# ----------------------------------------------------------------------
# 階段 6：啟動主程式 (無終端視窗模式，啟動後 CMD 自動退出)
# ----------------------------------------------------------------------
$mainFile = Join-Path $projectDir $entryPoint
if (-not (Test-Path -LiteralPath $mainFile)) {
    throw "找不到專案啟動進入點：$mainFile"
}

$pythonwExe = Join-Path $embedDir 'pythonw.exe'
if (Test-Path -LiteralPath $pythonwExe) {
    Start-Process -FilePath $pythonwExe -ArgumentList @('-B', '-s', $entryPoint) -WorkingDirectory $projectDir
} else {
    & $embedPython -B -s $mainFile
}
