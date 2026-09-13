"""Regression: /health tells the truth about the provider."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import MakeClient
from tests.framework.client import TriageClient
from tests.framework.faults import FaultToggler

pytestmark = pytest.mark.regression


def test_llm_status_is_unknown_before_the_first_call(
    client: TriageClient, fresh_state: None
) -> None:
    health = client.health()

    assert health.status == "ok"
    assert health.llm.status == "unknown"
    assert health.llm.last_success_at is None


def test_health_follows_the_most_recent_outcome(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    faults.assert_off("llm_timeout")
    client.triage(ticket)
    assert client.health().llm.status == "ok"

    with faults.enabled("llm_timeout"):
        client.triage(ticket)
        degraded = client.health()

    assert degraded.status == "degraded"
    assert degraded.llm.status == "degraded"
    assert degraded.llm.last_error == "llm_timeout"
    assert degraded.llm.consecutive_failures >= 1

    client.triage(ticket)
    recovered = client.health()
    assert recovered.status == "ok"
    assert recovered.llm.consecutive_failures == 0
    assert recovered.llm.last_error is None


def test_probe_reports_an_unreachable_provider(client: TriageClient, faults: FaultToggler) -> None:
    faults.assert_off("llm_timeout")
    assert client.health(probe=True).llm.status == "ok"

    with faults.enabled("llm_timeout"):
        health = client.health(probe=True)

    assert health.status == "degraded"
    assert health.llm.status == "unreachable"
    assert health.llm.last_error == "llm_timeout"
    assert health.llm.probe_latency_ms is not None and health.llm.probe_latency_ms > 0
    assert health.faults_active == ["llm_timeout"]


def test_quota_fault_marks_the_budget_exhausted(client: TriageClient) -> None:
    assert not client.health().token_budget.exhausted

    health = client.health(faults=["quota_exceeded"])

    assert health.status == "degraded"
    assert health.llm.status == "quota_exceeded"
    assert health.token_budget.exhausted
    assert health.token_budget.remaining == 0
    assert not client.health().token_budget.exhausted


def test_a_really_spent_budget_stops_triage(
    make_client: MakeClient, fresh_state: None, ticket: dict[str, Any]
) -> None:
    """Not the fault: the actual budget. One call is allowed to overspend a tiny budget;
    the next is refused."""
    client = make_client(token_budget=50)

    first = client.triage(ticket)
    second = client.triage_raw(ticket)
    health = client.health()

    assert first.source == "llm"
    assert second.status_code == 503
    assert health.llm.status == "quota_exceeded"
    assert health.token_budget.spent >= 50
