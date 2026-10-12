# Same discovery contract as delivery_paths.pending_files: loose images plus 自提,
# recursively below the selected mode directory, excluding directory redirections.
function Get-SelfPickupImages {
    param($Settings)
    $root = [IO.Path]::GetFullPath([string]$Settings.pending_root)
    $selected = if ($Settings.self_pickup_pending_root) { [string]$Settings.self_pickup_pending_root } else { Join-Path $root '自提' }
    $factory = if ($Settings.factory_pending_root) { [IO.Path]::GetFullPath([string]$Settings.factory_pending_root) } else { Join-Path $root '厂发' }
    $found = @{}
    if ((Test-Path -LiteralPath $root -PathType Container) -and $root -ne $factory) {
        Get-ChildItem -LiteralPath $root -File | Where-Object { $_.Extension.ToLowerInvariant() -in @('.jpg','.jpeg','.png') -and -not $_.LinkType } | ForEach-Object { $found[$_.FullName] = $_ }
    }
    $queue = [Collections.Generic.Queue[string]]::new()
    if (Test-Path -LiteralPath $selected -PathType Container) { $queue.Enqueue([IO.Path]::GetFullPath($selected)) }
    while ($queue.Count) {
        $directory = $queue.Dequeue()
        Get-ChildItem -LiteralPath $directory | ForEach-Object {
            if ($_.PSIsContainer) {
                if ($_.FullName -ne $factory -and -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)) { $queue.Enqueue($_.FullName) }
            } elseif ($_.Extension.ToLowerInvariant() -in @('.jpg','.jpeg','.png') -and -not $_.LinkType) { $found[$_.FullName] = $_ }
        }
    }
    $found.Values | Sort-Object FullName
}
