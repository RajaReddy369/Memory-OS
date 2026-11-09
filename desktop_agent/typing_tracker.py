"""
MemoryOS Privacy-Preserving Typing Capture.
Captures typed text CHUNKS strictly inside an allowlist of applications (VS Code, Notepad, Word, Cursor).
NOT a global keylogger.
Immediately pauses and discards input when sensitive windows, password fields, or unlisted apps are active.
"""

import logging
import threading
import time
from typing import Callable, Optional
from pynput import keyboard

from backend.config import TYPING_APP_ALLOWLIST
from backend.scrubber import scrub_text
from desktop_agent.window_tracker import get_active_window_info

logger = logging.getLogger("memoryos.typing_tracker")

SENSITIVE_EDITOR_KEYWORDS = (
    ".env", "config.", "config_", "secrets", "credential", "id_rsa",
    ".pem", ".key", ".kdbx", "password", "token"
)


def is_sensitive_editor_title(title: str) -> bool:
    """Check if the active editor window title indicates a sensitive file (.env, config, secrets)."""
    if not title:
        return False
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in SENSITIVE_EDITOR_KEYWORDS)


class SelectiveTypingWatcher:
    """Listens for typing strictly within allowed productivity applications."""

    def __init__(self, callback: Callable[[dict], None]):
        self.callback = callback
        self.listener: Optional[keyboard.Listener] = None
        self.accumulated_text: str = ""
        self.last_app: str = ""
        self.last_window_title: str = ""
        self.debounce_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def _flush_chunk(self):
        with self._lock:
            text = self.accumulated_text.strip()
            self.accumulated_text = ""

        if len(text) >= 8:
            clean_text = scrub_text(text)
            event_dict = {
                "event_type": "typed_input",
                "source": "desktop",
                "timestamp": time.time(),
                "title": f"Typing in {self.last_app}",
                "text_content": clean_text,
                "app_name": self.last_app,
                "metadata": {
                    "window_title": self.last_window_title
                }
            }
            self.callback(event_dict)

    def _on_press(self, key):
        # 1. Inspect foreground window
        win_info = get_active_window_info()
        if not win_info:
            # Sensitive window or blocked: clear any buffer immediately
            with self._lock:
                self.accumulated_text = ""
            return

        proc = (win_info.get("process_name") or "").lower()
        if proc not in TYPING_APP_ALLOWLIST:
            # Not in allowed applications list: strictly ignore
            return

        app_name = win_info.get("app_name", proc)
        title = win_info.get("title", "")

        # 2. In VS Code/Cursor, skip typing capture when open file is .env, config, or secrets-like
        if proc in ("code.exe", "cursor.exe", "devenv.exe") and is_sensitive_editor_title(title):
            with self._lock:
                self.accumulated_text = ""
            return

        # 3. Extract character
        char = None
        try:
            if hasattr(key, "char") and key.char:
                char = key.char
            elif key == keyboard.Key.space:
                char = " "
            elif key == keyboard.Key.enter:
                char = "\n"
        except Exception:
            pass

        if not char:
            return

        with self._lock:
            # If app switched, flush previous chunk
            if self.last_app and self.last_app != app_name:
                self._flush_chunk()

            self.last_app = app_name
            self.last_window_title = title
            self.accumulated_text += char

            # Reset debounce timer (1.5 seconds)
            if self.debounce_timer:
                self.debounce_timer.cancel()
            self.debounce_timer = threading.Timer(1.5, self._flush_chunk)
            self.debounce_timer.daemon = True
            self.debounce_timer.start()

    def start(self):
        self.listener = keyboard.Listener(on_press=self._on_press)
        self.listener.daemon = True
        self.listener.start()
        logger.info(f"Selective typing capture started (Allowed apps: {', '.join(TYPING_APP_ALLOWLIST)})")

    def stop(self):
        if self.debounce_timer:
            self.debounce_timer.cancel()
        if self.listener:
            self.listener.stop()
            self.listener = None

