@echo off
title MemoryOS Desktop Agent
echo ==========================================================
echo             MemoryOS Windows Desktop Agent                
echo ==========================================================
if not exist ".venv\Scripts\python.exe" (
    echo [Error] Virtual environment not found at .venv\Scripts\python.exe.
    pause
    exit /b 1
)
echo Global Pause Hotkey: Ctrl + Alt + P
.venv\Scripts\python.exe -m desktop_agent.agent
pause
