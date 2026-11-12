# Start the NIFTY bot engine + dashboard (Windows PowerShell).
# Usage:
#   .\scripts\start.ps1          # use config.yaml (live/paper as configured)
#   .\scripts\start.ps1 -Sim     # force simulated feed (no token needed)
param(
    [switch]$Sim
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Prefer the project venv if present.
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$runArgs = @((Join-Path $root "scripts\run.py"), "start")
if ($Sim) { $runArgs += "--sim" }

Write-Host "Starting engine + dashboard using $py ..."
& $py $runArgs
