"""
MemoryOS Clipboard Tracker.
Captures text clipboard changes, deduplicates, scrubs secrets, and strictly ignores
any clipboard content copied from password managers or sensitive windows.
"""

import ctypes
from ctypes import wintypes
import hashlib
import logging
from typing import Optional

from backend.config import PASSWORD_MANAGER_PROCESSES
from backend.scrubber import scrub_text
from desktop_agent.window_tracker import get_active_window_info

logger = logging.getLogger("memoryos.clipboard")

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
CF_UNICODETEXT = 13


def get_clipboard_text() -> Optional[str]:
    """Retrieve current text from Windows clipboard via Win32 ctypes."""
    if not user32:
        return None

    if not user32.OpenClipboard(None):
        return None

    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None

        # Lock memory handle to get unicode string pointer
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalLock.restype = ctypes.c_void_p
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None

        try:
            text = ctypes.c_wchar_p(ptr).value
            return text
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


class ClipboardWatcher:
    """Monitors Windows clipboard for text copy actions with privacy guards."""

    def __init__(self):
        self.last_hash: Optional[str] = None

    def poll(self) -> Optional[dict]:
        """
        Poll clipboard content.
        Returns a scrubbed clipboard event dict if new text is copied, or None if unchanged or blocked.
        """
        # 1. Check if foreground window is a password manager or blocked
        win_info = get_active_window_info()
        if not win_info:
            return None

        proc = (win_info.get("process_name") or "").lower()
        if proc in PASSWORD_MANAGER_PROCESSES:
            return None

        # 2. Get text
        text = get_clipboard_text()
        if not text or len(text.strip()) < 4 or len(text) > 50000:
            return None

        # 3. Deduplicate via hash
        content_hash = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
        if content_hash == self.last_hash:
            return None

        self.last_hash = content_hash

        # 4. Scrub secrets
        clean_text = scrub_text(text)

        return {
            "event_type": "clipboard",
            "source": "desktop",
            "app_name": win_info.get("app_name", "Desktop"),
            "title": f"Clipboard copy from {win_info.get('app_name', 'Desktop')}",
            "text_content": clean_text,
            "metadata": {
                "process_name": proc,
                "window_title": win_info.get("title", "")
            }
        }
