param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$StagedCurrent,
    [Parameter(Mandatory = $true)][string]$ArchivePath,
    [Parameter(Mandatory = $true)][int]$MainPid
)

$ErrorActionPreference = 'Stop'
$install = (Resolve-Path -LiteralPath $InstallRoot).Path
$staged = (Resolve-Path -LiteralPath $StagedCurrent).Path
$archive = (Resolve-Path -LiteralPath $ArchivePath).Path
$current = Join-Path $install 'current'
$dataLogs = Join-Path $install 'data\logs'
New-Item -ItemType Directory -Path $dataLogs -Force | Out-Null
$logPath = Join-Path $dataLogs 'update_debug.log'

function Write-UpdateLog([string]$Message) {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value (
        '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    )
}

function Test-IsChildPath([string]$Parent, [string]$Child) {
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $childFull = [IO.Path]::GetFullPath($Child)
    return $childFull.StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)
}

function Remove-TemporaryArchive() {
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ((Test-Path -LiteralPath $archive) -and (Test-IsChildPath $tempRoot $archive)) {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    }
}

function Start-HiddenPython(
    [string]$PythonPath,
    [string]$WorkingDirectory,
    [string]$ScriptName
) {
    # Windows PowerShell 5.1 的 Start-Process 在同時存在 Path／PATH 時，
    # 可能因不區分大小寫的環境變數字典發生重複鍵例外。
    # UseShellExecute 直接由 Windows 繼承環境，避開該重建流程。
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $PythonPath
    $startInfo.Arguments = '-B "' + $ScriptName.Replace('"', '\"') + '"'
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    return [System.Diagnostics.Process]::Start($startInfo)
}

if (-not (Test-IsChildPath $install $staged)) {
    throw 'staging 目錄不在安裝根目錄內，拒絕更新。'
}
if ((Split-Path -Leaf $staged) -ne 'current' -or
    -not (Test-Path -LiteralPath (Join-Path $staged 'runtime\pythonw.exe')) -or
    -not (Test-Path -LiteralPath (Join-Path $staged 'ui.py'))) {
    throw 'staging 內容不完整，拒絕更新。'
}

$backupRoot = Join-Path $install ('.update_backup_' + [guid]::NewGuid().ToString('N'))
$backupCurrent = Join-Path $backupRoot 'current'
$backupBootstrap = Join-Path $backupRoot 'bootstrap'
$failedRoot = Join-Path $install ('.update_failed_' + [guid]::NewGuid().ToString('N'))
$packageRoot = Split-Path -Parent $staged
$stagingRoot = $packageRoot
$switched = $false
$newProcess = $null

foreach ($bootstrapName in @('啟動程式.bat', 'auto_update.ps1')) {
    if (-not (Test-Path -LiteralPath (Join-Path $packageRoot $bootstrapName))) {
        throw "更新包缺少啟動必要檔案：$bootstrapName"
    }
}

