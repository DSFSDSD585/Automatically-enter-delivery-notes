[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'archive-delivery-notes.ps1'
$root = Join-Path $env:TEMP ('process-delivery-notes-' + [guid]::NewGuid().ToString('N'))

function Write-Utf8NoBom {
    param([string]$Path, [string]$Content)
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

function Invoke-ArchiveChild {
    param([string[]]$Arguments)
    $allArguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $scriptPath) + $Arguments
    $currentPowerShell = (Get-Process -Id $PID).Path
    $process = Start-Process -FilePath $currentPowerShell -ArgumentList $allArguments -Wait -PassThru -NoNewWindow
    return $process.ExitCode
}

function Get-TestSha256 {
    param([string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-', '')
    } finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Assertion failed: $Message" }
}

try {
    $pending = Join-Path $root 'pending'
    $primary = Join-Path $root 'primary'
    $settlement = Join-Path $root 'settlement'
    $carrierDir = Join-Path $primary 'ProjectA\顾氏'
    $settlementYear = Join-Path $settlement 'ProjectA\2026'
    New-Item -ItemType Directory -Path $pending, $carrierDir, $settlementYear -Force | Out-Null

    $settingsPath = Join-Path $root 'settings.json'
    $rulesPath = Join-Path $root 'carrier-rules.json'
    $mapPath = Join-Path $root 'project-map.csv'
    Write-Utf8NoBom $settingsPath (@{
        pending_root = $pending
        ledger_root = (Join-Path $root 'ledgers')
        primary_archive_root = $primary
        settlement_archive_root = $settlement
        settlement_marker = '已录'
        default_year = 2026
        allowed_carriers = @('顾氏', '伟豪', '享运', '顺赢')
    } | ConvertTo-Json -Depth 4)
    Write-Utf8NoBom $rulesPath '{"rules":[{"pattern":"-GS-","carrier":"顾氏"}],"manual_only":[]}'
    Write-Utf8NoBom $mapPath "alias,standard_project,ledger_sheet,archive_project,archive_carrier_folder,settlement_project,status,notes`nProjectA,ProjectA,SheetA,ProjectA,,ProjectA,active,test`n"

    $manifestHeader = 'source_file,delivery_no,carrier,project_alias,arrival_date,ledger_file,ledger_sheet,ledger_rows,recognition_status,readback_status,save_status,ledger_saved,save_method,saved_mtime,close_status,close_method,close_error,primary_target,settlement_target,archive_status,source_sha256,primary_sha256,settlement_sha256,error_reason'
    $savedMtime = '2026-08-20T10:30:00+08:00'

    $source1 = Join-Path $pending 'one.jpg'
    [System.IO.File]::WriteAllBytes($source1, [byte[]](1,2,3,4,5))
    $manifest1 = Join-Path $root 'batch1.csv'
    $report1 = Join-Path $root 'batch1-result.csv'
    Write-Utf8NoBom $manifest1 ($manifestHeader + "`none.jpg,ABC-GS-00001,顾氏,ProjectA,2026-08-20,运输台账-顾氏.xlsx,SheetA,10:10,verified,verified,saved,true,ui,$savedMtime,closed,ui,,,,,,,,`n")

    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $manifest1, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $report1)
    Assert-True ($exitCode -eq 0) 'dry run should succeed'
    Assert-True (Test-Path -LiteralPath $source1) 'dry run must retain source'
    Assert-True ((Import-Csv $report1).archive_status -eq 'Ready') 'dry run should report Ready'

    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $manifest1, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $report1, '-Execute')
    Assert-True ($exitCode -eq 0) 'execute should succeed'
    $result1 = Import-Csv $report1
    Assert-True ($result1.archive_status -eq 'Completed') 'execute should report Completed'
    Assert-True ($result1.save_method -eq 'ui') 'report should preserve save method'
    Assert-True ($result1.saved_mtime -eq $savedMtime) 'report should preserve saved mtime'
    Assert-True ($result1.close_status -eq 'closed') 'report should preserve close status'
    Assert-True ($result1.close_method -eq 'ui') 'report should preserve close method'
    Assert-True (-not (Test-Path -LiteralPath $source1)) 'source should be deleted after both hashes pass'
    Assert-True ((Get-TestSha256 $result1.primary_target) -eq (Get-TestSha256 $result1.settlement_target)) 'paired archive hashes should match'

    $source2 = Join-Path $pending 'two.jpg'
    [System.IO.File]::WriteAllBytes($source2, [byte[]](6,7,8))
    $manifest2 = Join-Path $root 'batch2.csv'
    $report2 = Join-Path $root 'batch2-result.csv'
    Write-Utf8NoBom $manifest2 ($manifestHeader + "`ntwo.jpg,ABC-GS-00002,顾氏,ProjectA,2026-08-20,运输台账-顾氏.xlsx,SheetA,11:11,verified,pending,saved,true,native,$savedMtime,failed,ui,window remained open,,,,,,,`n")
    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $manifest2, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $report2, '-Execute')
    Assert-True ($exitCode -eq 2) 'unverified readback should be blocked'
    Assert-True (Test-Path -LiteralPath $source2) 'blocked item must retain source'
    Assert-True ((Import-Csv $report2).error_reason -match 'Readback status') 'blocked report should explain readback failure'

    $source3 = Join-Path $pending 'three.jpg'
    [System.IO.File]::WriteAllBytes($source3, [byte[]](9,10,11))
    $primaryConflict = Join-Path $carrierDir 'ABC-GS-00003.jpg'
    $settlementConflict = Join-Path $settlementYear '0820已录ABC-GS-00003.jpg'
    Copy-Item -LiteralPath $source3 -Destination $primaryConflict
    [System.IO.File]::WriteAllBytes($settlementConflict, [byte[]](99,98,97))
    $manifest3 = Join-Path $root 'batch3.csv'
    $report3 = Join-Path $root 'batch3-result.csv'
    Write-Utf8NoBom $manifest3 ($manifestHeader + "`nthree.jpg,ABC-GS-00003,顾氏,ProjectA,2026-08-20,运输台账-顾氏.xlsx,SheetA,12:12,verified,verified,saved,true,native,$savedMtime,not_attempted,none,desktop locked,,,,,,,`n")
    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $manifest3, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $report3)
    Assert-True ($exitCode -eq 2) 'different-content filename conflict should be blocked'
    $result3 = Import-Csv $report3
    Assert-True ($result3.error_reason -match 'Review physical-note identity') 'conflict must distinguish rephotographs from different physical notes'
    Assert-True ([string]::IsNullOrWhiteSpace($result3.primary_target)) 'conflict must not auto-generate a file-only suffix'
    Assert-True (Test-Path -LiteralPath $source3) 'conflicted source must remain pending'

    $source4 = Join-Path $pending 'four.jpg'
    [System.IO.File]::WriteAllBytes($source4, [byte[]](12,13,14))
    $manifest4 = Join-Path $root 'batch4.csv'
    $report4 = Join-Path $root 'batch4-result.csv'
    Write-Utf8NoBom $manifest4 ($manifestHeader + "`nfour.jpg,ABC-GS-00004,顾氏,ProjectA,2026-08-20,运输台账-顾氏.xlsx,SheetA,13:13,verified,verified,saved,true,native,$savedMtime,failed,ui,window remained open,,,,,,,`n")
    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $manifest4, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $report4, '-Execute')
    Assert-True ($exitCode -eq 0) 'verified save should archive even when close failed'
    $result4 = Import-Csv $report4
    Assert-True ($result4.archive_status -eq 'Completed') 'close failure must not block verified archive'
    Assert-True ($result4.close_status -eq 'failed') 'close failure status should be preserved'
    Assert-True ($result4.close_error -eq 'window remained open') 'close failure reason should be preserved'
    Assert-True (-not (Test-Path -LiteralPath $source4)) 'verified save with close failure should still clean pending source after hashes pass'

    $source5 = Join-Path $pending 'five.jpg'
    [System.IO.File]::WriteAllBytes($source5, [byte[]](15,16,17))
    $manifest5 = Join-Path $root 'batch5.csv'
    $report5 = Join-Path $root 'batch5-result.csv'
    Write-Utf8NoBom $manifest5 ($manifestHeader + "`nfive.jpg,ABC-GS-00005,顾氏,ProjectA,2026-08-20,运输台账-顾氏.xlsx,SheetA,14:14,verified,verified,saved,true,native,$savedMtime,closed,none,,,,,,,,`n")
    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $manifest5, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $report5, '-Execute')
    Assert-True ($exitCode -eq 2) 'inconsistent close audit fields should be blocked'
    Assert-True (Test-Path -LiteralPath $source5) 'invalid close audit fields must retain pending source'
    Assert-True ((Import-Csv $report5).error_reason -match 'requires native or ui close method') 'invalid close audit report should explain the inconsistent fields'

    $replay = Join-Path $root 'replay.csv'
    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $report1, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $replay, '-Execute')
    Assert-True ($exitCode -eq 0) 'completed result must replay with absent source'
    Assert-True ((Import-Csv $replay).cleanup_status -eq 'already_absent') 'replay must not claim deletion again'
    Assert-True ((Import-Csv $replay).archive_status -eq 'AlreadyComplete') 'replay must not count as newly completed'

    $blankPlate = Import-Csv $manifest1
    $blankPlate.source_file = 'six.jpg'
    $blankPlate.delivery_no = 'ABC-GS-00006'
    $blankPlate | Add-Member -NotePropertyName missing_fields -NotePropertyValue 'vehicle_plate'
    [System.IO.File]::WriteAllBytes((Join-Path $pending 'six.jpg'), [byte[]](21,22,23))
    $blankManifest = Join-Path $root 'blank.csv'
    $blankPlate | Export-Csv -LiteralPath $blankManifest -NoTypeInformation -Encoding UTF8
    $blankReport = Join-Path $root 'blank-result.csv'
    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $blankManifest, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $blankReport, '-Execute')
    Assert-True ($exitCode -eq 0) 'blank plate alone must not block archive'
    $blankPlate.missing_fields = 'arrival_date'
    $blankPlate.source_file = 'seven.jpg'
    $blankPlate.delivery_no = 'ABC-GS-00007'
    [System.IO.File]::WriteAllBytes((Join-Path $pending 'seven.jpg'), [byte[]](31,32,33))
    $blankPlate | Export-Csv -LiteralPath $blankManifest -NoTypeInformation -Encoding UTF8
    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $blankManifest, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $blankReport, '-Execute')
    Assert-True ($exitCode -eq 2) 'blank date must remain blocked'
    Assert-True (Test-Path -LiteralPath (Join-Path $pending 'seven.jpg')) 'missing required field must retain source'
    $png = Import-Csv $manifest1
    $png.source_file = 'eight.png'
    $png.delivery_no = 'ABC-GS-00008'
    [System.IO.File]::WriteAllBytes((Join-Path $pending 'eight.png'), [byte[]](137,80,78,71,13,10,26,10,1,2,3))
    $pngManifest = Join-Path $root 'png.csv'
    $pngReport = Join-Path $root 'png-result.csv'
    $png | Export-Csv -LiteralPath $pngManifest -NoTypeInformation -Encoding UTF8
    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $pngManifest, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $pngReport, '-Execute')
    Assert-True ($exitCode -eq 0) 'native PNG should archive'
    $pngResult = Import-Csv $pngReport
    Assert-True ($pngResult.primary_target.EndsWith('.png') -and $pngResult.settlement_target.EndsWith('.png')) 'PNG format must be preserved in both paths'
    Assert-True ($pngResult.primary_sha256 -eq $pngResult.source_sha256 -and $pngResult.settlement_sha256 -eq $pngResult.source_sha256) 'PNG hash equality'
    $png.source_file = 'nine.png'
    $png.delivery_no = 'ABC-GS-00009'
    [System.IO.File]::WriteAllBytes((Join-Path $pending 'nine.png'), [byte[]](1,2,3))
    $png | Export-Csv -LiteralPath $pngManifest -NoTypeInformation -Encoding UTF8
    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $pngManifest, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $pngReport, '-Execute')
    Assert-True ($exitCode -eq 2) 'false PNG extension must block'
    Assert-True (Test-Path -LiteralPath (Join-Path $pending 'nine.png')) 'invalid PNG must be retained'
    $png.source_file = 'ten.png'
    $png.delivery_no = 'ABC-GS-00001'
    [System.IO.File]::WriteAllBytes((Join-Path $pending 'ten.png'), [byte[]](137,80,78,71,13,10,26,10,1,2,3))
    $png | Export-Csv -LiteralPath $pngManifest -NoTypeInformation -Encoding UTF8
    $exitCode = Invoke-ArchiveChild @('-ManifestPath', $pngManifest, '-SettingsPath', $settingsPath, '-CarrierRulesPath', $rulesPath, '-ProjectMapPath', $mapPath, '-ReportPath', $pngReport, '-Execute')
    Assert-True ($exitCode -eq 2) 'same number across formats must require review'
    Assert-True (Test-Path -LiteralPath (Join-Path $pending 'ten.png')) 'cross-format conflict source retained'
    Write-Host 'All archive workflow tests passed, including native PNG, invalid PNG and cross-format collision.'
} finally {
    if (Test-Path -LiteralPath $root) {
        $resolvedRoot = [IO.Path]::GetFullPath($root)
        $tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
        if (-not $resolvedRoot.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $resolvedRoot) -notlike 'process-delivery-notes-*') { throw 'Unsafe test cleanup path' }
        Remove-Item -LiteralPath $root -Recurse -Force
    }
}
