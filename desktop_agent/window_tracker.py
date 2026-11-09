"""
MemoryOS Windows Active Window & Idle Tracker.
Uses native Windows Win32 APIs via ctypes to track the foreground application, window title,
active vs. idle time (via GetLastInputInfo), and enforces privacy exclusions.
"""

import ctypes
from ctypes import wintypes
import logging
import time
from typing import Dict, Optional, Tuple
import psutil

from backend.config import BLOCKED_WINDOW_TITLES, IDLE_THRESHOLD_SECONDS

logger = logging.getLogger("memoryos.window_tracker")

# Windows API Structures
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD)
    ]


user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None


def get_idle_seconds() -> float:
    """Return seconds elapsed since the last user keyboard or mouse input."""
    if not user32 or not kernel32:
        return 0.0

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if user32.GetLastInputInfo(ctypes.byref(lii)):
        tick_count = kernel32.GetTickCount()
        elapsed_ms = tick_count - lii.dwTime
        return max(0.0, elapsed_ms / 1000.0)
    return 0.0


def is_user_idle() -> bool:
    """Check if the user has been inactive for more than the idle threshold (default 2 mins)."""
    return get_idle_seconds() >= IDLE_THRESHOLD_SECONDS


def is_window_blocked(window_title: str, process_name: str) -> bool:
    """
    Check if foreground window or process matches privacy blocklist.
    Hard exclusions: Incognito, banking, login/auth, password managers, lock screen.
    """
    title_lower = (window_title or "").lower()
    proc_lower = (process_name or "").lower()

    for blocked in BLOCKED_WINDOW_TITLES:
        if blocked in title_lower or blocked in proc_lower:
            return True
    return False


def get_active_window_info() -> Optional[Dict[str, any]]:
    """
    Retrieve foreground window title, process name, and active vs. idle state.
    Returns None if no active window or if window is in the privacy blocklist.
    """
    if not user32:
        return None

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    # Get window title
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return None

    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    title = buffer.value.strip()

    # Get process ID and name
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process_name = "unknown.exe"
    try:
        proc = psutil.Process(pid.value)
        process_name = proc.name()
    except Exception:
        pass

    # Hard privacy exclusion
    if is_window_blocked(title, process_name):
        return None

    idle_sec = get_idle_seconds()
    is_idle = idle_sec >= IDLE_THRESHOLD_SECONDS

    return {
        "hwnd": hwnd,
        "title": title,
        "process_name": process_name,
        "app_name": process_name.replace(".exe", "").title(),
        "is_idle": is_idle,
        "idle_seconds": round(idle_sec, 1)
    }

