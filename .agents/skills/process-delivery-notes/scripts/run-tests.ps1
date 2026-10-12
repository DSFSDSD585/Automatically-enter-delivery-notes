[CmdletBinding()]
param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) {
    $PythonPath = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (-not (Test-Path -LiteralPath $PythonPath)) { $PythonPath = (Get-Command python).Source }
}
& $PythonPath -B -m unittest discover -s $PSScriptRoot -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Python regression checks failed' }
& $PythonPath -B (Join-Path $PSScriptRoot 'rules_data.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Business rule appendix and generated mappings differ' }
$shell = (Get-Process -Id $PID).Path
& $shell -NoProfile -File (Join-Path $PSScriptRoot 'test-archive-delivery-notes.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Self-pickup archive regression checks failed' }
