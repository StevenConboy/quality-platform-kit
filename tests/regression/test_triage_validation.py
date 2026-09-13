"""Regression: the /triage input contract."""

from __future__ import annotations

from typing import Any

import pytest

from tests.framework.client import TriageClient
from tests.framework.tickets import make_ticket

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("field", ["title", "description", "asset_id"])
def test_missing_field_is_rejected(client: TriageClient, field: str) -> None:
    ticket = make_ticket()
    del ticket[field]

    response = client.triage_raw(ticket)

    assert response.status_code == 422
    assert any(field in error["loc"] for error in response.json()["detail"])


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"title": "   "}, id="blank-title"),
        pytest.param({"description": "x" * 4001}, id="oversized-description"),
        pytest.param({"asset_id": "rack b"}, id="asset-id-with-space"),
        pytest.param({"asset_id": "rack/b"}, id="asset-id-with-slash"),
        pytest.param({"priority": "critical"}, id="unknown-field"),
    ],
)
def test_invalid_input_is_rejected(client: TriageClient, overrides: dict[str, Any]) -> None:
    response = client.triage_raw(make_ticket(**overrides))
    assert response.status_code == 422


def test_unicode_text_is_accepted(client: TriageClient) -> None:
    ticket = make_ticket(
        title="Fenêtre cassée – étage 2",
        description="La vitre est fissurée près de l'entrée. Risque de blessure ⚠️.",
    )
    result = client.triage(ticket)
    assert result.summary


def test_boundary_lengths_are_accepted(client: TriageClient) -> None:
    ticket = make_ticket(title="t" * 200, description="d" * 4000, asset_id="a" * 64)
    result = client.triage(ticket)
    assert len(result.summary) <= 240
