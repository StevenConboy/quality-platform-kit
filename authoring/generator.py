"""Draft a test module with the Anthropic SDK from an editable prompt."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import anthropic

DEFAULT_MODEL = "claude-opus-5"
MAX_OUTPUT_TOKENS = 16000

FENCE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class Draft:
    source: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None


def render_prompt(template: str, **values: str) -> str:
    """Fill {{placeholders}}. Unknown placeholders are left alone so a typo is visible."""
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def build_user_message(
    endpoint_text: str,
    conventions: str,
    example_path: Path,
    example_source: str,
    existing_tests: list[str],
    module_name: str,
) -> str:
    existing = "\n".join(f"- {name}" for name in existing_tests) or "- (none)"
    return (
        f"# Endpoint\n\n{endpoint_text}\n\n"
        f"# Framework conventions (tests/README.md)\n\n{conventions}\n\n"
        f"# Style example ({example_path.as_posix()})\n\n```python\n{example_source}\n```\n\n"
        f"# Existing tests, with coverage fingerprints (do not duplicate)\n\n{existing}\n\n"
        f"# Output\n\nThe module will be saved as `{module_name}`."
    )


def extract_code(text: str) -> str:
    """Take the first fenced Python block; fall back to the whole text."""
    match = FENCE_RE.search(text)
    return (match.group(1) if match else text).strip() + "\n"


class Generator:
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None) -> None:
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key, timeout=300.0, max_retries=2)

    def draft(self, system_prompt: str, user_message: str) -> Draft:
        # Streaming so a long module cannot hit an HTTP timeout; the final message is
        # all we need.
        with self._client.messages.stream(
            model=self.model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            raise RuntimeError("the model declined to draft tests for this endpoint")
        text = "".join(block.text for block in message.content if block.type == "text")
        return Draft(
            source=extract_code(text),
            model=message.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            stop_reason=message.stop_reason,
        )
