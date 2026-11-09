"""
MemoryOS System Tray Icon & Global Hotkey (Ctrl+Alt+P).
Shows recording state, allows instant pause/resume, and provides quick actions.
"""

import logging
import threading
import time
import webbrowser
from typing import Callable, Optional
from PIL import Image, ImageDraw
from pynput import keyboard
import pystray

logger = logging.getLogger("memoryos.tray")


def create_tray_image(color: str = "#10b981") -> Image.Image:
    """Generate dynamic system tray icon circle."""
    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Background circle
    draw.ellipse((8, 8, 56, 56), fill=color)
    # Inner accent
    draw.ellipse((22, 22, 42, 42), fill="#ffffff")
    return img


class SystemTrayService:
    """Manages the Windows taskbar notification tray icon and global hotkey."""

    def __init__(
        self,
        on_toggle_pause: Callable[[Optional[bool]], None],
        on_pause_for_hour: Callable[[], None],
        on_exit: Callable[[], None]
    ):
        self.on_toggle_pause = on_toggle_pause
        self.on_pause_for_hour = on_pause_for_hour
        self.on_exit = on_exit

        self.icon: Optional[pystray.Icon] = None
        self.is_paused: bool = False
        self.pause_until: Optional[float] = None
        self.hotkey_listener: Optional[keyboard.GlobalHotKeys] = None

    def _get_status_text(self) -> str:
        if self.pause_until and time.time() < self.pause_until:
            remaining = int((self.pause_until - time.time()) / 60)
            return f"Paused ({remaining}m remaining)"
        return "Paused" if self.is_paused else "Recording Active"

    def _toggle_hotkey(self):
        """Handler for Ctrl+Alt+P."""
        logger.info("[Hotkey] Ctrl+Alt+P triggered!")
        self.is_paused = not self.is_paused
        self.pause_until = None
        self.on_toggle_pause(self.is_paused)
        self.update_state(self.is_paused)

    def _menu_pause(self):
        self.is_paused = True
        self.pause_until = None
        self.on_toggle_pause(True)
        self.update_state(True)

    def _menu_resume(self):
        self.is_paused = False
        self.pause_until = None
        self.on_toggle_pause(False)
        self.update_state(False)

    def _menu_pause_hour(self):
        self.is_paused = True
        self.pause_until = time.time() + 3600
        self.on_pause_for_hour()
        self.update_state(True, temporary=True)

    def _menu_open_dashboard(self):
        webbrowser.open("http://localhost:3000")

    def _create_menu(self):
        return pystray.Menu(
            pystray.MenuItem(self._get_status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Resume Recording", self._menu_resume, visible=lambda item: self.is_paused),
            pystray.MenuItem("Pause Recording", self._menu_pause, visible=lambda item: not self.is_paused),
            pystray.MenuItem("Pause for 1 Hour", self._menu_pause_hour),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open MemoryOS Dashboard", self._menu_open_dashboard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit Agent", self.on_exit)
        )

    def update_state(self, is_paused: bool, temporary: bool = False):
        self.is_paused = is_paused
        if self.icon:
            color = "#f59e0b" if temporary else ("#ef4444" if is_paused else "#10b981")
            self.icon.icon = create_tray_image(color)
            self.icon.title = f"MemoryOS: {self._get_status_text()}"

    def start(self):
        # 1. Setup Global Hotkey (Ctrl+Alt+P)
        try:
            self.hotkey_listener = keyboard.GlobalHotKeys({
                "<ctrl>+<alt>+p": self._toggle_hotkey
            })
            self.hotkey_listener.daemon = True
            self.hotkey_listener.start()
            logger.info("Global hotkey registered: Ctrl+Alt+P")
        except Exception as e:
            logger.warning(f"Could not register global hotkey: {e}")

        # 2. Setup Tray Icon
        self.icon = pystray.Icon(
            name="MemoryOS",
            icon=create_tray_image("#10b981"),
            title="MemoryOS: Recording Active",
            menu=self._create_menu()
        )
        tray_thread = threading.Thread(target=self.icon.run, daemon=True)
        tray_thread.start()
        logger.info("System tray icon initialized.")

    def stop(self):
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        if self.icon:
            self.icon.stop()
