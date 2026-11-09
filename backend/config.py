"""
MemoryOS Configuration Module.
Handles environment variables, data directory paths, API tokens, security settings,
and Phase 3 desktop agent preferences.
"""

import os
from pathlib import Path
import secrets
from typing import List, Set


def get_default_data_dir() -> Path:
    """Return platform-appropriate persistent data directory outside the codebase with local fallback."""
    custom_dir = os.environ.get("MEMORYOS_DATA_DIR")
    if custom_dir:
        target = Path(custom_dir)
        try:
            target.mkdir(parents=True, exist_ok=True)
            return target
        except OSError:
            pass

    appdata = os.environ.get("APPDATA")
    if appdata:
        try:
            target = Path(appdata) / "MemoryOS"
            target.mkdir(parents=True, exist_ok=True)
            return target
        except (PermissionError, OSError):
            pass

    try:
        target = Path.home() / ".memoryos"
        target.mkdir(parents=True, exist_ok=True)
        return target
    except (PermissionError, OSError):
        pass

    fallback = Path.cwd() / "data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


DATA_DIR = get_default_data_dir()
DB_PATH = DATA_DIR / "memoryos.db"
TOKEN_FILE = DATA_DIR / "token.txt"


def get_or_create_api_token() -> str:
    """Retrieve existing API token or create a secure persistent random token on first run."""
    env_token = os.environ.get("MEMORYOS_API_TOKEN")
    if env_token:
        return env_token.strip()

    if TOKEN_FILE.exists():
        try:
            token = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if token:
                return token
        except Exception:
            pass

    new_token = secrets.token_hex(24)
    try:
        TOKEN_FILE.write_text(new_token, encoding="utf-8")
    except Exception as e:
        print(f"[Warning] Could not write token file {TOKEN_FILE}: {e}")

    return new_token


API_TOKEN = get_or_create_api_token()

HOST = os.environ.get("MEMORYOS_HOST", "127.0.0.1")
PORT = int(os.environ.get("MEMORYOS_PORT", "8000"))

# Default domain exclusion blocklist
DEFAULT_BLOCKED_DOMAINS: Set[str] = {
    "login.live.com",
    "accounts.google.com",
    "auth0.com",
    "okta.com",
    "chase.com",
    "bankofamerica.com",
    "wellsfargo.com",
    "citi.com",
    "fidelity.com",
    "paypal.com",
    "stripe.com",
    "1password.com",
    "bitwarden.com",
    "lastpass.com",
    "dashlane.com",
    "vault.bitwarden.com",
}

# CORS Allowed Origins
CORS_ORIGIN_REGEX = r"^(http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?|chrome-extension://.*)$"

# ========================================================
# Phase 3: Desktop Agent Configurations
# ========================================================

# 1. Folders to watch for file activity
user_home = Path.home()
WATCHED_FOLDERS: List[Path] = [
    user_home / "Documents",
    user_home / "Desktop",
    user_home / "Downloads",
    Path.cwd(),  # Workspace: e:\rag two
]

# 2. Typing Capture App Allowlist (strictly only these apps can have typing captured)
TYPING_APP_ALLOWLIST: Set[str] = {
    "code.exe",       # VS Code
    "notepad.exe",    # Notepad
    "winword.exe",    # Microsoft Word
    "cursor.exe",     # Cursor AI
    "devenv.exe",     # Visual Studio
}

# 3. Window Title Hard Blocklist
# If any of these substrings appear in the foreground window title, ALL recording is paused
BLOCKED_WINDOW_TITLES: List[str] = [
    "incognito",
    "inprivate",
    "password",
    "bitwarden",
    "1password",
    "keepass",
    "dashlane",
    "bank",
    "login",
    "sign in",
    "auth",
    "windows security",
    "lockapp",
]

# Password manager process names to skip for clipboard
PASSWORD_MANAGER_PROCESSES: Set[str] = {
    "1password.exe",
    "bitwarden.exe",
    "keepass.exe",
    "dashlane.exe",
    "lastpass.exe",
}

# Session segmentation & LLM Model
SESSION_GAP_SECONDS = 600.0  # 10 minutes gap marks a session boundary
SESSION_LABEL_MODEL = os.environ.get("MEMORYOS_SESSION_MODEL", "llama3.2")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

# Desktop Agent Resource Caps
MAX_IDLE_CPU_PERCENT = 3.0   # Must stay under 3% CPU at idle
MAX_IDLE_RAM_MB = 150.0      # Must stay under 150MB RAM at idle
IDLE_THRESHOLD_SECONDS = 120 # 2 minutes of no input marks system idle
