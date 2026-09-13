"""The provider interface and the errors the app knows how to handle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class ProviderError(Exception):
    """Base class for provider failures. `reason` is a short machine-readable label."""

    reason = "llm_error"


class ProviderTimeout(ProviderError):
    reason = "llm_timeout"


class ProviderRateLimited(ProviderError):
    reason = "llm_rate_limit"


class ProviderUnavailable(ProviderError):
    reason = "llm_unavailable"


class LLMProvider(Protocol):
    """What the app needs from an LLM. Implementations must be safe to call concurrently."""

    name: str
    model: str

    async def complete(self, system: str, user: str) -> LLMResult:
        """Return the model's text for one system + user prompt pair."""
        ...

    async def ping(self) -> None:
        """Cheaply verify the provider is reachable and authenticated. Raise on failure."""
        ...
