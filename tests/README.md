# Tests

## Running the tests

From the repo root:

```bash
uv run pytest tests
```

That runs the shared suites: 41 tests against an in-process copy of the app using the
fake LLM provider. No server, no network, no API key. It takes about five seconds. At the
end you get a summary of how many tokens each test spent. Plain `uv run pytest` with no
path also runs the resilience harness in [`harness/`](../harness/README.md).

`uv run` just means "run this inside the project's virtual environment". If you have
activated the environment yourself, plain `pytest` works too.

Pick a subset:

```bash
uv run pytest -m smoke                     # the quick checks only
uv run pytest -m regression                # the specified-behaviour suite
uv run pytest -m "not slow"                # skip tests that wait on timers
uv run pytest tests/regression/test_health.py            # one file
uv run pytest -k "quota"                   # tests whose name contains "quota"
uv run pytest -v                           # show each test name as it runs
```

Run against a server that is already running (start one with `uv run uvicorn app.main:app`):

```bash
uv run pytest --base-url http://localhost:8000
```

Run against the real Anthropic API instead of the fake provider:

```bash
set ANTHROPIC_API_KEY=sk-ant-...           # Windows; use export on macOS/Linux
uv run pytest --provider anthropic
```

If `make` is installed, `make test`, `make smoke`, `make regression` and `make test-live`
are shortcuts for the commands above. They are not required.

## Reading a failure

When a test fails, pytest prints the assertion, then the app's log lines, then a section
called "API exchanges" showing every request the test sent and every response it got,
including the X-Fault header. You should not need to add print statements.

## Adding a test

1. Create a `test_*.py` file in `tests/smoke/` (quick "is it up" checks) or
   `tests/regression/` (specified behaviour).
2. Mark the module so it runs with the right suite:

   ```python
   import pytest

   pytestmark = pytest.mark.regression
   ```

3. Write the test. Ask for what you need by naming fixtures as parameters:

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

Marker names are checked: a typo like `smok` fails the run instead of silently skipping
the test. Type hints are checked too (`uv run mypy`).

## What the fixtures give you

| Fixture         | What it is                                                                        |
| --------------- | --------------------------------------------------------------------------------- |
| `client`        | A client for the app with `triage()`, `health()`, `metrics()`, `recent()`, ...     |
| `ticket`        | A sample ticket. Each test gets a different one from a pool of 17, with a fresh id |
| `faults`        | Switch faults on and off. Anything switched on is switched off after the test      |
| `token_tracker` | How many tokens this test has spent so far, and `assert_under(n)`                  |
| `log`           | `log.step("what happened", key=value)` writes a JSON line tagged with the test id  |
| `make_client`   | Build a client with custom app settings, e.g. `make_client(token_budget=50)`       |
| `provider_name` | `"fake"` or `"anthropic"`, whichever the run was started with                      |
| `fresh_state`   | Skips the test when running against a live server, where state is shared           |

Named sample tickets (`ELECTRICAL_URGENT`, `PLUMBING_LEAK`, `WITH_PII`, ...) are in
[`framework/tickets.py`](framework/tickets.py) for tests that need a specific shape:
`make_ticket(WITH_PII)`.

## Markers

| Marker        | Meaning                                                            |
| ------------- | ------------------------------------------------------------------ |
| `smoke`       | Fast. Is the service up and roughly right?                          |
| `regression`  | Specified behaviour. Run before merging.                            |
| `adversarial` | Hostile input. The app must stay safe, not necessarily useful.      |
| `flaky`       | Quarantined: runs, reported separately, does not block the pipeline |
| `slow`        | Takes more than a couple of seconds                                 |

They are registered in [`pyproject.toml`](../pyproject.toml).

## Flaky tests

A test marked `flaky` still runs in CI, but in a separate step that cannot fail the
pipeline; its result goes to the job summary instead. To find candidates, run the suite
several times and compare:

```bash
uv run python scripts/flake_detect.py --suite tests --runs 5
uv run python scripts/flake_detect.py --suite tests --runs 5 --apply   # also insert the markers
```

`--apply` writes a marker with the detection date above each inconsistent test, for
example `@pytest.mark.flaky  # quarantined 2026-09-13 by scripts/flake_detect.py: failed
2 of 5 runs`. Review the diff before committing. A weekly workflow runs the detector and
opens an issue when it finds anything.

## Two rules the suite follows

**Every fault test proves the fault is off first.** If a fault was already on, "before"
and "after" look the same and the test passes for the wrong reason. `faults.assert_off()`
makes that impossible.

**The client never retries a 503.** It retries connection errors and gateway errors
(502, 504) because those come from infrastructure. A 503 comes from the app on purpose
when the token budget is spent, and a test must be able to see it.

## Layout

```
conftest.py                (repo root) loads tests/framework/fixtures.py as a plugin
tests/
  framework/
    fixtures.py            fixtures, command line options, failure reporting
    client.py              the HTTP client: retries, request/response capture
    faults.py              FaultToggler
    budget.py              token spend tracking
    structured_log.py      JSON-line logger
    tickets.py             sample tickets
  smoke/                   one file per endpoint
  regression/              faults, validation, health, metrics
```
