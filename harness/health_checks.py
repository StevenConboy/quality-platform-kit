"""Probe the LLM provider through the app and report reachability and latency.

Usable from tests (see test_health.py) or on its own:

    uv run python -m harness.health_checks                      # in-process app
    uv run python -m harness.health_checks http://localhost:8000
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from tests.framework.client import TriageClient


@dataclass(frozen=True)
class ProbeResult:
    reachable: bool
    llm_status: str
    latency_ms: float
    error: str | None


@dataclass(frozen=True)
class HealthSummary:
    provider: str
    model: str
    probes: int
    reachable: bool
    failures: int
    min_latency_ms: float
    avg_latency_ms: float
    max_latency_ms: float
    errors: list[str]


def probe_once(client: TriageClient, faults: Iterable[str] | None = None) -> ProbeResult:
    health = client.health(probe=True, faults=faults)
    latency = health.llm.probe_latency_ms if health.llm.probe_latency_ms is not None else 0.0
    return ProbeResult(
        reachable=health.llm.status == "ok",
        llm_status=health.llm.status,
        latency_ms=latency,
        error=health.llm.last_error,
    )


def run_probes(client: TriageClient, count: int) -> HealthSummary:
    results = [probe_once(client) for _ in range(count)]
    info = client.health()
    latencies = [r.latency_ms for r in results]
    return HealthSummary(
        provider=info.llm.provider,
        model=info.llm.model,
        probes=count,
        reachable=all(r.reachable for r in results),
        failures=sum(1 for r in results if not r.reachable),
        min_latency_ms=min(latencies),
        avg_latency_ms=sum(latencies) / len(latencies),
        max_latency_ms=max(latencies),
        errors=[r.error for r in results if r.error],
    )


def main(argv: list[str]) -> int:
    from fastapi.testclient import TestClient

    from app.main import create_app

    if argv:
        import httpx2

        http: httpx2.Client = httpx2.Client(base_url=argv[0], timeout=30.0)
    else:
        http = TestClient(create_app())
    summary = run_probes(TriageClient(http), count=3)
    print(json.dumps(asdict(summary), indent=2))
    return 0 if summary.reachable else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
