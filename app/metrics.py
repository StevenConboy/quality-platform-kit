"""In-memory request metrics: counts, latency percentiles, LLM call outcomes."""

from __future__ import annotations

import threading
from collections import Counter, defaultdict, deque

from app.budget import TokenBudget
from app.models import LatencyStats, LLMCallStats, MetricsResponse

MAX_SAMPLES = 5_000


def percentile(sorted_samples: list[float], fraction: float) -> float:
    """Nearest-rank percentile. Plain and good enough for a demo service."""
    if not sorted_samples:
        return 0.0
    index = round(fraction * (len(sorted_samples) - 1))
    return sorted_samples[index]


def latency_stats(samples: deque[float]) -> LatencyStats:
    ordered = sorted(samples)
    return LatencyStats(
        count=len(ordered),
        p50_ms=percentile(ordered, 0.50),
        p95_ms=percentile(ordered, 0.95),
        p99_ms=percentile(ordered, 0.99),
        max_ms=ordered[-1] if ordered else 0.0,
    )


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_endpoint: Counter[str] = Counter()
        self._by_status: Counter[str] = Counter()
        self._latency: deque[float] = deque(maxlen=MAX_SAMPLES)
        self._latency_by_endpoint: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=MAX_SAMPLES)
        )
        self._llm_total = 0
        self._llm_succeeded = 0
        self._llm_failed = 0
        self._fallbacks = 0

    def record_request(self, endpoint: str, status_code: int, latency_ms: float) -> None:
        with self._lock:
            self._by_endpoint[endpoint] += 1
            self._by_status[str(status_code)] += 1
            self._latency.append(latency_ms)
            self._latency_by_endpoint[endpoint].append(latency_ms)

    def record_llm_call(self, succeeded: bool) -> None:
        with self._lock:
            self._llm_total += 1
            if succeeded:
                self._llm_succeeded += 1
            else:
                self._llm_failed += 1

    def record_fallback(self) -> None:
        with self._lock:
            self._fallbacks += 1

    def reset(self) -> None:
        with self._lock:
            self.__init__()  # type: ignore[misc]

    def snapshot(self, budget: TokenBudget) -> MetricsResponse:
        with self._lock:
            return MetricsResponse(
                requests_total=sum(self._by_endpoint.values()),
                requests_by_endpoint=dict(self._by_endpoint),
                requests_by_status=dict(self._by_status),
                latency=latency_stats(self._latency),
                latency_by_endpoint={
                    endpoint: latency_stats(samples)
                    for endpoint, samples in self._latency_by_endpoint.items()
                },
                llm_calls=LLMCallStats(
                    total=self._llm_total,
                    succeeded=self._llm_succeeded,
                    failed=self._llm_failed,
                    fallbacks=self._fallbacks,
                ),
                tokens=budget.status(),
                tokens_by_direction=budget.by_direction(),
            )
