[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ReportPath,
    [string]$SettingsPath = (Join-Path $PSScriptRoot '..\assets\settings.json'),
    [string]$PythonPath,
    [string]$AsOf,
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
if ($Execute -and $AsOf) { throw 'AsOf is preview-only; execution always uses the real Beijing time.' }
if (-not $PythonPath) {
    $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $PythonPath = if (Test-Path -LiteralPath $bundled -PathType Leaf) { $bundled } else { (Get-Command python -ErrorAction Stop).Source }
}
$planner = Join-Path $PSScriptRoot 'backup_cleanup.py'
$ReportPath = [IO.Path]::GetFullPath($ReportPath)
$SettingsPath = [IO.Path]::GetFullPath($SettingsPath)
$journalPath = $ReportPath + '.journal.jsonl'
$resultPath = $ReportPath + '.result.json'
foreach ($p in @($ReportPath,$journalPath,$resultPath)) { if (Test-Path -LiteralPath $p) { throw "Use new audit paths: $p" } }

function Assert-PlainPath {
    param([string]$Path)
    $itemPath = [IO.Path]::GetFullPath($Path)
    while ($itemPath) {
        if (Test-Path -LiteralPath $itemPath) {
            $item = Get-Item -LiteralPath $itemPath -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse path rejected: $itemPath" }
        }
        $parent = [IO.Directory]::GetParent($itemPath)
        $itemPath = if ($parent) { $parent.FullName } else { $null }
    }
}

function Assert-BackupPath {
    param($Entry,[string]$Batch,[string]$Root)
    $batchPath = [IO.Path]::GetFullPath($Batch)
    if ([IO.Path]::GetDirectoryName($batchPath) -ne $Root -or [IO.Path]::GetFileName($batchPath) -notmatch '^delivery-batch-\d{8}-\d{6}$') { throw 'Invalid batch path' }
    $backupRoot = Join-Path $batchPath 'backups'
    $path = [IO.Path]::GetFullPath([string]$Entry.path)
    if ($Entry.backup_root -ne $backupRoot -or -not $path.StartsWith($backupRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Backup path escaped batch' }
    if ($path.Substring([IO.Path]::GetPathRoot($path).Length).Contains(':')) { throw 'Alternate data stream rejected' }
    if ([IO.Path]::GetExtension($path).ToLowerInvariant() -notin @('.xlsx','.xls','.xlsm','.jpg','.jpeg','.png','.webp','.tif','.tiff','.bmp','.heic')) { throw 'Extension not authorized' }
    Assert-PlainPath $path
    return $path
}

function Write-Journal {
    param($Value)
    $line = ($Value | ConvertTo-Json -Compress -Depth 15) + "`n"
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($line)
    $stream = [IO.File]::Open($journalPath,[IO.FileMode]::Append,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}

function Assert-Evidence {
    param($Plan)
    if ((Get-FileHash -LiteralPath $SettingsPath -Algorithm SHA256).Hash -ne $Plan.settings_sha256) { throw 'Settings changed' }
    foreach ($property in $Plan.evidence_files.PSObject.Properties) {
        if ((Get-FileHash -LiteralPath $property.Name -Algorithm SHA256).Hash -ne $property.Value) { throw "Evidence changed: $($property.Name)" }
    }
}

Assert-PlainPath $ReportPath
$arguments = @('-B',$planner,'--settings',$SettingsPath,'--report',$ReportPath)
if ($AsOf) { $arguments += @('--as-of',$AsOf) }
& $PythonPath @arguments
if ($LASTEXITCODE -ne 0) { throw 'Backup preflight failed; nothing deleted' }
if (-not $Execute) { return }
$plan = Get-Content -LiteralPath $ReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($plan.simulation) { throw 'Simulation cannot execute' }
$root = [IO.Path]::GetFullPath([string]$plan.backup_batch_root)
Assert-PlainPath $root
$lockPath = Join-Path $root '.backup-cleanup.lock'
Assert-PlainPath $lockPath
$lock = [IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$outcomes = [Collections.Generic.List[object]]::new()
try {
    $journal = [IO.File]::Open($journalPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    $journal.Dispose()
    Write-Journal @{event='run_start';plan=$ReportPath;time=[DateTimeOffset]::Now.ToString('o')}
    $index = 0
    foreach ($batch in $plan.batches) {
        if ($batch.status -ne 'ready') { continue }
        $index++
        try {
            $freshPath = $ReportPath + '.recheck-' + $index + '.json'
            & $PythonPath -B $planner --settings $SettingsPath --report $freshPath --batch $batch.batch
            if ($LASTEXITCODE -ne 0) { throw 'Batch recheck failed' }
            $fresh = Get-Content -LiteralPath $freshPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($fresh.backup_batch_root -ne $root -or $fresh.settings_sha256 -ne $plan.settings_sha256 -or $fresh.batches[0].status -ne 'ready') { throw 'Batch changed since preflight' }
            foreach ($entry in $batch.files | Where-Object { $_.status -eq 'eligible' }) {
                $match = @($fresh.batches[0].files | Where-Object { $_.path -eq $entry.path -and $_.sha256 -eq $entry.sha256 -and $_.status -eq 'eligible' })
                if ($match.Count -ne 1) { throw 'Candidate changed since preflight' }
                Assert-Evidence $fresh
                $path = Assert-BackupPath $entry $batch.batch $root
                $stream = [IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::Read -bor [IO.FileShare]::Delete))
                try {
                    $algorithm = [Security.Cryptography.SHA256]::Create()
                    try { $hash = ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','') } finally { $algorithm.Dispose() }
                    if ($hash -ne $entry.sha256 -or $stream.Length -ne $entry.size) { throw 'Backup changed before deletion' }
                    Assert-BackupPath $entry $batch.batch $root | Out-Null
                    Write-Journal @{event='delete_started';path=$path;size=$entry.size;sha256=$entry.sha256;kind=$entry.kind}
                    Remove-Item -LiteralPath $path -ErrorAction Stop
                } finally { $stream.Dispose() }
                if (Test-Path -LiteralPath $path) { throw 'File still present after deletion' }
                $outcome = @{event='deleted';path=$path;size=$entry.size;sha256=$entry.sha256;kind=$entry.kind}
                Write-Journal $outcome
                $outcomes.Add($outcome)
            }
        } catch {
            $failure = @{event='batch_retained_after_failure';batch=$batch.batch;reason=$_.Exception.Message}
            Write-Journal $failure
            $outcomes.Add($failure)
        }
    }
    $summary = @{
        deleted_ledgers=@($outcomes | Where-Object { $_.event -eq 'deleted' -and $_.kind -eq 'ledger' }).Count
        deleted_photos=@($outcomes | Where-Object { $_.event -eq 'deleted' -and $_.kind -eq 'photo' }).Count
        released_bytes=($outcomes | Where-Object { $_.event -eq 'deleted' } | Measure-Object -Property size -Sum).Sum
        failed_batches=@($outcomes | Where-Object { $_.event -eq 'batch_retained_after_failure' }).Count
        blocked_batches=$plan.summary.blocked_batches
    }
    Write-Journal @{event='run_complete';summary=$summary}
    [IO.File]::WriteAllText($resultPath,(@{summary=$summary;outcomes=@($outcomes.ToArray())} | ConvertTo-Json -Depth 20),[Text.UTF8Encoding]::new($false))
    $summary | ConvertTo-Json -Compress
    if ($summary.failed_batches -or $summary.blocked_batches) { exit 2 }
} finally { $lock.Dispose() }
