# Test framework

A pytest setup that other services can adopt as-is. It gives you a typed API client with
retries and request capture, fault toggling, token spend tracking, structured logs, and
strict markers, all wired into fixtures. Tests run against an in-process app by default,
with no network, in about five seconds.

## Run it

```bash
make test                 # everything, FakeProvider, in-process
make smoke                # -m smoke
make regression           # -m regression
make test-fast            # -m "not slow"
make test-live            # against http://localhost:8000 (start it with `make run`)
make test-anthropic       # in-process app calling the real Anthropic API
uv run pytest tests/regression/test_health.py -k probe   # the usual pytest selection
```

Options: `--provider fake|anthropic` (or `TEST_PROVIDER`), `--base-url URL` (or
`TEST_BASE_URL`). With `--base-url` the same tests hit a running server; tests that need
a fresh app (they use the `fresh_state` fixture) skip themselves.

At the end of every run you get a token spend summary, total and top spenders per test.

## Add a test in under five minutes

1. Pick a folder: `tests/smoke/` for "is it up and roughly right", `tests/regression/` for
   specified behaviour. Create or open a `test_*.py` file there.
2. Put a marker on the module so it runs with the right suite:

   ```python
   import pytest

   pytestmark = pytest.mark.regression
   ```

3. Write the test. Ask for the fixtures you need by name:

   ```python
   from typing import Any
   from tests.framework.client import TriageClient
   from tests.framework.faults import FaultToggler


   def test_rate_limit_falls_back(
       client: TriageClient, faults: FaultToggler, ticket: dict[str, Any]
   ) -> None:
       faults.assert_off("llm_rate_limit")  # 1. prove the fault is off
       baseline = client.triage(ticket)
       assert baseline.source == "llm"

       with faults.enabled("llm_rate_limit"):  # 2. flip it on
           degraded = client.triage(ticket)

       assert degraded.source == "fallback"  # 3. assert graceful behaviour
       assert degraded.degradation_reason == "llm_rate_limit"
   ```

4. Run it: `uv run pytest tests/regression/test_yours.py -v`.
5. If it fails, the report includes the last API exchanges the client made, so you can
   see the exact request and response without adding prints.

That is the whole process. Marker typos fail the run rather than silently deselecting
the test, and mypy is strict on `tests/` so the type hints are checked too.

## Fixtures

| Fixture         | Gives you                                                                  |
| --------------- | -------------------------------------------------------------------------- |
| `client`        | `TriageClient` against a fresh app (or the live server with `--base-url`)   |
| `make_client`   | Factory for a client with custom settings: `make_client(token_budget=50)`   |
| `faults`        | `FaultToggler`: `assert_off()`, `enable()`, `disable()`, `enabled()` context |
| `ticket`        | A sample ticket with a unique asset id                                      |
| `token_tracker` | `TokenTracker`: `.spent` so far this test, `.assert_under(n)`               |
| `log`           | `StructuredLogger`: `log.step("event", key=value)`, JSON lines               |
| `provider_name` | `"fake"` or `"anthropic"`                                                   |
| `fresh_state`   | Skips the test under `--base-url`                                           |

Sample tickets live in [`framework/tickets.py`](framework/tickets.py). Use
`make_ticket(PLUMBING_LEAK, title="...")` to copy one with overrides; every copy gets a
new asset id so the app's per-asset category cache cannot leak between tests.

## The client

[`framework/client.py`](framework/client.py) has two classes.

`BaseApiClient` is generic. It wraps any `httpx2.Client` (the library Starlette's
`TestClient` and the Anthropic SDK are built on), retries transport errors and
gateway errors (502, 504) with backoff, and records every attempt as an `Exchange`. It
never retries 503, because this app returns 503 on purpose and a test must be able to see
it. To adopt the framework for another service, subclass it and add typed helpers.

`TriageClient` adds `triage()`, `triage_raw()`, `health()`, `metrics()`, `recent()`,
`get_faults()` and `set_faults()`. Helpers that return a model assert the status code
first, and the assertion message is the rendered exchange.

## Faults

`FaultToggler` uses the app's `/faults` endpoint, which is the same switch as
`faults.json`. `assert_off()` exists because a fault test that does not prove the fault
was off can pass for the wrong reason. Anything a test enables is switched off at
teardown, even if the test fails, so one test cannot poison the next. Per-request faults
go through the header instead: `client.triage(ticket, faults=["llm_timeout"])`.

## Markers

Registered in [`pyproject.toml`](../pyproject.toml) under `[tool.pytest.ini_options]`.
`--strict-markers` is on, so an unregistered marker is an error.

| Marker        | Meaning                                                            |
| ------------- | ------------------------------------------------------------------ |
| `smoke`       | Fast, runs on every push. Is the service up and roughly right?      |
| `regression`  | Specified behaviour. Runs before merge.                             |
| `adversarial` | Hostile input. The app must stay safe, not necessarily useful.      |
| `flaky`       | Quarantined: runs, reported separately, does not block the pipeline |
| `slow`        | More than a couple of seconds. `-m "not slow"` skips it.            |

## Layout

```
tests/
  conftest.py              fixtures, CLI options, reporting hooks
  framework/
    client.py              BaseApiClient, TriageClient, Exchange
    faults.py              FaultToggler
    budget.py              TokenTracker, SpendLedger
    structured_log.py      StructuredLogger
    tickets.py             sample tickets, make_ticket()
  smoke/                   one file per endpoint
  regression/              faults, validation, health, metrics
```
