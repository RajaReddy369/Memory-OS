"""
MemoryOS Desktop Agent Daemon.
Continuously coordinates window tracking, clipboard watching, file monitoring,
selective typing capture, resource monitoring, and offline queueing.
"""

import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Dict, List, Optional
import httpx

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import API_TOKEN, DATA_DIR, HOST, PORT
from desktop_agent.clipboard_tracker import ClipboardWatcher
from desktop_agent.file_watcher import FileWatcherService
from desktop_agent.resource_monitor import AgentResourceMonitor
from desktop_agent.tray import SystemTrayService
from desktop_agent.typing_tracker import SelectiveTypingWatcher
from desktop_agent.window_tracker import get_active_window_info

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [Agent] %(message)s")
logger = logging.getLogger("memoryos.agent")

QUEUE_FILE = DATA_DIR / "desktop_queue.json"


class DesktopAgent:
    """Core Desktop Agent Daemon."""

    def __init__(self, api_url: Optional[str] = None):
        self.api_url = api_url or f"http://{HOST}:{PORT}"
        self.is_paused: bool = False
        self.pause_until: Optional[float] = None
        self.running: bool = False

        self.queue: List[Dict[str, Any]] = []
        self.queue_lock = threading.Lock()
        self._load_offline_queue()

        # Track active window state
        self.last_window: Optional[Dict[str, Any]] = None
        self.window_start_time: float = time.time()

        # Component watchers
        self.clipboard_watcher = ClipboardWatcher()
        self.file_watcher = FileWatcherService(callback=self.enqueue_event)
        self.typing_watcher = SelectiveTypingWatcher(callback=self.enqueue_event)
        self.resource_monitor = AgentResourceMonitor()
        self.tray_service = SystemTrayService(
            on_toggle_pause=self.set_pause,
            on_pause_for_hour=self.pause_for_hour,
            on_exit=self.stop
        )

    def _load_offline_queue(self):
        if QUEUE_FILE.exists():
            try:
                data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.queue = data[:300]
                    logger.info(f"Loaded {len(self.queue)} events from offline queue.")
            except Exception:
                self.queue = []

    def _save_offline_queue(self):
        with self.queue_lock:
            try:
                QUEUE_FILE.write_text(json.dumps(self.queue[-300:]), encoding="utf-8")
            except Exception:
                pass

    def enqueue_event(self, event: Dict[str, Any]):
        """Enqueue event for transmission to backend API."""
        if self.is_paused:
            if self.pause_until and time.time() >= self.pause_until:
                self.is_paused = False
                self.pause_until = None
            else:
                return

        with self.queue_lock:
            self.queue.append(event)

    def set_pause(self, paused: Optional[bool] = None):
        if paused is not None:
            self.is_paused = paused
        else:
            self.is_paused = not self.is_paused
        logger.info(f"Agent recording state: {'PAUSED' if self.is_paused else 'ACTIVE'}")

    def pause_for_hour(self):
        self.is_paused = True
        self.pause_until = time.time() + 3600
        logger.info("Agent recording paused for 1 hour.")

    def flush_queue(self):
        """Send queued events to local backend API."""
        with self.queue_lock:
            if not self.queue:
                return
            to_send = list(self.queue)
            self.queue = []

        headers = {
            "Content-Type": "application/json",
            "X-MemoryOS-Key": API_TOKEN
        }

        try:
            with httpx.Client(timeout=4.0) as client:
                res = client.post(
                    f"{self.api_url}/api/events/batch",
                    json={"events": to_send},
                    headers=headers
                )
                if res.status_code != 200:
                    with self.queue_lock:
                        self.queue = to_send + self.queue
        except Exception:
            # Backend unreachable: restore to queue and persist to disk
            with self.queue_lock:
                self.queue = (to_send + self.queue)[-500:]
            self._save_offline_queue()

    def _track_window_loop(self):
        """Polls active foreground window and detects context switches."""
        while self.running:
            try:
                win = get_active_window_info()
                now = time.time()

                if win:
                    title = win["title"]
                    app = win["app_name"]

                    if self.last_window is None:
                        self.last_window = win
                        self.window_start_time = now
                    else:
                        prev_title = self.last_window["title"]
                        prev_app = self.last_window["app_name"]

                        # Check if application or title changed
                        if (title != prev_title or app != prev_app) and not win["is_idle"]:
                            duration = max(1.0, round(now - self.window_start_time, 1))
                            if duration >= 2.0:
                                self.enqueue_event({
                                    "event_type": "active_window",
                                    "source": "desktop",
                                    "timestamp": self.window_start_time,
                                    "title": prev_title,
                                    "app_name": prev_app,
                                    "duration": duration,
                                    "metadata": {
                                        "process_name": self.last_window.get("process_name")
                                    }
                                })
                            self.last_window = win
                            self.window_start_time = now
                else:
                    # Sensitive window or privacy blocklist active: flush previous window if any
                    if self.last_window:
                        duration = max(1.0, round(now - self.window_start_time, 1))
                        if duration >= 2.0:
                            self.enqueue_event({
                                "event_type": "active_window",
                                "source": "desktop",
                                "timestamp": self.window_start_time,
                                "title": self.last_window["title"],
                                "app_name": self.last_window["app_name"],
                                "duration": duration
                            })
                        self.last_window = None

                # Poll clipboard
                clip_event = self.clipboard_watcher.poll()
                if clip_event:
                    self.enqueue_event(clip_event)

            except Exception as e:
                logger.debug(f"Window tracker loop error: {e}")

            time.sleep(1.0)

    def _resource_and_flush_loop(self):
        """Flushes queue and verifies agent CPU/RAM metrics stay under thresholds."""
        count = 0
        while self.running:
            self.flush_queue()
            count += 1

            # Sample resource metrics every 15 seconds
            if count % 3 == 0:
                is_ok, msg = self.resource_monitor.check_thresholds()
                if not is_ok:
                    logger.warning(f"[Performance Alert] {msg}")

            time.sleep(5.0)

    def start(self):
        """Start all desktop agent monitoring services."""
        self.running = True
        logger.info("Starting MemoryOS Windows Desktop Agent...")

        # 1. Start component services
        self.file_watcher.start()
        self.typing_watcher.start()
        self.tray_service.start()

        # 2. Start monitoring threads
        t1 = threading.Thread(target=self._track_window_loop, daemon=True)
        t2 = threading.Thread(target=self._resource_and_flush_loop, daemon=True)
        t1.start()
        t2.start()

        logger.info("Desktop agent fully active and recording.")
        try:
            while self.running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        """Stop all background watchers cleanly."""
        if not self.running:
            return
        logger.info("Stopping MemoryOS Desktop Agent...")
        self.running = False
        self.file_watcher.stop()
        self.typing_watcher.stop()
        self.tray_service.stop()
        self.flush_queue()
        self._save_offline_queue()
        logger.info("Desktop agent terminated.")


def main():
    agent = DesktopAgent()
    agent.start()


if __name__ == "__main__":
    main()
