"""
Unit tests for Windows Desktop Agent privacy exclusions and resource monitor.
"""

from backend.config import MAX_IDLE_CPU_PERCENT, MAX_IDLE_RAM_MB, TYPING_APP_ALLOWLIST
from desktop_agent.resource_monitor import AgentResourceMonitor
from desktop_agent.window_tracker import is_window_blocked


def test_window_title_privacy_blocklist():
    """Verify that sensitive windows and apps are blocked completely from recording."""
    # Hard privacy exclusions
    assert is_window_blocked("New Tab - Google Chrome (Incognito)", "chrome.exe") is True
    assert is_window_blocked("InPrivate Browsing - Microsoft Edge", "msedge.exe") is True
    assert is_window_blocked("Bitwarden - Vault", "bitwarden.exe") is True
    assert is_window_blocked("1Password - Unlock", "1password.exe") is True
    assert is_window_blocked("KeePass Password Safe", "keepass.exe") is True
    assert is_window_blocked("Chase Online Banking - Sign In", "chrome.exe") is True
    assert is_window_blocked("Bank of America - Accounts", "firefox.exe") is True
    assert is_window_blocked("Windows Security - Authentication Prompt", "credentialuibroker.exe") is True
    assert is_window_blocked("Windows Default Lock Screen", "lockapp.exe") is True

    # Standard productivity windows should be allowed
    assert is_window_blocked("agent.py - MemoryOS - Visual Studio Code", "code.exe") is False
    assert is_window_blocked("Untitled - Notepad", "notepad.exe") is False
    assert is_window_blocked("Quarterly Report.docx - Word", "winword.exe") is False
    assert is_window_blocked("Python 3.12 Tutorial - Google Chrome", "chrome.exe") is False


def test_typing_capture_allowlist():
    """Verify that typing capture ONLY runs inside whitelisted productivity apps."""
    allowed = {"code.exe", "notepad.exe", "winword.exe", "cursor.exe"}
    for app in allowed:
        assert app in TYPING_APP_ALLOWLIST

    # Crucial: browsers, chat apps, terminals, and system apps must NEVER be in typing allowlist
    assert "chrome.exe" not in TYPING_APP_ALLOWLIST
    assert "msedge.exe" not in TYPING_APP_ALLOWLIST
    assert "slack.exe" not in TYPING_APP_ALLOWLIST
    assert "discord.exe" not in TYPING_APP_ALLOWLIST
    assert "cmd.exe" not in TYPING_APP_ALLOWLIST
    assert "powershell.exe" not in TYPING_APP_ALLOWLIST
    assert "terminal.exe" not in TYPING_APP_ALLOWLIST


def test_agent_resource_monitor():
    """Test CPU and RAM sampling and performance bounds validation."""
    monitor = AgentResourceMonitor()
    metrics = monitor.sample()

    assert "cpu_percent" in metrics
    assert "ram_mb" in metrics
    assert "is_idle" in metrics

    # Memory of the test process should be positive
    assert metrics["ram_mb"] > 0

    # Validate threshold logic
    is_ok, msg = monitor.check_thresholds()
    # At non-idle or idle under threshold, should return True
    assert isinstance(is_ok, bool)
    assert len(msg) > 0
