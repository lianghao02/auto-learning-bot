param(
    [Parameter(Mandatory = $true)][string]$ReleaseDirectory,
    [switch]$UsePackagedUpdater
)

$ErrorActionPreference = 'Stop'
$release = (Resolve-Path -LiteralPath $ReleaseDirectory).Path
$runtime = Join-Path $release 'current\runtime'
$projectRoot = Split-Path -Parent $PSScriptRoot
$updater = if ($UsePackagedUpdater) {
    Join-Path $release 'auto_update.ps1'
} else {
    Join-Path $projectRoot 'scripts\auto_update.ps1'
}
$powershellEngine = if ($UsePackagedUpdater) { 'powershell' } else { 'pwsh' }
$launcher = (Get-ChildItem -LiteralPath $release -Filter '*.bat' -File | Select-Object -First 1).FullName
$launcherName = Split-Path -Leaf $launcher
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())

function Test-IsChildPath([string]$Parent, [string]$Child) {
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $childFull = [IO.Path]::GetFullPath($Child)
    return $childFull.StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)
}

function New-SimulationLayout([string]$Mode) {
    $root = Join-Path $tempBase ('aep_update_test_' + [guid]::NewGuid().ToString('N'))
    $install = Join-Path $root 'install'
    $stage = Join-Path $install '.u_test'
    $oldCurrent = Join-Path $install 'current'
    $newCurrent = Join-Path $stage 'current'
    New-Item -ItemType Directory -Path $oldCurrent, $newCurrent, (Join-Path $install 'data') -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $oldCurrent 'runtime') -Target $runtime | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $newCurrent 'runtime') -Target $runtime | Out-Null
    Copy-Item -LiteralPath $updater -Destination (Join-Path $install 'auto_update.ps1')
    Copy-Item -LiteralPath $launcher -Destination (Join-Path $install $launcherName)
    Copy-Item -LiteralPath $updater -Destination (Join-Path $stage 'auto_update.ps1')
    Copy-Item -LiteralPath $launcher -Destination (Join-Path $stage $launcherName)
    Set-Content -LiteralPath (Join-Path $oldCurrent 'ui.py') -Encoding UTF8 -Value @'
import os
import time
from pathlib import Path
Path(__file__).resolve().parents[1].joinpath("data", "old_pid.txt").write_text(str(os.getpid()))
time.sleep(30)
'@
    Set-Content -LiteralPath (Join-Path $oldCurrent 'marker.txt') -Encoding ASCII -Value 'old'

    if ($Mode -eq 'success') {
        Set-Content -LiteralPath (Join-Path $newCurrent 'ui.py') -Encoding UTF8 -Value @'
import os
import time
from pathlib import Path
Path(__file__).resolve().parents[1].joinpath("data", "new_pid.txt").write_text(str(os.getpid()))
time.sleep(30)
'@
    }
    else {
        Set-Content -LiteralPath (Join-Path $newCurrent 'ui.py') -Encoding UTF8 -Value 'raise SystemExit(23)'
    }
    Set-Content -LiteralPath (Join-Path $newCurrent 'marker.txt') -Encoding ASCII -Value 'new'
    $archive = Join-Path $root 'update.zip'
    Set-Content -LiteralPath $archive -Encoding ASCII -Value 'simulation'
    return @{ Root = $root; Install = $install; Stage = $stage; Archive = $archive }
}

function Stop-SimulationProcess([string]$PidFile) {
    if (Test-Path -LiteralPath $PidFile) {
        $processId = [int](Get-Content -LiteralPath $PidFile -Raw)
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
    }
}

function Invoke-Simulation([string]$Mode, [int]$ExpectedExit, [string]$ExpectedMarker) {
    $layout = New-SimulationLayout $Mode
    try {
        $process = Start-Process -FilePath $powershellEngine -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            (Join-Path $layout.Install 'auto_update.ps1'),
            '-InstallRoot', $layout.Install,
            '-StagedCurrent', (Join-Path $layout.Stage 'current'),
            '-ArchivePath', $layout.Archive,
            '-MainPid', '999999'
        ) -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne $ExpectedExit) {
            $debugLog = Join-Path $layout.Install 'data\logs\update_debug.log'
            $details = if (Test-Path -LiteralPath $debugLog) {
                Get-Content -LiteralPath $debugLog -Raw
            } else {
                'no update_debug.log'
            }
            throw "$Mode updater exit=$($process.ExitCode), expected $ExpectedExit`n$details"
        }
        $marker = (Get-Content -LiteralPath (Join-Path $layout.Install 'current\marker.txt') -Raw).Trim()
        if ($marker -ne $ExpectedMarker) {
            throw "$Mode marker=$marker, expected $ExpectedMarker"
        }
        if (Test-Path -LiteralPath $layout.Stage) { throw "$Mode staging not cleaned" }
        if (Test-Path -LiteralPath $layout.Archive) { throw "$Mode archive not cleaned" }
        Stop-SimulationProcess (Join-Path $layout.Install 'data\new_pid.txt')
        Stop-SimulationProcess (Join-Path $layout.Install 'data\old_pid.txt')
        Write-Output "AUTO_UPDATE_${Mode}_OK"
    }
    finally {
        Stop-SimulationProcess (Join-Path $layout.Install 'data\new_pid.txt')
        Stop-SimulationProcess (Join-Path $layout.Install 'data\old_pid.txt')
        if ((Test-Path -LiteralPath $layout.Root) -and (Test-IsChildPath $tempBase $layout.Root)) {
            Remove-Item -LiteralPath $layout.Root -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

Invoke-Simulation -Mode 'success' -ExpectedExit 0 -ExpectedMarker 'new'
Invoke-Simulation -Mode 'rollback' -ExpectedExit 1 -ExpectedMarker 'old'