try {
    Write-UpdateLog "等待主程式 PID=$MainPid 結束"
    for ($index = 0; $index -lt 60; $index++) {
        if (-not (Get-Process -Id $MainPid -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 500
    }
    if (Get-Process -Id $MainPid -ErrorAction SilentlyContinue) {
        throw '主程式未在 30 秒內結束，取消更新。'
    }

    $smokePython = Join-Path $staged 'runtime\python.exe'
    $smokeScript = Join-Path $staged '_update_smoke.py'
    $smokeOut = Join-Path $dataLogs 'update_smoke_stdout.log'
    $smokeErr = Join-Path $dataLogs 'update_smoke_stderr.log'
    Set-Content -LiteralPath $smokeScript -Encoding ASCII -Value `
        'import PySide6,selenium,requests,cv2,numpy,ddddocr,psutil'
    $smokeOutput = @(& $smokePython -B $smokeScript 2>&1)
    $smokeExit = $LASTEXITCODE
    Set-Content -LiteralPath $smokeOut -Encoding UTF8 -Value $smokeOutput
    Remove-Item -LiteralPath $smokeScript -Force -ErrorAction SilentlyContinue
    if ($smokeExit -ne 0) {
        $smokeDetails = @(
            (Get-Content -LiteralPath $smokeOut -Raw -ErrorAction SilentlyContinue),
            (Get-Content -LiteralPath $smokeErr -Raw -ErrorAction SilentlyContinue)
        ) -join ' '
        throw "新版 runtime 匯入檢查失敗，exit=$smokeExit：$smokeDetails"
    }
    Remove-Item -LiteralPath $smokeOut, $smokeErr -Force -ErrorAction SilentlyContinue

    New-Item -ItemType Directory -Path $backupRoot | Out-Null
    New-Item -ItemType Directory -Path $backupBootstrap | Out-Null
    $rootFiles = @('啟動程式.bat', '建立桌面捷徑.bat', '發行說明.txt', 'SHA256SUMS.txt', 'auto_update.ps1')
    foreach ($bootstrapName in $rootFiles) {
        $installedBootstrap = Join-Path $install $bootstrapName
        if (Test-Path -LiteralPath $installedBootstrap) {
            Copy-Item -LiteralPath $installedBootstrap -Destination $backupBootstrap -Force -ErrorAction SilentlyContinue
        }
    }
    if (Test-Path -LiteralPath $current) {
        Move-Item -LiteralPath $current -Destination $backupCurrent
    }
    Move-Item -LiteralPath $staged -Destination $current
    $switched = $true
    Write-UpdateLog '程式目錄切換完成，啟動新版健康檢查。'

    $newPythonw = Join-Path $current 'runtime\pythonw.exe'
    $newProcess = Start-HiddenPython $newPythonw $current 'ui.py'
    Start-Sleep -Seconds 8
    if ($newProcess.HasExited) {
        throw "新版啟動後提前結束，exit=$($newProcess.ExitCode)。"
    }

    foreach ($bootstrapName in $rootFiles) {
        $bootstrapSource = Join-Path $packageRoot $bootstrapName
        if (Test-Path -LiteralPath $bootstrapSource) {
            $bootstrapTarget = Join-Path $install $bootstrapName
            $bootstrapTemp = $bootstrapTarget + '.new'
            Copy-Item -LiteralPath $bootstrapSource -Destination $bootstrapTemp -Force
            Move-Item -LiteralPath $bootstrapTemp -Destination $bootstrapTarget -Force
        }
    }
    Write-UpdateLog '新版健康檢查通過。'
    if (Test-Path -LiteralPath $backupRoot) {
        if (-not (Test-IsChildPath $install $backupRoot)) { throw '備份路徑安全檢查失敗。' }
        Remove-Item -LiteralPath $backupRoot -Recurse -Force
    }
    if (Test-Path -LiteralPath $stagingRoot) {
        if (-not (Test-IsChildPath $install $stagingRoot)) { throw 'staging 清理路徑安全檢查失敗。' }
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
    Remove-TemporaryArchive
    Write-UpdateLog '更新完成。'
    exit 0
}
catch {
    Write-UpdateLog ("更新失敗：" + $_.Exception.Message)
    try {
        if ($null -ne $newProcess -and -not $newProcess.HasExited) {
            Stop-Process -Id $newProcess.Id -Force -ErrorAction SilentlyContinue
            Wait-Process -Id $newProcess.Id -Timeout 10 -ErrorAction SilentlyContinue
        }
        if ($switched -and (Test-Path -LiteralPath $current)) {
            Move-Item -LiteralPath $current -Destination $failedRoot
        }
        if (Test-Path -LiteralPath $backupBootstrap) {
            foreach ($bootstrapName in @('啟動程式.bat', 'auto_update.ps1')) {
                $savedBootstrap = Join-Path $backupBootstrap $bootstrapName
                if (Test-Path -LiteralPath $savedBootstrap) {
                    Copy-Item -LiteralPath $savedBootstrap -Destination (Join-Path $install $bootstrapName) -Force
                }
            }
        }
        if (Test-Path -LiteralPath $backupCurrent) {
            Move-Item -LiteralPath $backupCurrent -Destination $current
            $oldPythonw = Join-Path $current 'runtime\pythonw.exe'
            if (Test-Path -LiteralPath $oldPythonw) {
                [void](Start-HiddenPython $oldPythonw $current 'ui.py')
            }
            Write-UpdateLog '已還原並重新啟動舊版。'
        }
        if (Test-Path -LiteralPath $failedRoot) {
            if (Test-IsChildPath $install $failedRoot) {
                Remove-Item -LiteralPath $failedRoot -Recurse -Force
            }
        }
        if (Test-Path -LiteralPath $stagingRoot) {
            if (Test-IsChildPath $install $stagingRoot) {
                Remove-Item -LiteralPath $stagingRoot -Recurse -Force
            }
        }
        if (Test-Path -LiteralPath $backupRoot) {
            if (Test-IsChildPath $install $backupRoot) {
                Remove-Item -LiteralPath $backupRoot -Recurse -Force
            }
        }
        Remove-TemporaryArchive
    }
    catch {
        Write-UpdateLog ("還原失敗：" + $_.Exception.Message)
    }
    exit 1
}
