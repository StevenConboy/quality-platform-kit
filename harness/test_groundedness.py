"""Groundedness: the summary must not contradict the ticket.

This is the check the app cannot do for itself. With the llm_hallucinate fault on, the
app returns a confident, well-formed, wrong summary with a 200. Only this suite notices.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from harness.groundedness import GroundednessChecker, Verdict
from harness.report import ReportCollector
from tests.framework.client import TriageClient
from tests.framework.faults import FaultToggler
from tests.framework.tickets import SAMPLE_TICKETS, make_ticket

pytestmark = pytest.mark.regression


def record(
    report: ReportCollector,
    test_id: str,
    ticket: dict[str, Any],
    summary: str,
    verdict: Verdict,
    expected_grounded: bool,
) -> None:
    report.groundedness.append(
        {
            "test": test_id,
            "ticket_title": ticket["title"],
            "summary": summary,
            "grounded": verdict.grounded,
            "expected_grounded": expected_grounded,
            "method": verdict.method,
            "score": verdict.score,
            "rationale": verdict.rationale,
        }
    )


@pytest.mark.parametrize("sample", SAMPLE_TICKETS, ids=[t["asset_id"] for t in SAMPLE_TICKETS])
def test_healthy_summaries_are_grounded(
    client: TriageClient,
    groundedness: GroundednessChecker,
    report: ReportCollector,
    request: pytest.FixtureRequest,
    sample: dict[str, str],
) -> None:
    ticket = make_ticket(sample)
    result = client.triage(ticket)
    verdict = groundedness.check(ticket, result.summary)

    record(report, request.node.nodeid, ticket, result.summary, verdict, expected_grounded=True)
    assert verdict.grounded, f"{verdict.rationale}\n  summary: {result.summary}"


def test_hallucinated_summary_is_caught(
    client: TriageClient,
    faults: FaultToggler,
    groundedness: GroundednessChecker,
    report: ReportCollector,
    request: pytest.FixtureRequest,
) -> None:
    ticket = make_ticket()
    faults.assert_off("llm_hallucinate")
    honest = client.triage(ticket)
    assert groundedness.check(ticket, honest.summary).grounded

    with faults.enabled("llm_hallucinate"):
        result = client.triage(ticket)
    assert result.source == "llm" and not result.degraded, "the app itself cannot see this"

    verdict = groundedness.check(ticket, result.summary)
    record(report, request.node.nodeid, ticket, result.summary, verdict, expected_grounded=False)
    assert not verdict.grounded, f"hallucination not caught: {result.summary}"


def test_fallback_summary_is_grounded(
    client: TriageClient,
    faults: FaultToggler,
    groundedness: GroundednessChecker,
    report: ReportCollector,
    request: pytest.FixtureRequest,
) -> None:
    """The fallback summary is the ticket title, which cannot contradict the ticket."""
    ticket = make_ticket()
    faults.assert_off("llm_timeout")

    with faults.enabled("llm_timeout"):
        result = client.triage(ticket)
    assert result.source == "fallback"

    verdict = groundedness.check(ticket, result.summary)
    record(report, request.node.nodeid, ticket, result.summary, verdict, expected_grounded=True)
    assert verdict.grounded, verdict.rationale


def test_keyword_fallback_catches_the_canned_hallucination(
    groundedness: GroundednessChecker,
) -> None:
    """The offline method on its own must catch the injected summary, whatever mode is set."""
    from app.providers.faulty import HALLUCINATED_OUTPUT
    from harness.groundedness import keyword_verdict

    ticket = make_ticket()
    text = f"{ticket['title']}\n{ticket['description']}\n{ticket['asset_id']}"
    canned = json.loads(HALLUCINATED_OUTPUT)["summary"]

    verdict = keyword_verdict(text, canned, groundedness.settings.min_overlap)

    assert not verdict.grounded
    assert verdict.method == "keyword"
