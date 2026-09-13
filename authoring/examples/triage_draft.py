"""Drafted tests for POST /triage. Drafted by the authoring tool for review.

This file is a hand-written stand-in for model output. It deliberately contains a mix of
good and bad tests so the review report has something to say without calling a model:
    authoring generate --spec openapi.json --endpoint /triage \
        --draft authoring/examples/triage_draft.py
"""

from __future__ import annotations

from typing import Any

import pytest

from app.models import CATEGORIES, PRIORITIES
from tests.framework.client import TriageClient
from tests.framework.faults import FaultToggler

pytestmark = pytest.mark.regression


def test_triage_returns_documented_priority_and_category(
    client: TriageClient, ticket: dict[str, Any]
) -> None:
    result = client.triage(ticket)
    assert result.priority in PRIORITIES
    assert result.category in CATEGORIES


def test_missing_asset_id_is_rejected_with_422(
    client: TriageClient, ticket: dict[str, Any]
) -> None:
    # Overlaps tests/regression/test_triage_validation.py, which checks 422 for every
    # missing field, but not closely enough for the exact-match duplicate check to flag
    # it. Spotting that overlap is the reviewer's job; the fingerprints help.
    del ticket["asset_id"]
    response = client.triage_raw(ticket)
    assert response.status_code == 422


def test_rate_limit_fault_produces_fallback(
    client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
) -> None:
    faults.assert_off("llm_rate_limit")
    with faults.enabled("llm_rate_limit"):
        degraded = client.triage(ticket)
    assert degraded.source == "fallback"
    assert degraded.degradation_reason == "llm_rate_limit"


def test_triage_responds(client: TriageClient, ticket: dict[str, Any]) -> None:
    # Weak: it only proves a response came back.
    response = client.triage_raw(ticket)
    assert response is not None


def test_summary_exists(client: TriageClient, ticket: dict[str, Any]) -> None:
    # Weak: no assertion at all.
    client.triage(ticket)


def test_unknown_fault_header_is_rejected(client: TriageClient, ticket: dict[str, Any]) -> None:
    # Duplicates tests/regression/test_triage_faults.py::test_unknown_fault_name_is_rejected
    response = client.triage_raw(ticket, faults=["llm_timeuot"])
    assert response.status_code == 400
    assert "known faults" in response.json()["detail"]


def test_summary_is_never_longer_than_100_characters(
    client: TriageClient, ticket: dict[str, Any]
) -> None:
    # Wrong: the documented limit is 240, so this will fail on some tickets. A human must
    # decide whether the test or the app is at fault.
    result = client.triage(ticket)
    assert len(result.summary) <= 60
