"""Keyword heuristics used by the fallback path and by the FakeProvider.

These are deliberately simple. They exist so the app can still return a sensible
priority and category when the LLM is unavailable.
"""

from __future__ import annotations

from app.models import Category, Priority

CATEGORY_KEYWORDS: dict[Category, tuple[str, ...]] = {
    "electrical": ("breaker", "electrical", "outlet", "wiring", "power", "voltage", "spark"),
    "plumbing": ("leak", "pipe", "water", "drain", "toilet", "faucet", "flood"),
    "hvac": ("hvac", "air conditioning", "heating", "thermostat", "furnace", "vent", "chiller"),
    "structural": ("crack", "ceiling", "roof", "wall", "foundation", "door", "window"),
    "safety": ("fire", "smoke", "alarm", "injur", "hazard", "gas", "exit sign", "sprinkler"),
    "it": ("network", "server", "wifi", "printer", "laptop", "badge reader", "camera"),
}

CRITICAL_WORDS: tuple[str, ...] = (
    "fire",
    "smoke",
    "gas leak",
    "gas smell",
    "gas odour",
    "gas odor",
    "smell of gas",
    "injur",
    "flood",
    "sparking",
)
HIGH_WORDS: tuple[str, ...] = ("outage", "no power", "leak", "burning", "not working", "down")
LOW_WORDS: tuple[str, ...] = ("cosmetic", "paint", "scratch", "minor", "when convenient")


def keyword_category(text: str) -> Category:
    lowered = text.lower()
    best: Category = "general"
    best_hits = 0
    for category, words in CATEGORY_KEYWORDS.items():
        hits = sum(1 for word in words if word in lowered)
        if hits > best_hits:
            best, best_hits = category, hits
    return best


def keyword_priority(text: str) -> Priority:
    lowered = text.lower()
    if any(word in lowered for word in CRITICAL_WORDS):
        return "critical"
    if any(word in lowered for word in HIGH_WORDS):
        return "high"
    if any(word in lowered for word in LOW_WORDS):
        return "low"
    return "medium"


def fallback_priority(text: str) -> Priority:
    """Priority to use when the LLM is unavailable.

    Never returns "low": while degraded we would rather over-prioritise than lose a
    ticket that only the LLM would have recognised as urgent.
    """
    priority = keyword_priority(text)
    return "medium" if priority == "low" else priority
