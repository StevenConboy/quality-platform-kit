"""Harness-only fixtures and hooks. The shared fixtures come from the root conftest.

Adds:
  harness_settings   typed view of harness/config.yaml
  groundedness       GroundednessChecker (LLM judge or keyword fallback)
  report             ReportCollector that the suites record findings into
  a quota monitor that fails the run when app token spend crosses the budget
  REPORT.md rendering at the end of the session
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from _pytest.terminal import TerminalReporter

from harness.groundedness import GroundednessChecker
from harness.quota import QuotaMonitor
from harness.report import ReportCollector
from harness.settings import HarnessSettings
from tests.framework.fixtures import LEDGER

SETTINGS = pytest.StashKey[HarnessSettings]()
QUOTA = pytest.StashKey[QuotaMonitor]()
REPORT = pytest.StashKey[ReportCollector]()
CHECKER = pytest.StashKey[GroundednessChecker]()
SESSION = pytest.StashKey[pytest.Session]()


def pytest_configure(config: pytest.Config) -> None:
    settings = HarnessSettings.load()
    config.stash[SETTINGS] = settings
    config.stash[QUOTA] = QuotaMonitor(settings.run_token_budget, settings.per_test_token_budget)
    config.stash[REPORT] = ReportCollector()


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[SESSION] = session


# --- fixtures ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def harness_settings(request: pytest.FixtureRequest) -> HarnessSettings:
    return request.config.stash[SETTINGS]


@pytest.fixture(scope="session")
def groundedness(
    request: pytest.FixtureRequest, harness_settings: HarnessSettings
) -> GroundednessChecker:
    checker = GroundednessChecker(harness_settings, api_key=os.environ.get("ANTHROPIC_API_KEY"))
    request.config.stash[CHECKER] = checker
    request.config.stash[REPORT].judge = checker.method
    return checker


@pytest.fixture(scope="session", autouse=True)
def _report_provider(request: pytest.FixtureRequest, provider_name: str) -> None:
    request.config.stash[REPORT].provider = provider_name


@pytest.fixture
def report(request: pytest.FixtureRequest) -> ReportCollector:
    return request.config.stash[REPORT]


@pytest.fixture(autouse=True)
def _quota_guard(request: pytest.FixtureRequest) -> Iterator[None]:
    """After each test, check the run budget. Crossing it fails the run and stops it."""
    yield
    config = request.config
    if QUOTA not in config.stash:
        return
    quota = config.stash[QUOTA]
    ledger = config.stash[LEDGER]
    if quota.observe(ledger, request.node.nodeid):
        session = config.stash[SESSION]
        session.shouldfail = (
            f"token budget exceeded during {request.node.nodeid}: "
            f"{ledger.total} > {quota.run_budget}"
        )


# --- reporting --------------------------------------------------------------------------


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Count outcomes for the report. Skips can happen at setup; failures at any phase."""
    # This hook can fire before pytest_configure has run for us if collection is odd;
    # guard rather than assume.
    collector = _collector_for_current_session
    if collector is None:
        return
    if report.when == "call" or report.outcome != "passed":
        collector.record_outcome(report.outcome)


_collector_for_current_session: ReportCollector | None = None


@pytest.hookimpl(trylast=True)
def pytest_collection_finish(session: pytest.Session) -> None:
    global _collector_for_current_session
    _collector_for_current_session = session.config.stash[REPORT]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    if REPORT not in config.stash:
        return
    settings = config.stash[SETTINGS]
    quota = config.stash[QUOTA]
    ledger = config.stash[LEDGER]
    checker = config.stash.get(CHECKER, None)
    if quota.exceeded:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    text = config.stash[REPORT].render(
        settings.report_template, ledger, quota, checker.usage if checker else None
    )
    settings.report_output.parent.mkdir(parents=True, exist_ok=True)
    settings.report_output.write_text(text, encoding="utf-8")


def pytest_terminal_summary(terminalreporter: TerminalReporter, config: pytest.Config) -> None:
    if QUOTA not in config.stash:
        return
    settings = config.stash[SETTINGS]
    quota = config.stash[QUOTA]
    ledger = config.stash[LEDGER]
    terminalreporter.section("harness")
    terminalreporter.write_line(f"token budget: {quota.status_line(ledger)}")
    if quota.exceeded:
        terminalreporter.write_line(f"budget crossed during: {quota.exceeded_at}", red=True)
    for test, spent in quota.hot_spots(ledger):
        terminalreporter.write_line(f"hot spot: {spent} tokens  {test}", yellow=True)
    terminalreporter.write_line(f"report written to: {settings.report_output}")
