"""
MemoryOS Configuration Module.
Handles environment variables, data directory paths, API tokens, and security settings.
"""

import os
import secrets
from pathlib import Path
from typing import Set


def get_default_data_dir() -> Path:
    """Return platform-appropriate persistent data directory outside the codebase with local fallback."""
    # 1. Check if explicitly passed via environment variable
    custom_dir = os.environ.get("MEMORYOS_DATA_DIR")
    if custom_dir:
        target = Path(custom_dir)
        try:
            target.mkdir(parents=True, exist_ok=True)
            return target
        except OSError:
            pass

    # 2. Try standard APPDATA directory on Windows
    appdata = os.environ.get("APPDATA")
    if appdata:
        try:
            target = Path(appdata) / "MemoryOS"
            target.mkdir(parents=True, exist_ok=True)
            return target
        except (PermissionError, OSError):
            pass

    # 3. Try user home directory ~/.memoryos
    try:
        target = Path.home() / ".memoryos"
        target.mkdir(parents=True, exist_ok=True)
        return target
    except (PermissionError, OSError):
        pass

    # 4. Safe fallback inside workspace data/ directory (gitignored)
    fallback = Path.cwd() / "data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


DATA_DIR = get_default_data_dir()
DB_PATH = DATA_DIR / "memoryos.db"
TOKEN_FILE = DATA_DIR / "token.txt"


def get_or_create_api_token() -> str:
    """Retrieve existing API token or create a secure persistent random token on first run."""
    # 1. Environment variable override
    env_token = os.environ.get("MEMORYOS_API_TOKEN")
    if env_token:
        return env_token.strip()

    # 2. Check token file in DATA_DIR
    if TOKEN_FILE.exists():
        try:
            token = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if token:
                return token
        except Exception:
            pass

    # 3. Generate new 32-byte secure hex token
    new_token = secrets.token_hex(24)
    try:
        TOKEN_FILE.write_text(new_token, encoding="utf-8")
    except Exception as e:
        print(f"[Warning] Could not write token file {TOKEN_FILE}: {e}")

    return new_token


API_TOKEN = get_or_create_api_token()

# Host & Port settings
HOST = os.environ.get("MEMORYOS_HOST", "127.0.0.1")
PORT = int(os.environ.get("MEMORYOS_PORT", "8000"))

# Default domain exclusion blocklist (never log content or typed inputs)
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
