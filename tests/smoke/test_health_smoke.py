"""Smoke: /health reports the app and provider as healthy when nothing is wrong."""

from __future__ import annotations

import pytest

from tests.framework.client import TriageClient

pytestmark = pytest.mark.smoke


def test_health_is_ok_with_no_faults(client: TriageClient, provider_name: str) -> None:
    health = client.health()

    assert health.status == "ok"
    assert health.llm.provider == provider_name
    assert health.faults_active == []
    assert not health.token_budget.exhausted


def test_health_probe_reaches_the_provider(client: TriageClient) -> None:
    health = client.health(probe=True)

    assert health.status == "ok"
    assert health.llm.status == "ok"
    assert health.llm.probe_latency_ms is not None
    assert health.llm.probe_latency_ms >= 0
