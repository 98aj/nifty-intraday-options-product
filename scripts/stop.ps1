# Stop the NIFTY bot engine + dashboard (Windows PowerShell).
# Usage: .\scripts\stop.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py (Join-Path $root "scripts\run.py") stop
