"""Runtime settings, read once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ProviderName = Literal["fake", "anthropic"]


@dataclass(frozen=True)
class Settings:
    provider: ProviderName = "fake"
    model: str = "claude-opus-5"
    llm_timeout_seconds: float = 8.0
    token_budget: int = 200_000
    faults_file: Path = Path("faults.json")
    slow_response_seconds: float = 3.0

    @classmethod
    def from_env(cls) -> Settings:
        provider = os.environ.get("TRIAGE_PROVIDER", "fake").lower()
        if provider not in ("fake", "anthropic"):
            raise ValueError(f"TRIAGE_PROVIDER must be 'fake' or 'anthropic', got {provider!r}")
        return cls(
            provider=provider,  # type: ignore[arg-type]  # validated above
            model=os.environ.get("TRIAGE_MODEL", cls.model),
            llm_timeout_seconds=float(
                os.environ.get("TRIAGE_LLM_TIMEOUT_SECONDS", cls.llm_timeout_seconds)
            ),
            token_budget=int(os.environ.get("TRIAGE_TOKEN_BUDGET", cls.token_budget)),
            faults_file=Path(os.environ.get("TRIAGE_FAULTS_FILE", cls.faults_file)),
            slow_response_seconds=float(
                os.environ.get("TRIAGE_SLOW_RESPONSE_SECONDS", cls.slow_response_seconds)
            ),
        )
