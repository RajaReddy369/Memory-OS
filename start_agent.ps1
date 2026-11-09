# MemoryOS Windows Desktop Agent Startup Script
$Host.UI.RawUI.WindowTitle = "MemoryOS Desktop Agent"

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "            MemoryOS Windows Desktop Agent               " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[Error] Virtual environment not found at $VenvPython." -ForegroundColor Red
    exit 1
}

Write-Host "System Tray Icon   : Active in Notification Area" -ForegroundColor Gray
Write-Host "Global Pause Hotkey: Ctrl + Alt + P" -ForegroundColor Cyan
Write-Host "Allowed Typing Apps: VS Code, Notepad, Word, Cursor" -ForegroundColor Gray
Write-Host "Starting agent daemon..." -ForegroundColor Gray

& $VenvPython -m desktop_agent.agent

