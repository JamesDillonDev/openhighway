<#
.SYNOPSIS
    Starts the full openhighway dev environment.
.DESCRIPTION
    Syncs camera sources into the database, then launches backend/app.py (Flask
    API), src/vehicle_watcher.py (if present), and the frontend Vite dev server,
    each in its own PowerShell window so logs stay separate and any one of them
    can be stopped independently with Ctrl+C.
.PARAMETER SkipSync
    Don't run sync_sources.py before starting the servers.
.PARAMETER SkipWatcher
    Don't start vehicle_watcher.py.
.PARAMETER SkipInstall
    Skip installing frontend npm dependencies even if node_modules is missing.
#>
param(
    [switch]$SkipSync,
    [switch]$SkipWatcher,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$srcDir = Join-Path $root "src"

function Start-DevWindow {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$Command
    )

    Start-Process pwsh -ArgumentList @(
        "-NoExit",
        "-Command",
        "`$Host.UI.RawUI.WindowTitle = '$Title'; $Command"
    ) -WorkingDirectory $WorkingDirectory
}

if (-not $SkipInstall -and -not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "Installing frontend dependencies..."
    Push-Location $frontendDir
    npm install
    Pop-Location
}

if (-not $SkipSync) {
    Write-Host "Syncing camera sources into the database..."
    Push-Location $srcDir
    python .\sync_sources.py
    Pop-Location
}

Write-Host "Starting backend API (http://127.0.0.1:5000)..."
Start-DevWindow -Title "openhighway - backend" -WorkingDirectory $backendDir -Command "python .\app.py"

$watcherScript = Join-Path $srcDir "vehicle_watcher.py"

if (-not $SkipWatcher) {

    if (Test-Path $watcherScript) {
        Write-Host "Starting vehicle watcher..."
        Start-DevWindow -Title "openhighway - vehicle_watcher" -WorkingDirectory $srcDir -Command "python .\vehicle_watcher.py"
    } else {
        Write-Host "src/vehicle_watcher.py not found yet - skipping."
    }
}

Write-Host "Starting frontend dev server (http://localhost:5173)..."
Start-DevWindow -Title "openhighway - frontend" -WorkingDirectory $frontendDir -Command "npm run dev"

Write-Host "All dev processes launched in separate windows. Close a window or press Ctrl+C in it to stop that process."
