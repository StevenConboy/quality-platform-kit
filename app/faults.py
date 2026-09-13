"""Fault injection configuration.

Faults come from two places:
  1. faults.json, loaded at startup and editable at runtime via /faults
  2. the X-Fault request header, which overrides the file for one request

The header format is a comma-separated list of fault names. A name enables the fault,
"-name" disables it, and the single word "none" clears every fault for that request.
"""

from __future__ import annotations

import json
from pathlib import Path

FAULT_DESCRIPTIONS: dict[str, str] = {
    "llm_timeout": "provider sleeps past the app's LLM timeout",
    "llm_rate_limit": "provider raises a 429 rate-limit error",
    "llm_garbage": "provider returns malformed JSON",
    "llm_hallucinate": "provider returns a plausible summary that contradicts the ticket",
    "quota_exceeded": "token budget is reported as exhausted",
    "slow_response": "adds fixed latency before the request is handled",
    "pii_leak": "summary echoes an email or phone number from the input",
}

ALL_FAULTS: frozenset[str] = frozenset(FAULT_DESCRIPTIONS)

# Faults that change how the provider behaves, as opposed to the app around it.
PROVIDER_FAULTS: frozenset[str] = frozenset(
    {"llm_timeout", "llm_rate_limit", "llm_garbage", "llm_hallucinate", "pii_leak"}
)


class UnknownFault(ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(f"unknown fault {name!r}; known faults: {', '.join(sorted(ALL_FAULTS))}")
        self.name = name


class FaultConfig:
    """Holds the set of faults enabled globally, seeded from faults.json."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._enabled: set[str] = set()
        self.reload()

    def reload(self) -> None:
        """Re-read the file. A missing file means no faults enabled."""
        self._enabled = set()
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        flags = data.get("faults", data)
        for name, enabled in flags.items():
            if name not in ALL_FAULTS:
                raise UnknownFault(name)
            if enabled:
                self._enabled.add(name)

    @property
    def enabled(self) -> frozenset[str]:
        return frozenset(self._enabled)

    def set(self, name: str, enabled: bool) -> None:
        if name not in ALL_FAULTS:
            raise UnknownFault(name)
        if enabled:
            self._enabled.add(name)
        else:
            self._enabled.discard(name)

    def clear(self) -> None:
        self._enabled.clear()

    def as_dict(self) -> dict[str, bool]:
        return {name: name in self._enabled for name in sorted(ALL_FAULTS)}


def resolve_faults(globally_enabled: frozenset[str], header: str | None) -> frozenset[str]:
    """Combine the global config with the per-request X-Fault header."""
    active = set(globally_enabled)
    if header is None or not header.strip():
        return frozenset(active)

    for raw in header.split(","):
        token = raw.strip()
        if not token:
            continue
        if token == "none":
            active.clear()
            continue
        disable = token.startswith("-")
        name = token[1:] if disable else token
        if name not in ALL_FAULTS:
            raise UnknownFault(name)
        if disable:
            active.discard(name)
        else:
            active.add(name)
    return frozenset(active)
