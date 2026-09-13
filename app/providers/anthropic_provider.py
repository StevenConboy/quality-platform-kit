"""Provider backed by the Anthropic Python SDK."""

from __future__ import annotations

import anthropic

from app.providers.base import (
    LLMResult,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)

# Enough room for a short JSON object plus whatever adaptive thinking the model decides on.
MAX_OUTPUT_TOKENS = 2048


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, timeout_seconds: float, api_key: str | None = None) -> None:
        self.model = model
        # max_retries=0: the app owns its retry and fallback policy, so a 429 or timeout
        # must surface immediately rather than being retried silently by the SDK.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout_seconds, max_retries=0
        )

    async def complete(self, system: str, user: str) -> LLMResult:
        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.RateLimitError as exc:
            raise ProviderRateLimited(str(exc)) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeout(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderUnavailable(f"HTTP {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailable(f"connection error: {exc}") from exc

        if response.stop_reason == "refusal":
            raise ProviderUnavailable("model refused the request")

        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResult(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )

    async def ping(self) -> None:
        """count_tokens is free and exercises auth plus reachability."""
        try:
            await self._client.messages.count_tokens(
                model=self.model, messages=[{"role": "user", "content": "ping"}]
            )
        except anthropic.RateLimitError as exc:
            raise ProviderRateLimited(str(exc)) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeout(str(exc)) from exc
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise ProviderUnavailable(str(exc)) from exc
