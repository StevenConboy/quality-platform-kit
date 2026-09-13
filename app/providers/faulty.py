"""A provider wrapper that misbehaves on demand.

This is the fault injection layer for everything LLM-shaped. It sits between the
app and the real provider so the app's handling of bad providers can be exercised
without a bad provider.
"""

from __future__ import annotations

import asyncio
import json

from app.guards import find_pii
from app.providers.base import LLMProvider, LLMResult, ProviderRateLimited

INJECTOR_MODEL = "fault-injector"

GARBAGE_OUTPUT = '{"priority": "high", "category": "electrical", "summary": "Breaker'

HALLUCINATED_OUTPUT = json.dumps(
    {
        "priority": "low",
        "category": "general",
        "summary": (
            "Routine cosmetic touch-up requested; the asset is fully operational "
            "and no repair is required."
        ),
    }
)


class FaultInjectingProvider:
    def __init__(self, inner: LLMProvider, faults: frozenset[str], timeout_seconds: float) -> None:
        self.inner = inner
        self.faults = faults
        self.timeout_seconds = timeout_seconds
        self.name = inner.name
        self.model = inner.model

    async def complete(self, system: str, user: str) -> LLMResult:
        if "llm_timeout" in self.faults:
            # The app enforces the timeout with asyncio.wait_for, which cancels this sleep.
            await asyncio.sleep(self.timeout_seconds + 1.0)
        if "llm_rate_limit" in self.faults:
            raise ProviderRateLimited("injected 429: rate limit exceeded")
        if "llm_garbage" in self.faults:
            return LLMResult(GARBAGE_OUTPUT, 0, 0, INJECTOR_MODEL)
        if "llm_hallucinate" in self.faults:
            return LLMResult(HALLUCINATED_OUTPUT, 0, 0, INJECTOR_MODEL)

        result = await self.inner.complete(system, user)

        if "pii_leak" in self.faults:
            return _leak_pii(result, user)
        return result

    async def ping(self) -> None:
        if "llm_timeout" in self.faults:
            await asyncio.sleep(self.timeout_seconds + 1.0)
        if "llm_rate_limit" in self.faults:
            raise ProviderRateLimited("injected 429: rate limit exceeded")
        await self.inner.ping()


def _leak_pii(result: LLMResult, user_prompt: str) -> LLMResult:
    """Append any email or phone number found in the prompt to the summary."""
    leaked = find_pii(user_prompt)
    if not leaked:
        return result
    suffix = " Contact: " + ", ".join(leaked) + "."
    try:
        payload = json.loads(result.text)
    except json.JSONDecodeError:
        return LLMResult(
            result.text + suffix, result.input_tokens, result.output_tokens, result.model
        )
    if isinstance(payload, dict):
        payload["summary"] = str(payload.get("summary", "")) + suffix
        return LLMResult(
            json.dumps(payload), result.input_tokens, result.output_tokens, result.model
        )
    return result
