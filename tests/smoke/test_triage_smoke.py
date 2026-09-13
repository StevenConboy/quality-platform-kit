"""Smoke: /triage answers, and answers in the documented shape."""

from __future__ import annotations

from typing import Any

import pytest

from app.models import CATEGORIES, PRIORITIES
from tests.framework.client import TriageClient

pytestmark = pytest.mark.smoke


def test_triage_returns_a_valid_decision(client: TriageClient, ticket: dict[str, Any]) -> None:
    result = client.triage(ticket)

    assert result.priority in PRIORITIES
    assert result.category in CATEGORIES
    assert result.summary.strip() and "\n" not in result.summary
    assert result.source == "llm"
    assert not result.degraded
    assert result.faults_applied == []
    assert result.usage.input_tokens > 0


def test_triage_rejects_an_empty_body(client: TriageClient) -> None:
    response = client.post("/triage", json_body={})
    assert response.status_code == 422


def test_openapi_documents_the_fault_header(client: TriageClient) -> None:
    spec = client.get("/openapi.json").json()
    params = spec["paths"]["/triage"]["post"]["parameters"]
    header = next(p for p in params if p["name"] == "x-fault")
    assert "llm_timeout" in header["description"]
