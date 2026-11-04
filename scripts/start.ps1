# Start the NIFTY bot engine + dashboard (Windows PowerShell).
# Usage: .\scripts\start.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Prefer the project venv if present.
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "Starting engine + UI using $py ..."
& $py (Join-Path $root "scripts\run.py") start
Write-Host "Dashboard: http://127.0.0.1:8080"
Write-Host "State API: http://127.0.0.1:8081/state"
