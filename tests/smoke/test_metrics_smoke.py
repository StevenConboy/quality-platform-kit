"""Smoke: /metrics moves when the app does work."""

from __future__ import annotations

from typing import Any

import pytest

from tests.framework.client import TriageClient

pytestmark = pytest.mark.smoke


def test_metrics_count_requests_and_tokens(client: TriageClient, ticket: dict[str, Any]) -> None:
    before = client.metrics()
    client.triage(ticket)
    after = client.metrics()

    triage_before = before.requests_by_endpoint.get("/triage", 0)
    assert after.requests_by_endpoint["/triage"] == triage_before + 1
    assert after.llm_calls.succeeded == before.llm_calls.succeeded + 1
    assert after.tokens.spent > before.tokens.spent


def test_latency_percentiles_are_ordered(client: TriageClient, ticket: dict[str, Any]) -> None:
    client.triage(ticket)
    client.triage(ticket)
    latency = client.metrics().latency_by_endpoint["/triage"]

    assert latency.count >= 2
    assert latency.p50_ms <= latency.p95_ms <= latency.p99_ms <= latency.max_ms
