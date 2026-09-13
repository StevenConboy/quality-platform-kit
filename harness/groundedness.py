"""Groundedness check: does the summary contradict the ticket?

Two methods behind one interface:
  - an LLM judge (Anthropic SDK) scoring against the rubric in groundedness_rubric.md
  - a keyword-overlap fallback that needs no network

The judge is used when configured and reachable; anything else falls back to keywords and
says so in the verdict, so a report never silently mixes the two.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import anthropic

from harness.settings import HarnessSettings

Method = Literal["llm", "keyword"]

STOPWORDS = frozenset(
    [
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from",
        "has", "have", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this",
        "to", "was", "were", "will", "with", "since", "after", "before", "every", "few",
        "not", "no", "there", "their", "they", "into", "onto", "over", "under", "near",
        "about", "when", "where", "which", "who", "how", "all", "any", "some", "very",
        "just", "also", "than", "then", "them", "our", "your", "you", "we", "he", "she",
        "his", "her",
    ]
)  # fmt: skip

# Phrases that claim there is nothing wrong. If one appears in the summary but not in the
# ticket, the summary is contradicting the ticket.
ALL_CLEAR_CUES: tuple[str, ...] = (
    "no action",
    "no repair",
    "no issue",
    "no fault",
    "nothing wrong",
    "fully operational",
    "working normally",
    "operating normally",
    "resolved",
    "no urgency",
)

JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Verdict:
    grounded: bool
    method: Method
    score: float  # 1-5 for the judge, 0-1 overlap for keywords
    rationale: str


@dataclass
class JudgeUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def content_words(text: str) -> set[str]:
    words = set()
    for word in WORD_RE.findall(text.lower()):
        if len(word) < 3 or word in STOPWORDS:
            continue
        words.add(word[:-1] if word.endswith("s") and len(word) > 3 else word)
    return words


def keyword_verdict(ticket_text: str, summary: str, min_overlap: float) -> Verdict:
    summary_words = content_words(summary)
    ticket_words = content_words(ticket_text)
    shared = summary_words & ticket_words
    overlap = len(shared) / len(summary_words) if summary_words else 0.0

    ticket_lower = ticket_text.lower()
    summary_lower = summary.lower()
    cues = [c for c in ALL_CLEAR_CUES if c in summary_lower and c not in ticket_lower]

    if cues:
        return Verdict(False, "keyword", overlap, f"summary claims all clear: {', '.join(cues)}")
    if overlap < min_overlap:
        return Verdict(
            False,
            "keyword",
            overlap,
            f"only {overlap:.0%} of summary words appear in the ticket (need {min_overlap:.0%})",
        )
    return Verdict(True, "keyword", overlap, f"{overlap:.0%} of summary words appear in the ticket")


class GroundednessChecker:
    def __init__(self, settings: HarnessSettings, api_key: str | None = None) -> None:
        self.settings = settings
        self.usage = JudgeUsage()
        self._rubric: str | None = None
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if settings.judge_mode == "llm" and not key:
            raise RuntimeError("groundedness.judge is 'llm' but ANTHROPIC_API_KEY is not set")
        self.use_llm = settings.judge_mode != "keyword" and bool(key)
        self._client = (
            anthropic.Anthropic(api_key=key, timeout=30.0, max_retries=1) if self.use_llm else None
        )

    @property
    def method(self) -> Method:
        return "llm" if self.use_llm else "keyword"

    @property
    def rubric(self) -> str:
        if self._rubric is None:
            self._rubric = Path(self.settings.rubric_path).read_text(encoding="utf-8")
        return self._rubric

    def check(self, ticket: dict[str, Any], summary: str) -> Verdict:
        ticket_text = f"{ticket['title']}\n{ticket['description']}\n{ticket['asset_id']}"
        if self._client is not None:
            try:
                return self._judge(ticket_text, summary)
            except (anthropic.APIError, ValueError) as exc:
                self.usage.failures.append(f"{type(exc).__name__}: {exc}")
        fallback = keyword_verdict(ticket_text, summary, self.settings.min_overlap)
        if self._client is not None:
            return Verdict(
                fallback.grounded,
                fallback.method,
                fallback.score,
                f"judge unavailable, keyword fallback: {fallback.rationale}",
            )
        return fallback

    def _judge(self, ticket_text: str, summary: str) -> Verdict:
        assert self._client is not None
        response = self._client.messages.create(
            model=self.settings.judge_model,
            max_tokens=1024,
            system=self.rubric,
            messages=[
                {
                    "role": "user",
                    "content": f"TICKET:\n{ticket_text}\n\nSUMMARY:\n{summary}",
                }
            ],
        )
        self.usage.calls += 1
        self.usage.input_tokens += response.usage.input_tokens
        self.usage.output_tokens += response.usage.output_tokens
        if response.stop_reason == "refusal":
            raise ValueError("judge refused the request")

        text = "".join(block.text for block in response.content if block.type == "text")
        payload = json.loads(JSON_FENCE_RE.sub("", text.strip()))
        score = int(payload["score"])
        contradiction = bool(payload.get("contradiction", score == 1))
        rationale = str(payload.get("rationale", ""))
        grounded = not contradiction and score >= self.settings.min_score
        return Verdict(grounded, "llm", float(score), rationale)
