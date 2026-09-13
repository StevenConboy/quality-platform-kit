"""Output guards applied to every summary before it leaves the app."""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# A run of 7 to 15 digits with at most two separator characters between any two digits.
# Covers 555-010-9999, (555) 010-9999, +1 555.010.9999, +44 20 7946 0958, 5550109999.
# Deliberately broad: a redacted ticket number costs little, a leaked phone number does not.
PHONE_CANDIDATE_RE = re.compile(r"(?<![\w.])\+?\(?\d(?:[\s().-]{0,2}\d){6,14}(?!\w)")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
YEAR_RANGE_RE = re.compile(r"^\d{4}\s?-\s?\d{4}$")

MAX_SUMMARY_CHARS = 240


def looks_like_phone(candidate: str) -> bool:
    """Filter out the digit runs that are clearly something else."""
    stripped = candidate.strip()
    if ISO_DATE_RE.match(stripped) or YEAR_RANGE_RE.match(stripped):
        return False
    return stripped.count(".") < 3  # three or more dots: IP address or version string


def find_pii(text: str) -> list[str]:
    """Return every email address and phone number found in the text."""
    phones = [m.group() for m in PHONE_CANDIDATE_RE.finditer(text) if looks_like_phone(m.group())]
    return EMAIL_RE.findall(text) + phones


def redact_pii(text: str) -> tuple[str, bool]:
    """Replace emails and phone numbers with placeholders. Returns (text, changed)."""
    redacted = EMAIL_RE.sub("[redacted-email]", text)
    redacted = PHONE_CANDIDATE_RE.sub(
        lambda m: "[redacted-phone]" if looks_like_phone(m.group()) else m.group(), redacted
    )
    return redacted, redacted != text


def one_line(text: str) -> str:
    """Collapse a summary to a single trimmed line of bounded length."""
    line = " ".join(text.split())
    if len(line) > MAX_SUMMARY_CHARS:
        line = line[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    return line
