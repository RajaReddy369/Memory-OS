"""
MemoryOS Watchdog File Activity Monitor.
Monitors created/modified events across configured folders (Documents, Desktop, Downloads, workspace).
Extracts and indexes text of small code, markdown, and text files under 500KB.
"""

import logging
import os
from pathlib import Path
import time
from typing import Callable, List, Optional
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from backend.config import DATA_DIR, WATCHED_FOLDERS
from backend.scrubber import scrub_text

logger = logging.getLogger("memoryos.file_watcher")

MAX_FILE_SIZE_BYTES = 500 * 1024  # 500 KB limit
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".json", ".yaml", ".yml", ".csv", ".sql", ".rst"
}
IGNORED_PATTERNS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".tmp"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".kdbx"}
SENSITIVE_NAME_PREFIXES = (".env", "id_rsa", "credentials", "secrets")


def is_ignored_path(path: Path) -> bool:
    """Check if path belongs to excluded system, cache, or MemoryOS data directories."""
    try:
        resolved = path.resolve()
        # Exclude %APPDATA%\MemoryOS and local data dir so the agent never logs itself
        data_resolved = DATA_DIR.resolve()
        if resolved == data_resolved or data_resolved in resolved.parents:
            return True
        # Check standard ignored directory names
        for part in resolved.parts:
            if part in IGNORED_PATTERNS:
                return True
    except Exception:
        pass
    return False


def is_sensitive_file(path: Path) -> bool:
    """Never index .env, *.pem, *.key, id_rsa*, credentials*, secrets*, *.kdbx."""
    name_lower = path.name.lower()
    ext_lower = path.suffix.lower()

    if ext_lower in SENSITIVE_SUFFIXES:
        return True
    if any(name_lower.startswith(prefix) for prefix in SENSITIVE_NAME_PREFIXES):
        return True
    if "credentials" in name_lower or "secrets" in name_lower:
        return True
    return False


def is_in_downloads(path: Path) -> bool:
    """Check if path is located inside the user's Downloads directory."""
    downloads = Path.home() / "Downloads"
    try:
        resolved = path.resolve()
        downloads_resolved = downloads.resolve()
        if resolved == downloads_resolved or downloads_resolved in resolved.parents:
            return True
    except Exception:
        pass
    return "downloads" in [p.lower() for p in path.parts]


class MemoryOSFileHandler(FileSystemEventHandler):
    """Handles file system creation and modification events."""

    def __init__(self, callback: Callable[[dict], None]):
        super().__init__()
        self.callback = callback
        self.last_events: dict = {}

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory:
            self._handle_event(event.src_path, "created")

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory:
            self._handle_event(event.src_path, "modified")

    def _handle_event(self, path_str: str, action: str):
        path = Path(path_str)
        # 1. Exclude %APPDATA%\MemoryOS, .venv, .git, node_modules, __pycache__
        if is_ignored_path(path):
            return

        # 2. Never index .env, *.pem, *.key, id_rsa*, credentials*, secrets*, *.kdbx
        if is_sensitive_file(path):
            logger.debug(f"Skipping sensitive file: {path.name}")
            return

        ext = path.suffix.lower()

        now = time.time()
        # Debounce repeated file modification events within 3 seconds
        last_t = self.last_events.get(path_str, 0.0)
        if now - last_t < 3.0:
            return
        self.last_events[path_str] = now

        # 3. Downloads folder: log file name/type only, NEVER index contents
        if is_in_downloads(path):
            event_dict = {
                "event_type": f"file_{action}",
                "source": "desktop",
                "timestamp": now,
                "title": f"Downloaded: {path.name}",
                "text_content": "",  # NEVER index contents of Downloads folder
                "app_name": "Explorer",
                "metadata": {
                    "file_path": str(path.resolve()),
                    "file_name": path.name,
                    "extension": ext,
                    "file_size": path.stat().st_size if path.exists() else 0,
                    "action": action,
                    "download_metadata_only": True
                }
            }
            self.callback(event_dict)
            return

        # 4. For standard text files, extract and scrub content
        if ext not in TEXT_EXTENSIONS:
            return

        try:
            if not path.exists() or path.stat().st_size > MAX_FILE_SIZE_BYTES:
                return

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return

            clean_text = scrub_text(content[:15000])

            event_dict = {
                "event_type": f"file_{action}",
                "source": "desktop",
                "timestamp": now,
                "title": f"File {action}: {path.name}",
                "text_content": clean_text,
                "app_name": "Explorer",
                "metadata": {
                    "file_path": str(path.resolve()),
                    "file_name": path.name,
                    "extension": ext,
                    "file_size": path.stat().st_size,
                    "action": action
                }
            }
            self.callback(event_dict)
        except Exception as e:
            logger.debug(f"Could not read file {path}: {e}")


class FileWatcherService:
    """Manages the background Watchdog observer across configured directories."""

    def __init__(self, callback: Callable[[dict], None], watch_paths: Optional[List[Path]] = None):
        self.callback = callback
        self.watch_paths = watch_paths or WATCHED_FOLDERS
        self.observer: Optional[Observer] = None

    def start(self):
        self.observer = Observer()
        handler = MemoryOSFileHandler(self.callback)

        watched_count = 0
        for p in self.watch_paths:
            if p.exists() and p.is_dir():
                self.observer.schedule(handler, str(p), recursive=True)
                watched_count += 1
                logger.info(f"File watcher observing: {p}")

        if watched_count > 0:
            self.observer.daemon = True
            self.observer.start()
            logger.info(f"File watcher started with {watched_count} roots.")

    def stop(self):
        if self.observer and self.observer.is_alive():
            self.observer.stop()
            self.observer.join(timeout=2.0)
            self.observer = None

