[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,

    [switch]$Execute,

    [string]$SettingsPath,
    [string]$CarrierRulesPath,
    [string]$ProjectMapPath,
    [string]$ReportPath
)

$ErrorActionPreference = 'Stop'
if (-not $SettingsPath) { $SettingsPath = Join-Path $PSScriptRoot '..\assets\settings.json' }
if (-not $CarrierRulesPath) { $CarrierRulesPath = Join-Path $PSScriptRoot '..\references\carrier-rules.json' }
if (-not $ProjectMapPath) { $ProjectMapPath = Join-Path $PSScriptRoot '..\references\project-map.csv' }

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Configuration file not found: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-FullPath {
    param([string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-PathInsideRoot {
    param([string]$Path, [string]$Root)
    $fullPath = (Get-FullPath $Path).TrimEnd('\')
    $fullRoot = (Get-FullPath $Root).TrimEnd('\')
    return $fullPath.Equals($fullRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $fullPath.StartsWith($fullRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-Sha256 {
    param([string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $algorithm.ComputeHash($stream)
        return ([System.BitConverter]::ToString($bytes)).Replace('-', '')
    } finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

function Resolve-PairedTargets {
    param(
        [string]$PrimaryBase,
        [string]$SettlementBase,
        [string]$SourceHash
    )

    $primaryExists = Test-Path -LiteralPath $PrimaryBase -PathType Leaf
    $settlementExists = Test-Path -LiteralPath $SettlementBase -PathType Leaf
    $primaryMatches = $primaryExists -and ((Get-Sha256 $PrimaryBase) -eq $SourceHash)
    $settlementMatches = $settlementExists -and ((Get-Sha256 $SettlementBase) -eq $SourceHash)

    if (($primaryExists -and -not $primaryMatches) -or ($settlementExists -and -not $settlementMatches)) {
        throw 'Archive filename is occupied by different content. Review physical-note identity: a new photo of the same note requires verified version backup/replacement; only a different physical note requires a new -1/-2 business number. Do not infer identity from hashes or timestamps.'
    }

    return [pscustomobject]@{
        Primary = $PrimaryBase
        Settlement = $SettlementBase
        PrimaryExists = $primaryExists
        SettlementExists = $settlementExists
    }
}

function Resolve-Carrier {
    param([string]$DeliveryNo, [string]$ManifestCarrier, $Rules, [string[]]$AllowedCarriers)

    $matches = @($Rules.rules | Where-Object { $DeliveryNo -match $_.pattern } | Select-Object -ExpandProperty carrier -Unique)
    if ($matches.Count -gt 1) {
        throw "Delivery number matches multiple carriers: $($matches -join ', ')"
    }
    $inferred = if ($matches.Count -eq 1) { [string]$matches[0] } else { '' }
    $carrier = if ([string]::IsNullOrWhiteSpace($ManifestCarrier)) { $inferred } else { $ManifestCarrier.Trim() }

    if ([string]::IsNullOrWhiteSpace($carrier)) {
        throw 'Carrier rule did not resolve and manifest carrier is blank.'
    }
    if ($carrier -notin $AllowedCarriers) {
        throw "Carrier is not allowed: $carrier"
    }
    if ($inferred -and $inferred -ne $carrier) {
        throw "Manifest carrier conflicts with inferred carrier."
    }
    return $carrier
}

function Resolve-Project {
    param([string]$Alias, $ProjectMap, [string]$PrimaryRoot, [string]$SettlementRoot)

    $allMatches = @($ProjectMap | Where-Object { $_.alias -eq $Alias })
    if ($allMatches.Count -gt 1) {
        throw "Duplicate project alias in project map: $Alias"
    }
    if ($allMatches.Count -eq 1) {
        $match = $allMatches[0]
        if ($match.status -ne 'active') {
            throw "Project is not active: $Alias ($($match.notes))"
        }
        return $match
    }

    $primaryExact = Join-Path $PrimaryRoot $Alias
    $settlementExact = Join-Path $SettlementRoot $Alias
    if ((Test-Path -LiteralPath $primaryExact -PathType Container) -and
        (Test-Path -LiteralPath $settlementExact -PathType Container)) {
        return [pscustomobject]@{
            alias = $Alias
            standard_project = $Alias
            ledger_sheet = $Alias
            archive_project = $Alias
            archive_carrier_folder = ''
            settlement_project = $Alias
            status = 'active'
            notes = 'exact directory match'
        }
    }

    throw "Project mapping not found: $Alias"
}

function Test-LedgerSaved {
    param([string]$Value)
    return $Value -match '^(?i:true|1|yes)$'
}

function Test-VerifiedStatus {
    param([string]$Value)
    return ([string]$Value).Trim() -match '^(?i:verified)$'
}

function Test-SavedStatus {
    param([string]$Value)
    return ([string]$Value).Trim() -match '^(?i:saved)$'
}

function Test-CleanText {
    param([string]$Value)
    return -not ([string]$Value).Contains([char]0xFFFD)
}

function Get-ManifestValue {
    param($Row, [string]$Name)
    $property = $Row.PSObject.Properties[$Name]
    if ($null -eq $property) { return '' }
    return ([string]$property.Value).Trim()
}

$settings = Read-JsonFile $SettingsPath
$carrierRules = Read-JsonFile $CarrierRulesPath
$projectMap = Import-Csv -LiteralPath $ProjectMapPath -Encoding UTF8

$manifestFullPath = Get-FullPath $ManifestPath
if (-not (Test-Path -LiteralPath $manifestFullPath -PathType Leaf)) {
    throw "Batch manifest not found: $manifestFullPath"
}
$batch = @(Import-Csv -LiteralPath $manifestFullPath -Encoding UTF8)
if ($batch.Count -eq 0) {
    throw 'Batch manifest has no data rows.'
}
if ($Execute -and [string]::IsNullOrWhiteSpace($ReportPath)) {
    throw 'ReportPath is required with -Execute so archive state and hashes are persisted.'
}
if ($ReportPath) {
    $reportFullPath = Get-FullPath $ReportPath
    if ($reportFullPath -eq $manifestFullPath) { throw 'Report must not overwrite its input manifest.' }
    foreach ($rootKey in @('pending_root', 'ledger_root', 'primary_archive_root', 'settlement_archive_root')) {
        if (Test-PathInsideRoot $reportFullPath ([string]$settings.$rootKey)) { throw 'Report and journal must be outside business roots.' }
    }
    $reportDirectory = Split-Path -Parent $reportFullPath
    if (-not (Test-Path -LiteralPath $reportDirectory -PathType Container)) { throw 'Report directory does not exist.' }
    if ($Execute) {
        # Establish writable durable audit output BEFORE any archive/cleanup mutation.
        $journalPath = $reportFullPath + '.journal.jsonl'
        Add-Content -LiteralPath $journalPath -Encoding UTF8 -Value ('{"event":"batch_start","time":"' + [datetime]::UtcNow.ToString('o') + '"}')
    }
}

$duplicateSources = @($batch | Group-Object { Get-ManifestValue $_ 'source_file' } | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Name) -and $_.Count -gt 1 } | Select-Object -ExpandProperty Name)
$duplicateNumbers = @($batch | Group-Object { Get-ManifestValue $_ 'delivery_no' } | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Name) -and $_.Count -gt 1 } | Select-Object -ExpandProperty Name)

$pendingRoot = Get-FullPath ([string]$settings.pending_root)
$primaryRoot = Get-FullPath ([string]$settings.primary_archive_root)
$settlementRoot = Get-FullPath ([string]$settings.settlement_archive_root)
$allowedCarriers = @($settings.allowed_carriers | ForEach-Object { [string]$_ })
# Archive year is derived from each verified arrival date, never a default year.
$settlementMarker = [string]$settings.settlement_marker

$preflight = foreach ($row in $batch) {
    $deliveryNo = Get-ManifestValue $row 'delivery_no'
    $alias = Get-ManifestValue $row 'project_alias'
    $sourceName = Get-ManifestValue $row 'source_file'
    $ledgerFile = Get-ManifestValue $row 'ledger_file'
    $ledgerSheet = Get-ManifestValue $row 'ledger_sheet'
    $ledgerRows = Get-ManifestValue $row 'ledger_rows'
    $recognitionStatus = Get-ManifestValue $row 'recognition_status'
    $readbackStatus = Get-ManifestValue $row 'readback_status'
    $saveStatus = Get-ManifestValue $row 'save_status'
    $saveMethod = Get-ManifestValue $row 'save_method'
    $savedMtime = Get-ManifestValue $row 'saved_mtime'
    $closeStatus = Get-ManifestValue $row 'close_status'
    $closeMethod = Get-ManifestValue $row 'close_method'
    $closeError = Get-ManifestValue $row 'close_error'
    $errors = [System.Collections.Generic.List[string]]::new()

    if ([string]::IsNullOrWhiteSpace($deliveryNo)) { $errors.Add('Delivery number is blank') }
    if ($deliveryNo -match '[<>:"/\\|?*]') { $errors.Add('Delivery number contains invalid filename characters') }
    if ([string]::IsNullOrWhiteSpace($alias)) { $errors.Add('Project alias is blank') }
    if ($sourceName -in $duplicateSources) { $errors.Add('Source file is duplicated in the batch') }
    if ($deliveryNo -in $duplicateNumbers) { $errors.Add('Delivery number is duplicated in the batch; assign the final unique suffix first') }
    if ([string]::IsNullOrWhiteSpace($ledgerFile)) { $errors.Add('Ledger file is blank') }
    if ([string]::IsNullOrWhiteSpace($ledgerSheet)) { $errors.Add('Ledger sheet is blank') }
    if ([string]::IsNullOrWhiteSpace($ledgerRows)) { $errors.Add('Ledger rows are blank') }
    if (-not (Test-VerifiedStatus $recognitionStatus)) { $errors.Add('Recognition status is not verified') }
    if (-not (Test-VerifiedStatus $readbackStatus)) { $errors.Add('Readback status is not verified') }
    if (-not (Test-SavedStatus $saveStatus)) { $errors.Add('Save status is not saved') }
    if (-not (Test-LedgerSaved (Get-ManifestValue $row 'ledger_saved'))) { $errors.Add('Ledger is not marked saved') }
    if ($saveMethod -notin @('native', 'ui', 'existing', 'offline')) { $errors.Add('Save method must be native, ui, existing, or offline') }
    $ledgerHash = Get-ManifestValue $row 'ledger_sha256'
    if ($ledgerHash -notmatch '^[A-Fa-f0-9]{64}$') { $errors.Add('Every archive requires a fresh verified disk ledger SHA256') }
    if ($ledgerFile -and -not [IO.Path]::IsPathRooted($ledgerFile)) { $ledgerFile = Join-Path ([string]$settings.ledger_root) $ledgerFile }
    if ($ledgerFile -and -not (Test-PathInsideRoot $ledgerFile ([string]$settings.ledger_root))) { $errors.Add('Transport ledger outside ledger root') }
    if ($ledgerHash) {
        if (-not (Test-Path -LiteralPath $ledgerFile -PathType Leaf)) { $errors.Add('Ledger file does not exist') }
        elseif ((Get-Sha256 $ledgerFile) -ne $ledgerHash) { $errors.Add('Ledger changed since disk verification; reverify first') }
    }
    $missingFields = Get-ManifestValue $row 'missing_fields'
    foreach ($field in @($missingFields -split '[;,|]' | Where-Object { $_.Trim() })) {
        if ($field.Trim() -notin @('vehicle', 'vehicle_plate', '车牌', '车牌号')) { $errors.Add('Missing required field: ' + $field) }
    }
    $parsedSavedMtime = [datetimeoffset]::MinValue
    if (-not [datetimeoffset]::TryParse($savedMtime, [ref]$parsedSavedMtime)) { $errors.Add('Saved mtime must be an ISO 8601 timestamp') }
    if ($closeStatus -notin @('closed', 'failed', 'not_attempted')) { $errors.Add('Close status is invalid') }
    if ($closeMethod -notin @('native', 'ui', 'none')) { $errors.Add('Close method is invalid') }
    if ($closeStatus -in @('closed', 'failed') -and $closeMethod -notin @('native', 'ui')) { $errors.Add('Closed or failed close status requires native or ui close method') }
    if ($closeStatus -eq 'not_attempted' -and $closeMethod -ne 'none') { $errors.Add('Not-attempted close status requires none close method') }
    if ($closeStatus -eq 'closed' -and -not [string]::IsNullOrWhiteSpace($closeError)) { $errors.Add('Close error must be blank when close status is closed') }
    if ($closeStatus -ne 'closed' -and [string]::IsNullOrWhiteSpace($closeError)) { $errors.Add('Close error is required unless close status is closed') }
    foreach ($textValue in @($deliveryNo, $alias, $sourceName, $ledgerFile, $ledgerSheet, $ledgerRows)) {
        if (-not (Test-CleanText $textValue)) { $errors.Add('Manifest contains Unicode replacement text'); break }
    }

    $source = if ([System.IO.Path]::IsPathRooted($sourceName)) { Get-FullPath $sourceName } else { Get-FullPath (Join-Path $pendingRoot $sourceName) }
    if (-not (Test-PathInsideRoot -Path $source -Root $pendingRoot)) { $errors.Add('Source is outside pending root') }
    if ($settings.factory_pending_root -and (Test-PathInsideRoot $source ([string]$settings.factory_pending_root))) { $errors.Add('Factory notes must use archive_factory_notes.py') }
    $sourceExists = Test-Path -LiteralPath $source -PathType Leaf
    $expectedSourceHash = Get-ManifestValue $row 'source_sha256'
    if (-not $sourceExists -and $expectedSourceHash -notmatch '^[A-Fa-f0-9]{64}$') { $errors.Add('Missing source requires a previously recorded SHA256 and two matching archives') }
    $extension = [System.IO.Path]::GetExtension($source).ToLowerInvariant()
    if ($extension -notin @('.jpg', '.jpeg', '.png')) { $errors.Add('Only original JPEG and PNG images are supported; do not rename extensions') }
    if ($sourceExists -and $extension -eq '.png') {
        $stream = [IO.File]::OpenRead($source)
        try { $header = New-Object byte[] 8; $count = $stream.Read($header, 0, 8) } finally { $stream.Dispose() }
        if ($count -ne 8 -or ([BitConverter]::ToString($header)) -ne '89-50-4E-47-0D-0A-1A-0A') { $errors.Add('PNG extension does not match file signature') }
    }
    $archiveExtension = if ($extension -eq '.png') { '.png' } else { '.jpg' }

    $arrival = $null
    $arrivalText = Get-ManifestValue $row 'arrival_date'
    try {
        $arrival = [DateTime]::ParseExact($arrivalText, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    } catch {
        $errors.Add('Arrival date must use yyyy-MM-dd')
    }

    $carrier = ''
    try { $carrier = Resolve-Carrier -DeliveryNo $deliveryNo -ManifestCarrier ([string]$row.carrier) -Rules $carrierRules -AllowedCarriers $allowedCarriers }
    catch { $errors.Add($_.Exception.Message) }

    $project = $null
    try { $project = Resolve-Project -Alias $alias -ProjectMap $projectMap -PrimaryRoot $primaryRoot -SettlementRoot $settlementRoot }
    catch { $errors.Add($_.Exception.Message) }

    $primaryProjectDir = ''
    $primaryCarrierDir = ''
    $settlementProjectDir = ''
    $settlementTargetDir = ''
    $primaryBase = ''
    $settlementBase = ''
    $sourceHash = ''

    if ($project -and $carrier) {
        $primaryProjectDir = Get-FullPath (Join-Path $primaryRoot $project.archive_project)
        $mappedCarrierFolder = ([string]$project.archive_carrier_folder).Trim()
        $carrierFolder = if ([string]::IsNullOrWhiteSpace($mappedCarrierFolder)) { $carrier } else { $mappedCarrierFolder }
        $primaryCarrierDir = Get-FullPath (Join-Path $primaryProjectDir $carrierFolder)
        $settlementProjectDir = Get-FullPath (Join-Path $settlementRoot $project.settlement_project)
        if (-not (Test-Path -LiteralPath $primaryProjectDir -PathType Container)) { $errors.Add('Primary project directory does not exist') }
        if (-not (Test-Path -LiteralPath $primaryCarrierDir -PathType Container)) { $errors.Add('Primary carrier directory does not exist') }
        if (-not (Test-Path -LiteralPath $settlementProjectDir -PathType Container)) { $errors.Add('Settlement project directory does not exist') }

        if ($arrival) {
            $settlementTargetDir = Get-FullPath (Join-Path $settlementProjectDir ($arrival.Year.ToString()))
        } else {
            $settlementTargetDir = $settlementProjectDir
        }

        if (-not (Test-PathInsideRoot $primaryCarrierDir $primaryRoot)) { $errors.Add('Primary target is outside archive root') }
        if (-not (Test-PathInsideRoot $settlementTargetDir $settlementRoot)) { $errors.Add('Settlement target is outside archive root') }

        if ($errors.Count -eq 0) {
            $sourceHash = if ($sourceExists) { Get-Sha256 $source } else { $expectedSourceHash }
            if ($expectedSourceHash -and $sourceHash -ne $expectedSourceHash) { $errors.Add('Source hash changed since verification') }
            $primaryBase = Join-Path $primaryCarrierDir ($deliveryNo + $archiveExtension)
            $settlementBase = Join-Path $settlementTargetDir (($arrival.ToString('MMdd')) + $settlementMarker + $deliveryNo + $archiveExtension)
            foreach ($otherExtension in @('.jpg', '.jpeg', '.png')) {
                if ($otherExtension -eq $archiveExtension) { continue }
                if ((Test-Path -LiteralPath (Join-Path $primaryCarrierDir ($deliveryNo + $otherExtension))) -or
                    (Test-Path -LiteralPath (Join-Path $settlementTargetDir (($arrival.ToString('MMdd')) + $settlementMarker + $deliveryNo + $otherExtension)))) {
                    $errors.Add('Same delivery number already archived with another image extension; review photo identity first')
                }
            }
        }
    }

    $targets = $null
    if ($errors.Count -eq 0) {
        try { $targets = Resolve-PairedTargets -PrimaryBase $primaryBase -SettlementBase $settlementBase -SourceHash $sourceHash }
        catch { $errors.Add($_.Exception.Message) }
        if (-not $sourceExists -and $targets -and (-not $targets.PrimaryExists -or -not $targets.SettlementExists)) { $errors.Add('Source absent and dual archives incomplete; manual recovery required') }
    }

    [pscustomobject]@{
        Source = $source
        DeliveryNo = $deliveryNo
        Carrier = $carrier
        ProjectAlias = $alias
        ArrivalDate = $arrivalText
        LedgerFile = $ledgerFile
        LedgerSheet = $ledgerSheet
        LedgerRows = $ledgerRows
        LedgerHash = $ledgerHash
        MissingFields = $missingFields
        RecognitionStatus = $recognitionStatus
        ReadbackStatus = $readbackStatus
        SaveStatus = $saveStatus
        LedgerSaved = Get-ManifestValue $row 'ledger_saved'
        SaveMethod = $saveMethod
        SavedMtime = $savedMtime
        CloseStatus = $closeStatus
        CloseMethod = $closeMethod
        CloseError = $closeError
        ArchiveProject = if ($project) { $project.archive_project } else { '' }
        SettlementProject = if ($project) { $project.settlement_project } else { '' }
        PrimaryDirectory = $primaryCarrierDir
        PrimaryBase = $primaryBase
        SettlementBase = $settlementBase
        PrimaryTarget = if ($targets) { $targets.Primary } else { '' }
        SettlementTarget = if ($targets) { $targets.Settlement } else { '' }
        SourceHash = $sourceHash
        PrimaryStatus = if ($targets -and $targets.PrimaryExists) { 'verified_existing' } else { 'pending' }
        SettlementStatus = if ($targets -and $targets.SettlementExists) { 'verified_existing' } else { 'pending' }
        CleanupStatus = if ($sourceExists) { 'pending' } else { 'already_absent' }
        PrimaryHash = if ($targets -and $targets.PrimaryExists) { Get-Sha256 $targets.Primary } else { '' }
        SettlementHash = if ($targets -and $targets.SettlementExists) { Get-Sha256 $targets.Settlement } else { '' }
        Status = if ($errors.Count -eq 0) { if ($targets.PrimaryExists -and $targets.SettlementExists) { 'AlreadyComplete' } else { 'Ready' } } else { 'Blocked' }
        Message = $errors -join '; '
    }
}

$results = [System.Collections.Generic.List[object]]::new()
foreach ($item in $preflight) {
    if ($item.Status -eq 'Blocked' -or -not $Execute) {
        $results.Add($item)
        continue
    }

    try {
        if ($item.LedgerHash -and (Get-Sha256 $item.LedgerFile) -ne $item.LedgerHash) { throw 'Ledger changed after preflight; reverify first' }
        $targets = Resolve-PairedTargets -PrimaryBase $item.PrimaryBase -SettlementBase $item.SettlementBase -SourceHash $item.SourceHash
        if (Test-Path -LiteralPath $item.Source -PathType Leaf) {
            if ((Get-Sha256 $item.Source) -ne $item.SourceHash) { throw 'Source changed after preflight' }
        } elseif (-not $targets.PrimaryExists -or -not $targets.SettlementExists) { throw 'Source absent before dual archive completion' }
        $yearDir = Split-Path -Parent $targets.Settlement
        if (-not (Test-PathInsideRoot $yearDir $settlementRoot)) { throw 'Year directory outside settlement root' }
        if (-not (Test-Path -LiteralPath (Split-Path -Parent $yearDir) -PathType Container)) { throw 'Confirmed project directory disappeared; do not recreate it' }
        if (-not (Test-Path -LiteralPath $yearDir -PathType Container)) { [IO.Directory]::CreateDirectory($yearDir) | Out-Null }
        if (-not $targets.PrimaryExists) {
            [System.IO.File]::Copy($item.Source, $targets.Primary, $false)
            $item.PrimaryStatus = 'copied'
        }
        if (-not $targets.SettlementExists) {
            [System.IO.File]::Copy($item.Source, $targets.Settlement, $false)
            $item.SettlementStatus = 'copied'
        }

        if ((Get-Sha256 $targets.Primary) -ne $item.SourceHash) { throw 'Primary archive hash verification failed' }
        if ((Get-Sha256 $targets.Settlement) -ne $item.SourceHash) { throw 'Settlement archive hash verification failed' }

        $item.PrimaryHash = Get-Sha256 $targets.Primary
        $item.SettlementHash = Get-Sha256 $targets.Settlement

        $item.Status = 'ArchivesVerified'
        $item | ConvertTo-Json -Compress | Add-Content -LiteralPath $journalPath -Encoding UTF8
        if (Test-Path -LiteralPath $item.Source -PathType Leaf) {
            if ((Get-Sha256 $item.Source) -ne $item.SourceHash) { throw 'Source changed before cleanup; keep source and both archives' }
            if ($item.LedgerHash -and (Get-Sha256 $item.LedgerFile) -ne $item.LedgerHash) { throw 'Ledger changed before cleanup; retain source' }
            Remove-Item -LiteralPath $item.Source
            $item.CleanupStatus = 'deleted'
            $item.Status = 'Completed'
            $item.Message = 'Both archive hashes verified; pending source deleted'
        } else {
            $item.CleanupStatus = 'already_absent'
            $item.Status = 'AlreadyComplete'
            $item.Message = 'Both archive hashes verified; source was already absent; no deletion performed'
        }
        $item.PrimaryTarget = $targets.Primary
        $item.SettlementTarget = $targets.Settlement
    } catch {
        # Keep verified copies after partial failure so the next run can resume.
        $item.Status = 'Blocked'
        $item.Message = $_.Exception.Message
    }
    $item | ConvertTo-Json -Compress | Add-Content -LiteralPath $journalPath -Encoding UTF8
    $results.Add($item)
}

$results | Select-Object DeliveryNo, Carrier, ProjectAlias, LedgerFile, LedgerSheet, LedgerRows, SaveMethod, SavedMtime, CloseStatus, CloseMethod, CloseError, Status, Message, PrimaryTarget, SettlementTarget, SourceHash, PrimaryHash, SettlementHash

if ($ReportPath) {
    $reportFullPath = Get-FullPath $ReportPath
    $reportDirectory = Split-Path -Parent $reportFullPath
    if (-not (Test-Path -LiteralPath $reportDirectory -PathType Container)) {
        throw "Report directory does not exist: $reportDirectory"
    }
    $results | Select-Object `
        @{Name='source_file';Expression={$_.Source}}, `
        @{Name='delivery_no';Expression={$_.DeliveryNo}}, `
        @{Name='carrier';Expression={$_.Carrier}}, `
        @{Name='project_alias';Expression={$_.ProjectAlias}}, `
        @{Name='arrival_date';Expression={$_.ArrivalDate}}, `
        @{Name='ledger_file';Expression={$_.LedgerFile}}, `
        @{Name='ledger_sheet';Expression={$_.LedgerSheet}}, `
        @{Name='ledger_rows';Expression={$_.LedgerRows}}, `
        @{Name='ledger_sha256';Expression={$_.LedgerHash}}, `
        @{Name='missing_fields';Expression={$_.MissingFields}}, `
        @{Name='recognition_status';Expression={$_.RecognitionStatus}}, `
        @{Name='readback_status';Expression={$_.ReadbackStatus}}, `
        @{Name='save_status';Expression={$_.SaveStatus}}, `
        @{Name='ledger_saved';Expression={$_.LedgerSaved}}, `
        @{Name='save_method';Expression={$_.SaveMethod}}, `
        @{Name='saved_mtime';Expression={$_.SavedMtime}}, `
        @{Name='close_status';Expression={$_.CloseStatus}}, `
        @{Name='close_method';Expression={$_.CloseMethod}}, `
        @{Name='close_error';Expression={$_.CloseError}}, `
        @{Name='primary_target';Expression={$_.PrimaryTarget}}, `
        @{Name='settlement_target';Expression={$_.SettlementTarget}}, `
        @{Name='archive_status';Expression={$_.Status}}, `
        @{Name='primary_status';Expression={$_.PrimaryStatus}}, `
        @{Name='settlement_status';Expression={$_.SettlementStatus}}, `
        @{Name='cleanup_status';Expression={$_.CleanupStatus}}, `
        @{Name='source_sha256';Expression={$_.SourceHash}}, `
        @{Name='primary_sha256';Expression={$_.PrimaryHash}}, `
        @{Name='settlement_sha256';Expression={$_.SettlementHash}}, `
        @{Name='error_reason';Expression={$_.Message}} |
        Export-Csv -LiteralPath $reportFullPath -NoTypeInformation -Encoding UTF8
}

$blockedCount = @($results | Where-Object { $_.Status -eq 'Blocked' }).Count
$completedCount = @($results | Where-Object { $_.Status -eq 'Completed' }).Count
$alreadyCompleteCount = @($results | Where-Object { $_.Status -eq 'AlreadyComplete' }).Count
$readyCount = @($results | Where-Object { $_.Status -eq 'Ready' }).Count
$pendingCount = if (Test-Path -LiteralPath $pendingRoot -PathType Container) {
    @(Get-ChildItem -LiteralPath $pendingRoot -File | Where-Object { $_.Extension.ToLowerInvariant() -in @('.jpg', '.jpeg', '.png') }).Count
} else { 0 }
Write-Host ("Summary: completed={0}; already_complete={1}; ready={2}; blocked={3}; pending_images={4}" -f $completedCount, $alreadyCompleteCount, $readyCount, $blockedCount, $pendingCount)
if ($blockedCount -gt 0) {
    Write-Error "$blockedCount item(s) were not completed; pending sources were retained." -ErrorAction Continue
    exit 2
}
