"""Regression: how /triage behaves under each injected fault.

Every fault test follows the same three steps:
  1. prove the fault is off and capture healthy behaviour
  2. flip the fault on
  3. assert the app degraded the way app/README.md says it should
"""

from __future__ import annotations

from typing import Any

import pytest

from app.heuristics import keyword_category
from app.models import PRIORITIES, TriageResponse
from tests.framework.client import TriageClient
from tests.framework.faults import FaultToggler
from tests.framework.tickets import COSMETIC, PLUMBING_LEAK, WITH_PII, make_ticket

pytestmark = pytest.mark.regression


def prove_healthy(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any], *names: str
) -> TriageResponse:
    """Step 1 of every fault test: the fault is off and the app answers normally."""
    faults.assert_off(*names)
    baseline = client.triage(ticket)
    assert baseline.faults_applied == []
    assert baseline.source == "llm"
    assert not baseline.degraded
    return baseline


@pytest.mark.parametrize("fault", ["llm_timeout", "llm_rate_limit"])
def test_llm_failure_falls_back_to_a_degraded_answer(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any], fault: str
) -> None:
    baseline = prove_healthy(client, faults, ticket, fault)

    with faults.enabled(fault):
        degraded = client.triage(ticket)

    assert degraded.faults_applied == [fault]
    assert degraded.source == "fallback"
    assert degraded.degraded
    assert degraded.degradation_reason == fault
    assert degraded.priority in PRIORITIES and degraded.priority != "low"
    assert degraded.category == baseline.category
    assert "category_from_cache" in degraded.warnings
    assert degraded.summary == ticket["title"]

    recovered = client.triage(ticket)
    assert recovered.source == "llm"


def test_malformed_output_is_retried_once_then_falls_back(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    prove_healthy(client, faults, ticket, "llm_garbage")

    with faults.enabled("llm_garbage"):
        degraded = client.triage(ticket)

    assert degraded.source == "fallback"
    assert degraded.degradation_reason == "llm_malformed_output"
    assert degraded.warnings.count("llm_output_retried") == 1


def test_hallucinated_summary_is_not_detected_by_the_app(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    """The app has no way to see this fault; the harness groundedness check does.
    This test pins that limitation so a change in either direction is deliberate."""
    baseline = prove_healthy(client, faults, ticket, "llm_hallucinate")

    with faults.enabled("llm_hallucinate"):
        result = client.triage(ticket)

    assert result.source == "llm"
    assert not result.degraded
    assert result.warnings == []
    assert result.summary != baseline.summary


def test_quota_exceeded_returns_503_and_makes_no_llm_call(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    prove_healthy(client, faults, ticket, "quota_exceeded")
    calls_before = client.metrics().llm_calls.total

    with faults.enabled("quota_exceeded"):
        response = client.triage_raw(ticket)
        health = client.health()

    assert response.status_code == 503
    assert response.headers["retry-after"].isdigit()
    assert response.json()["error"] == "token_budget_exhausted"
    assert health.status == "degraded"
    assert health.llm.status == "quota_exceeded"
    assert client.metrics().llm_calls.total == calls_before


@pytest.mark.slow
def test_slow_response_is_reported_honestly(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    baseline = prove_healthy(client, faults, ticket, "slow_response")

    with faults.enabled("slow_response"):
        slow = client.triage(ticket)

    assert slow.source == "llm"
    assert not slow.degraded
    assert slow.latency_ms >= 250
    assert slow.latency_ms > baseline.latency_ms


def test_pii_in_ticket_never_reaches_the_summary(
    client: TriageClient, faults: FaultToggler
) -> None:
    ticket = make_ticket(WITH_PII)
    baseline = prove_healthy(client, faults, ticket, "pii_leak")
    assert "555-010-9999" not in baseline.summary
    assert "sam@example.com" not in baseline.summary

    with faults.enabled("pii_leak"):
        leaked = client.triage(ticket)

    assert "555-010-9999" not in leaked.summary
    assert "sam@example.com" not in leaked.summary
    assert "[redacted-" in leaked.summary
    assert "pii_redacted" in leaked.warnings


def test_fallback_summary_is_also_pii_guarded(client: TriageClient, faults: FaultToggler) -> None:
    """Found by the harness against the real API: the fallback summary is the ticket
    title, and a title can contain contact details just as a description can."""
    ticket = make_ticket(title="Ask jo.bloggs@example.org about the smell in 4C")
    faults.assert_off("llm_rate_limit")

    with faults.enabled("llm_rate_limit"):
        degraded = client.triage(ticket)

    assert degraded.source == "fallback"
    assert "jo.bloggs@example.org" not in degraded.summary
    assert "[redacted-email]" in degraded.summary
    assert "pii_redacted" in degraded.warnings


def test_fallback_without_a_cached_category_uses_keywords(
    client: TriageClient, faults: FaultToggler
) -> None:
    ticket = make_ticket(PLUMBING_LEAK)  # fresh asset id: nothing cached for it
    faults.assert_off("llm_timeout")

    with faults.enabled("llm_timeout"):
        degraded = client.triage(ticket)

    assert degraded.source == "fallback"
    assert "category_from_keywords" in degraded.warnings
    assert degraded.category == keyword_category(f"{ticket['title']}\n{ticket['description']}")
    assert degraded.category == "plumbing"


def test_fallback_never_returns_low_priority(client: TriageClient, faults: FaultToggler) -> None:
    ticket = make_ticket(COSMETIC)
    faults.assert_off("llm_rate_limit")

    with faults.enabled("llm_rate_limit"):
        degraded = client.triage(ticket)

    assert degraded.source == "fallback"
    assert degraded.priority != "low"


def test_header_overrides_a_globally_enabled_fault(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    prove_healthy(client, faults, ticket, "llm_garbage")

    with faults.enabled("llm_garbage"):
        with_global = client.triage(ticket)
        with_override = client.triage(ticket, faults=["-llm_garbage"])

    assert with_global.source == "fallback"
    assert with_override.source == "llm"
    assert with_override.faults_applied == []


def test_header_and_global_faults_combine(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    prove_healthy(client, faults, ticket, "slow_response", "llm_rate_limit")

    with faults.enabled("slow_response"):
        result = client.triage(ticket, faults=["llm_rate_limit"])

    assert result.faults_applied == ["llm_rate_limit", "slow_response"]
    assert result.degradation_reason == "llm_rate_limit"


def test_unknown_fault_name_is_rejected(client: TriageClient, ticket: dict[str, Any]) -> None:
    response = client.triage_raw(ticket, faults=["llm_timeuot"])

    assert response.status_code == 400
    assert "known faults" in response.json()["detail"]


def test_recent_history_records_faults_and_outcomes(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    prove_healthy(client, faults, ticket, "llm_timeout")
    with faults.enabled("llm_timeout"):
        client.triage(ticket)

    newest, previous = client.recent(limit=2)

    assert newest.faults_applied == ["llm_timeout"]
    assert newest.response is not None and newest.response.source == "fallback"
    assert previous.faults_applied == []
    assert previous.response is not None and previous.response.source == "llm"
    assert newest.ticket.asset_id == previous.ticket.asset_id == ticket["asset_id"]
