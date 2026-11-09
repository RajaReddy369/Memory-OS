"""
Unit tests for Secret and Credential Scrubber.
"""

from backend.scrubber import extract_domain, is_domain_blocked, scrub_text


def test_scrub_openai_key():
    raw = "My API key is sk-abcdef1234567890abcdef1234567890 for testing."
    scrubbed = scrub_text(raw)
    assert "[REDACTED_OPENAI_KEY]" in scrubbed
    assert "sk-abcdef" not in scrubbed


def test_scrub_anthropic_key():
    raw = "Anthropic token: sk-ant-api03-abcdef1234567890abcdef1234567890"
    scrubbed = scrub_text(raw)
    assert "[REDACTED_ANTHROPIC_KEY]" in scrubbed
    assert "sk-ant" not in scrubbed


def test_scrub_aws_key():
    raw = "AWS credentials: AKIAIOSFODNN7EXAMPLE key"
    scrubbed = scrub_text(raw)
    assert "[REDACTED_AWS_KEY]" in scrubbed
    assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed


def test_scrub_github_token():
    raw = "GitHub token ghp_123456789012345678901234567890123456 used in CI"
    scrubbed = scrub_text(raw)
    assert "[REDACTED_GITHUB_TOKEN]" in scrubbed
    assert "ghp_12345" not in scrubbed


def test_scrub_credit_card():
    raw = "Payment card number is 4532-1234-5678-9012 for the purchase."
    scrubbed = scrub_text(raw)
    assert "[REDACTED_CARD_NUMBER]" in scrubbed
    assert "4532" not in scrubbed


def test_scrub_password_pattern():
    raw = "Config: password=MySecretPassword123! in connection string"
    scrubbed = scrub_text(raw)
    assert "password=[REDACTED]" in scrubbed
    assert "MySecretPassword123!" not in scrubbed


def test_domain_blocking():
    assert is_domain_blocked("https://chase.com/login") is True
    assert is_domain_blocked("https://accounts.google.com/signin") is True
    assert is_domain_blocked("https://paypal.com/checkout") is True
    assert is_domain_blocked("https://github.com/my-repo") is False
    assert is_domain_blocked("https://en.wikipedia.org/wiki/Main_Page") is False


def test_extract_domain():
    assert extract_domain("https://news.ycombinator.com/item?id=123") == "news.ycombinator.com"
    assert extract_domain("http://localhost:8000/api/health") == "localhost"

