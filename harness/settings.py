"""Typed view of harness/config.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

JudgeMode = Literal["auto", "llm", "keyword"]

REPO_ROOT = Path(__file__).resolve().parent.parent
# HARNESS_CONFIG points at an alternative config file, e.g. a tighter budget for CI.
DEFAULT_CONFIG = Path(
    os.environ.get("HARNESS_CONFIG", Path(__file__).resolve().parent / "config.yaml")
)


@dataclass(frozen=True)
class HarnessSettings:
    run_token_budget: int
    per_test_token_budget: int
    probe_count: int
    max_probe_latency_ms: float
    judge_mode: JudgeMode
    judge_model: str
    rubric_path: Path
    min_overlap: float
    min_score: int
    payloads_path: Path
    report_template: Path
    report_output: Path

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG) -> HarnessSettings:
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        budget = raw["token_budget"]
        health = raw["health"]
        grounded = raw["groundedness"]
        judge_mode = grounded.get("judge", "auto")
        if judge_mode not in ("auto", "llm", "keyword"):
            raise ValueError(f"groundedness.judge must be auto, llm or keyword; got {judge_mode!r}")
        return cls(
            run_token_budget=int(budget["run"]),
            per_test_token_budget=int(budget["per_test"]),
            probe_count=int(health["probe_count"]),
            max_probe_latency_ms=float(health["max_probe_latency_ms"]),
            judge_mode=judge_mode,
            judge_model=str(grounded["model"]),
            rubric_path=REPO_ROOT / grounded["rubric"],
            min_overlap=float(grounded["min_overlap"]),
            min_score=int(grounded["min_score"]),
            payloads_path=REPO_ROOT / raw["adversarial"]["payloads"],
            report_template=REPO_ROOT / raw["report"]["template"],
            # HARNESS_REPORT_OUTPUT lets a second run in the same job (the quarantine
            # step in CI) write elsewhere instead of overwriting the real report.
            report_output=Path(
                os.environ.get("HARNESS_REPORT_OUTPUT", REPO_ROOT / raw["report"]["output"])
            ),
        )
