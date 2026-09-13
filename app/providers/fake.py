"""A deterministic offline provider that behaves like a well-behaved model."""

from __future__ import annotations

import json
import re

from app.heuristics import keyword_category, keyword_priority
from app.providers.base import LLMResult

TICKET_BLOCK_RE = re.compile(
    r"Title:\s*(?P<title>.*?)\nAsset:\s*(?P<asset>.*?)\nDescription:\s*(?P<description>.*)",
    re.DOTALL,
)


def estimate_tokens(text: str) -> int:
    """Rough token estimate so budget tracking works offline."""
    return max(1, len(text) // 4)


class FakeProvider:
    name = "fake"
    model = "fake-triage-v1"

    async def complete(self, system: str, user: str) -> LLMResult:
        match = TICKET_BLOCK_RE.search(user)
        if match:
            title = match.group("title").strip()
            asset = match.group("asset").strip()
            description = match.group("description").strip()
        else:
            title, asset, description = "Unrecognised prompt", "unknown", user

        text = f"{title}\n{description}"
        first_sentence = re.split(r"(?<=[.!?])\s", description, maxsplit=1)[0]
        summary = f"{title.rstrip('.')} on {asset}: {first_sentence}"
        output = json.dumps(
            {
                "priority": keyword_priority(text),
                "category": keyword_category(text),
                "summary": summary,
            }
        )
        return LLMResult(
            text=output,
            input_tokens=estimate_tokens(system + user),
            output_tokens=estimate_tokens(output),
            model=self.model,
        )

    async def ping(self) -> None:
        return None
