from __future__ import annotations

import re

REDACTED = "[REDACTED]"

WEBHOOK_URL_RE = re.compile(
    r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+",
    re.IGNORECASE,
)
MFA_TOKEN_RE = re.compile(r"\bmfa\.[A-Za-z0-9_-]{20,}\b")
DISCORD_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{20,}\b")
BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b", re.IGNORECASE)
PASSWORD_RE = re.compile(r"\b(password|passwd|pwd)\s*[:=]\s*([^\s]+)", re.IGNORECASE)
TOTP_RE = re.compile(
    r"\b(totp(?:\s+secret)?|2fa(?:\s+secret)?|mfa(?:\s+secret)?)\s*[:=]?\s*([A-Z2-7]{16,})\b",
    re.IGNORECASE,
)
KEYWORD_SECRET_RE = re.compile(
    r"(?i)\b(token|password|passwd|pwd|secret|totp|webhook|api[_-]?key|access[_-]?key|client[_-]?secret)\b"
    r"\s*[:=]?\s*\S+"
)

SENSITIVE_PATTERNS = (
    WEBHOOK_URL_RE,
    MFA_TOKEN_RE,
    DISCORD_TOKEN_RE,
    BEARER_RE,
    PASSWORD_RE,
    TOTP_RE,
    KEYWORD_SECRET_RE,
)


def redact_sensitive(text: str | None) -> str:
    """Redact credentials and secrets from arbitrary text.

    Over-redaction is intentional: raw logs stay useful for moderation and
    security work, but Discord tokens, MFA tokens, webhook URLs, passwords and
    TOTP secrets must never be written or exported in the clear.
    """
    if text is None:
        return ""
    redacted = str(text)
    redacted = WEBHOOK_URL_RE.sub(f"https://discord.com/api/webhooks/{REDACTED}", redacted)
    redacted = MFA_TOKEN_RE.sub(REDACTED, redacted)
    redacted = DISCORD_TOKEN_RE.sub(REDACTED, redacted)
    redacted = BEARER_RE.sub(f"Bearer {REDACTED}", redacted)
    redacted = PASSWORD_RE.sub(lambda match: f"{match.group(1)}={REDACTED}", redacted)
    redacted = TOTP_RE.sub(lambda match: f"{match.group(1)} {REDACTED}", redacted)
    redacted = KEYWORD_SECRET_RE.sub(lambda match: f"{match.group(1)} {REDACTED}", redacted)
    return redacted
