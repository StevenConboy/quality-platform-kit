"""Degradation: under every fault the app must degrade the documented way, not crash.

The contract for each fault comes from app/README.md and is written down here as data,
so a fault added to the app without a contract fails test_every_fault_has_a_contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.faults import ALL_FAULTS
from app.models import TriageResponse
from harness.report import ReportCollector
from tests.framework.client import TriageClient
from tests.framework.faults import FaultToggler
from tests.framework.tickets import WITH_PII, make_ticket

pytestmark = pytest.mark.regression


@dataclass(frozen=True)
class Contract:
    status: int
    source: str | None  # "llm" or "fallback"; None when there is no triage body
    degraded: bool | None
    reason: str | None
    health: str  # expected top-level /health status while the fault is on
    warning: str | None = None
    min_latency_ms: float | None = None
    note: str = ""

    def describe(self) -> str:
        if self.status != 200:
            return f"HTTP {self.status}, health {self.health}"
        parts = [f"200 {self.source}"]
        if self.reason:
            parts.append(f"reason {self.reason}")
        if self.warning:
            parts.append(f"warning {self.warning}")
        if self.min_latency_ms:
            parts.append(f"latency >= {self.min_latency_ms:.0f} ms")
        parts.append(f"health {self.health}")
        return ", ".join(parts)


CONTRACTS: dict[str, Contract] = {
    "llm_timeout": Contract(200, "fallback", True, "llm_timeout", "degraded"),
    "llm_rate_limit": Contract(200, "fallback", True, "llm_rate_limit", "degraded"),
    "llm_garbage": Contract(200, "fallback", True, "llm_malformed_output", "degraded"),
    "llm_hallucinate": Contract(
        200, "llm", False, None, "ok", note="undetectable by the app; see groundedness"
    ),
    "quota_exceeded": Contract(503, None, None, None, "degraded"),
    "slow_response": Contract(200, "llm", False, None, "ok", min_latency_ms=250),
    "pii_leak": Contract(200, "llm", False, None, "ok", warning="pii_redacted"),
}


def observe(client: TriageClient, fault: str, ticket: dict[str, Any]) -> tuple[Any, str, str]:
    """Send one request under the fault. Returns (parsed body or None, health, description)."""
    response = client.triage_raw(ticket)
    health = client.health().status
    if response.status_code != 200:
        return None, health, f"HTTP {response.status_code}, health {health}"
    result = TriageResponse.model_validate(response.json())
    parts = [f"200 {result.source}"]
    if result.degradation_reason:
        parts.append(f"reason {result.degradation_reason}")
    if result.warnings:
        parts.append("warnings " + ",".join(result.warnings))
    parts.append(f"latency {result.latency_ms:.0f} ms")
    parts.append(f"health {health}")
    return result, health, ", ".join(parts)


def test_every_fault_has_a_contract() -> None:
    assert set(CONTRACTS) == ALL_FAULTS, (
        f"missing contracts: {ALL_FAULTS - set(CONTRACTS)}; "
        f"stale contracts: {set(CONTRACTS) - ALL_FAULTS}"
    )


@pytest.mark.parametrize("fault", sorted(ALL_FAULTS))
def test_app_degrades_per_contract(
    client: TriageClient, faults: FaultToggler, fault: str, report: ReportCollector
) -> None:
    contract = CONTRACTS[fault]
    ticket = make_ticket(WITH_PII) if fault == "pii_leak" else make_ticket()

    faults.assert_off(fault)
    healthy = client.triage(ticket)
    assert healthy.source == "llm" and not healthy.degraded

    with faults.enabled(fault):
        result, health, observed = observe(client, fault, ticket)

    problems: list[str] = []
    if health != contract.health:
        problems.append(f"health {health}, expected {contract.health}")
    if contract.status != 200:
        if result is not None:
            problems.append(f"expected HTTP {contract.status}, got a 200 body")
    elif result is None:
        problems.append(f"expected 200, got {observed}")
    else:
        if result.source != contract.source:
            problems.append(f"source {result.source}, expected {contract.source}")
        if result.degraded != contract.degraded:
            problems.append(f"degraded {result.degraded}, expected {contract.degraded}")
        if result.degradation_reason != contract.reason:
            problems.append(f"reason {result.degradation_reason}, expected {contract.reason}")
        if contract.warning and contract.warning not in result.warnings:
            problems.append(f"warning {contract.warning} missing from {result.warnings}")
        if contract.min_latency_ms and result.latency_ms < contract.min_latency_ms:
            problems.append(f"latency {result.latency_ms:.0f} ms under {contract.min_latency_ms}")
        if result.faults_applied != [fault]:
            problems.append(f"faults_applied {result.faults_applied}, expected [{fault}]")

    report.degradation.append(
        {
            "fault": fault,
            "contract": contract.describe() + (f" ({contract.note})" if contract.note else ""),
            "observed": observed,
            "passed": not problems,
        }
    )
    assert not problems, "; ".join(problems)


@pytest.mark.parametrize("fault", sorted(ALL_FAULTS))
def test_app_recovers_after_fault(client: TriageClient, faults: FaultToggler, fault: str) -> None:
    """Whatever a fault did, the next request without it must be fully healthy."""
    ticket = make_ticket()
    faults.assert_off(fault)

    with faults.enabled(fault):
        client.triage_raw(ticket)

    recovered = client.triage(ticket)
    health = client.health()

    assert recovered.source == "llm"
    assert not recovered.degraded
    assert recovered.faults_applied == []
    assert health.status == "ok"
    assert health.llm.consecutive_failures == 0
