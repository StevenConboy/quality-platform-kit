"""Regression: /metrics counts what actually happened."""

from __future__ import annotations

from typing import Any

import pytest

from tests.framework.budget import TokenTracker
from tests.framework.client import TriageClient
from tests.framework.faults import FaultToggler

pytestmark = pytest.mark.regression


def test_status_counts_include_errors(client: TriageClient, ticket: dict[str, Any]) -> None:
    before = client.metrics().requests_by_status
    client.triage(ticket)
    client.triage_raw(ticket, faults=["quota_exceeded"])
    client.triage_raw(ticket, faults=["not_a_fault"])
    after = client.metrics().requests_by_status

    assert after["200"] >= before.get("200", 0) + 1
    assert after["503"] == before.get("503", 0) + 1
    assert after["400"] == before.get("400", 0) + 1


def test_llm_call_outcomes_are_counted(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    faults.assert_off("llm_rate_limit")
    before = client.metrics().llm_calls

    client.triage(ticket)
    with faults.enabled("llm_rate_limit"):
        client.triage(ticket)
    after = client.metrics().llm_calls

    assert after.total == before.total + 2
    assert after.succeeded == before.succeeded + 1
    assert after.failed == before.failed + 1
    assert after.fallbacks == before.fallbacks + 1


def test_faults_injected_are_counted_per_name(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    faults.assert_off("llm_garbage")
    before = client.metrics().faults_injected.get("llm_garbage", 0)

    with faults.enabled("llm_garbage"):
        client.triage(ticket)
        client.triage(ticket)

    assert client.metrics().faults_injected["llm_garbage"] == before + 2


def test_token_spend_is_tracked(
    client: TriageClient, ticket: dict[str, Any], token_tracker: TokenTracker
) -> None:
    client.triage(ticket)
    metrics = client.metrics()

    assert token_tracker.spent > 0
    assert metrics.tokens.remaining == metrics.tokens.limit - metrics.tokens.spent
    by_direction = metrics.tokens_by_direction
    assert by_direction.input_tokens + by_direction.output_tokens == metrics.tokens.spent


def test_a_refused_llm_call_spends_nothing(
    client: TriageClient,
    faults: FaultToggler,
    ticket: dict[str, Any],
    token_tracker: TokenTracker,
) -> None:
    faults.assert_off("llm_rate_limit")

    with faults.enabled("llm_rate_limit"):
        client.triage(ticket)

    assert token_tracker.spent == 0
    token_tracker.assert_under(0)


@pytest.mark.slow
def test_latency_percentiles_reflect_slow_requests(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    faults.assert_off("slow_response")

    with faults.enabled("slow_response"):
        client.triage(ticket)

    assert client.metrics().latency_by_endpoint["/triage"].max_ms >= 250
