"""Fixtures and hooks shared by every test in this repo.

Fixtures:
  client         TriageClient against a fresh in-process app (or a live server with --base-url)
  make_client    factory for a client with custom app settings, e.g. make_client(token_budget=50)
  faults         FaultToggler; anything it enables is switched off again at teardown
  provider_name  "fake" (default) or "anthropic" (--provider anthropic, needs ANTHROPIC_API_KEY)
  token_tracker  TokenTracker: tokens this test has spent so far, with assert_under()
  log            StructuredLogger bound to the current test id
  ticket         a sample ticket with a unique asset id
  fresh_state    skips the test when running against a live server (state is shared there)

Hooks:
  a failing test's report includes the last API exchanges the client made
  the run summary lists token spend per test
"""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Callable, Generator, Iterator
from typing import Any

import httpx2
import pytest
from _pytest.terminal import TerminalReporter
from fastapi.testclient import TestClient

from app.config import Settings
from app.faults import ALL_FAULTS
from app.main import create_app
from tests.framework.budget import SpendLedger, TokenTracker
from tests.framework.client import TriageClient
from tests.framework.faults import FaultToggler
from tests.framework.structured_log import StructuredLogger
from tests.framework.tickets import make_ticket

LEDGER = pytest.StashKey[SpendLedger]()

MakeClient = Callable[..., TriageClient]


# --- command line options ---------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("quality-platform-kit")
    group.addoption(
        "--provider",
        choices=["fake", "anthropic"],
        default=os.environ.get("TEST_PROVIDER", "fake"),
        help="LLM provider for the in-process app (default: fake, or $TEST_PROVIDER)",
    )
    group.addoption(
        "--base-url",
        default=os.environ.get("TEST_BASE_URL"),
        help="Run against a live server at this URL instead of an in-process app",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.stash[LEDGER] = SpendLedger()
    in_process_anthropic = config.getoption("--provider") == "anthropic" and not config.getoption(
        "--base-url"
    )
    if in_process_anthropic and not os.environ.get("ANTHROPIC_API_KEY"):
        raise pytest.UsageError("--provider anthropic requires ANTHROPIC_API_KEY to be set")


# --- session-scoped configuration -------------------------------------------------------


@pytest.fixture(scope="session")
def provider_name(request: pytest.FixtureRequest) -> str:
    name: str = request.config.getoption("--provider")
    return name


@pytest.fixture(scope="session")
def base_url(request: pytest.FixtureRequest) -> str | None:
    url: str | None = request.config.getoption("--base-url")
    return url


@pytest.fixture(scope="session")
def app_settings(provider_name: str, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Settings for the in-process app. Faults come from a temp file with everything off,
    so the repo's faults.json cannot affect a test run. Timeouts are short for the fake
    provider so timeout tests take half a second rather than eight."""
    faults_file = tmp_path_factory.mktemp("faults") / "faults.json"
    faults_file.write_text(json.dumps({"faults": dict.fromkeys(sorted(ALL_FAULTS), False)}))
    return Settings(
        provider="fake" if provider_name == "fake" else "anthropic",
        llm_timeout_seconds=0.5 if provider_name == "fake" else 20.0,
        slow_response_seconds=0.3,
        faults_file=faults_file,
    )


# --- per-test fixtures ------------------------------------------------------------------


@pytest.fixture
def log(request: pytest.FixtureRequest) -> StructuredLogger:
    return StructuredLogger(request.node.nodeid)


@pytest.fixture
def make_client(
    app_settings: Settings, base_url: str | None, log: StructuredLogger
) -> Iterator[MakeClient]:
    """Build a client. Keyword arguments override app settings (in-process only)."""
    opened: list[httpx2.Client] = []

    def _make(**overrides: Any) -> TriageClient:
        http: httpx2.Client
        if base_url:
            if overrides:
                pytest.skip("settings overrides need an in-process app, not --base-url")
            http = httpx2.Client(base_url=base_url, timeout=30.0)
        else:
            http = TestClient(create_app(dataclasses.replace(app_settings, **overrides)))
        opened.append(http)
        return TriageClient(http, log=log)

    yield _make
    for http in opened:
        http.close()


@pytest.fixture
def client(make_client: MakeClient) -> TriageClient:
    return make_client()


@pytest.fixture
def faults(client: TriageClient, log: StructuredLogger) -> Iterator[FaultToggler]:
    toggler = FaultToggler(client, log)
    yield toggler
    toggler.clear()


@pytest.fixture
def ticket() -> dict[str, Any]:
    return make_ticket()


@pytest.fixture
def token_tracker(client: TriageClient, request: pytest.FixtureRequest) -> TokenTracker:
    return TokenTracker(client, request.node.nodeid)


@pytest.fixture
def fresh_state(base_url: str | None) -> None:
    if base_url:
        pytest.skip("needs a fresh in-process app; a live server's state is shared")


@pytest.fixture(autouse=True)
def _record_spend(request: pytest.FixtureRequest) -> Iterator[None]:
    """Record every test's token spend in the session ledger, if it used a client."""
    if "client" not in request.fixturenames:
        yield
        return
    tracker = TokenTracker(request.getfixturevalue("client"), request.node.nodeid)
    yield
    request.config.stash[LEDGER].record(request.node.nodeid, tracker.finish())


# --- reporting hooks --------------------------------------------------------------------


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Attach the client's recent request/response pairs to a failed test's report."""
    report = yield
    if report.when == "call" and report.failed:
        client = getattr(item, "funcargs", {}).get("client")
        if isinstance(client, TriageClient) and client.exchanges:
            report.sections.append(("API exchanges (most recent last)", client.render_exchanges()))
    return report


def pytest_terminal_summary(terminalreporter: TerminalReporter, config: pytest.Config) -> None:
    ledger = config.stash[LEDGER]
    if not ledger.by_test:
        return
    terminalreporter.section("token spend")
    terminalreporter.write_line(
        f"total: {ledger.total} tokens across {len(ledger.by_test)} tests; top spenders:"
    )
    for test_id, spent in ledger.top(5):
        terminalreporter.write_line(f"{spent:>8}  {test_id}")
