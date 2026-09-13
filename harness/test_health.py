"""Provider health: is the LLM reachable through the app, and how fast does it answer?"""

from __future__ import annotations

import pytest

from harness.health_checks import probe_once, run_probes
from harness.report import ReportCollector
from harness.settings import HarnessSettings
from tests.framework.client import TriageClient
from tests.framework.faults import FaultToggler

pytestmark = pytest.mark.smoke


def test_provider_is_reachable(
    client: TriageClient, harness_settings: HarnessSettings, report: ReportCollector
) -> None:
    summary = run_probes(client, harness_settings.probe_count)
    report.health = summary

    assert summary.reachable, (
        f"{summary.failures} of {summary.probes} probes failed: {summary.errors}"
    )


def test_probe_latency_is_acceptable(
    client: TriageClient, harness_settings: HarnessSettings
) -> None:
    summary = run_probes(client, harness_settings.probe_count)

    assert summary.max_latency_ms <= harness_settings.max_probe_latency_ms, (
        f"slowest probe {summary.max_latency_ms:.0f} ms exceeds "
        f"{harness_settings.max_probe_latency_ms:.0f} ms"
    )


def test_health_reports_an_unreachable_provider(client: TriageClient, faults: FaultToggler) -> None:
    """A probe must say "unreachable" when the provider is, rather than "ok" by default."""
    faults.assert_off("llm_timeout")
    assert probe_once(client).reachable

    with faults.enabled("llm_timeout"):
        result = probe_once(client)

    assert not result.reachable
    assert result.llm_status == "unreachable"
    assert result.error == "llm_timeout"
