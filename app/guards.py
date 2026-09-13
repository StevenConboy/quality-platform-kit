"""Output guards applied to every summary before it leaves the app."""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Matches common phone shapes: +1 555-010-9999, (555) 010-9999, 555.010.9999, 555 0100 etc.
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)?\d{3}[\s.-]?\d{4}(?!\w)"
)

MAX_SUMMARY_CHARS = 240


def find_pii(text: str) -> list[str]:
    """Return every email address and phone number found in the text."""
    return EMAIL_RE.findall(text) + [m.strip() for m in PHONE_RE.findall(text)]


def redact_pii(text: str) -> tuple[str, bool]:
    """Replace emails and phone numbers with placeholders. Returns (text, changed)."""
    redacted = EMAIL_RE.sub("[redacted-email]", text)
    redacted = PHONE_RE.sub("[redacted-phone]", redacted)
    return redacted, redacted != text


def one_line(text: str) -> str:
    """Collapse a summary to a single trimmed line of bounded length."""
    line = " ".join(text.split())
    if len(line) > MAX_SUMMARY_CHARS:
        line = line[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    return line
