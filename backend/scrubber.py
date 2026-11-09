"""
MemoryOS Secret & Credential Scrubber.
Redacts API keys, tokens, credit card numbers, passwords, and sensitive PII
before any event or chunk is stored in the database.
"""

import re
from typing import Optional, Set
from urllib.parse import urlparse

# Regular expressions for sensitive credentials (ordered from most specific to generic)
PATTERNS = [
    # Anthropic API Keys (checked before OpenAI since both start with sk-)
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}", re.IGNORECASE), "[REDACTED_ANTHROPIC_KEY]"),
    # OpenAI API Keys
    (re.compile(r"sk-(?!ant-)[A-Za-z0-9_-]{20,}", re.IGNORECASE), "[REDACTED_OPENAI_KEY]"),
    # AWS Access Key IDs
    (re.compile(r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    # GitHub Tokens
    (re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,255}\b"), "[REDACTED_GITHUB_PAT]"),
    # JWT Tokens (header.payload.signature)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED_JWT]"),
    # Private Key blocks
    (re.compile(r"-----BEGIN (RSA|EC|DSA|OPENSSH|PRIVATE) KEY-----[\s\S]*?-----END \1 KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    # Credit Card numbers (13-19 digits with optional spaces or hyphens)
    (re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b|\b3[47]\d{13}\b"), "[REDACTED_CARD_NUMBER]"),
    # US Social Security Number
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    # Generic passwords in URL params or key-value structures
    (re.compile(r"(?i)(password|passwd|pwd|secret|api_key|apikey|access_token|auth_token)\s*[:=]\s*['\"]?([^\s'\";&]{4,})['\"]?"), r"\1=[REDACTED]"),
    # OTP / 2FA verification codes
    (re.compile(r"(?i)\b(otp|verification\s*code|security\s*code)\b[\s:=]+([0-9]{4,8})\b"), r"\1=[REDACTED_OTP]"),
]


def scrub_text(text: Optional[str]) -> str:
    """Scrub sensitive information from text string."""
    if not text:
        return ""

    scrubbed = text
    for pattern, replacement in PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)

    return scrubbed


def extract_domain(url: str) -> str:
    """Safely extract lowercase domain name from URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return (parsed.netloc or "").split(":")[0].lower()
    except Exception:
        return ""


def is_domain_blocked(url: str, custom_blocklist: Optional[Set[str]] = None) -> bool:
    """Check if the given URL belongs to a blocked domain or banking/auth service."""
    domain = extract_domain(url)
    if not domain:
        return False

    if custom_blocklist and domain in custom_blocklist:
        return True

    # Generic financial and banking keywords in domain
    sensitive_keywords = ["bank", "chase", "paypal", "fidelity", "wellsfargo", "login.live", "accounts.google"]
    return any(keyword in domain for keyword in sensitive_keywords)
