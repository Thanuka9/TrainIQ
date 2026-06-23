# TrainIQ production web startup (Windows / PowerShell)
# Usage: .\scripts\start_production.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not $env:FLASK_ENV) { $env:FLASK_ENV = "production" }
if (-not $env:RUN_SCHEDULER) { $env:RUN_SCHEDULER = "false" }
if (-not $env:EVENT_BUS_CONSUMER) { $env:EVENT_BUS_CONSUMER = "false" }

Write-Host "Running production preflight..."
python scripts/production_preflight.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Applying migrations..."
$env:FLASK_APP = "app.py"
flask db upgrade
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Starting gunicorn..."
gunicorn -c gunicorn.conf.py app:app
