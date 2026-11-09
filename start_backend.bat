@echo off
title MemoryOS Local Server
echo ==========================================================
echo                 MemoryOS Cognitive Engine                 
echo ==========================================================

if not exist ".venv\Scripts\python.exe" (
    echo [Error] Virtual environment not found at .venv\Scripts\python.exe.
    pause
    exit /b 1
)

echo Starting MemoryOS on http://127.0.0.1:8000 ...
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
pause
