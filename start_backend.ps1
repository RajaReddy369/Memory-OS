# MemoryOS Windows PowerShell Startup Script
$Host.UI.RawUI.WindowTitle = "MemoryOS Local Server"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "                MemoryOS Cognitive Engine                  " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[Error] Virtual environment not found at $VenvPython." -ForegroundColor Red
    Write-Host "Please run 'uv venv --python 3.12 .venv' and install requirements." -ForegroundColor Yellow
    exit 1
}

# Display token if exists
$AppDataDir = if ($env:MEMORYOS_DATA_DIR) { $env:MEMORYOS_DATA_DIR } elseif ($env:APPDATA) { Join-Path $env:APPDATA "MemoryOS" } else { Join-Path $PSScriptRoot "data" }
$TokenFile = Join-Path $AppDataDir "token.txt"

Write-Host "Storage Directory : $AppDataDir" -ForegroundColor Gray
Write-Host "API Host          : 127.0.0.1:8000" -ForegroundColor Gray

# Start backend server
& $VenvPython -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
