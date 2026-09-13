# AI resilience harness

Does the app stay safe and honest when the LLM does not? The harness answers that with
four suites, a token quota, and a report you can hand to someone who was not in the room.

## Running it

From the repo root:

```bash
uv run pytest harness
```

Offline, fake provider, about ten seconds. It writes `reports/harness-report.md` and
prints a summary with the token spend and the report path.

Pick a suite:

```bash
uv run pytest harness/test_health.py
uv run pytest harness/test_degradation.py
uv run pytest harness/test_adversarial.py
uv run pytest harness/test_groundedness.py
```

Use the real LLM judge for groundedness (the app can still use the fake provider):

```bash
set ANTHROPIC_API_KEY=sk-ant-...      # Windows; export on macOS/Linux
uv run pytest harness
```

Run the app against the real API as well:

```bash
uv run pytest harness --provider anthropic
```

Probe a running server's provider health on its own, without pytest:

```bash
uv run python -m harness.health_checks http://localhost:8000
```

If `make` is installed, `make harness` and `make harness-online` are shortcuts.

## What each suite does

**Health** ([`test_health.py`](test_health.py)). Probes the provider through the app's
`/health?probe=true` several times and reports reachability and min/avg/max latency. Also
proves the probe says "unreachable" when the provider is, so a green health check means
something.

**Degradation** ([`test_degradation.py`](test_degradation.py)). For every fault the app
knows about: prove the fault is off, switch it on, send a ticket, and compare what came
back with the contract written in [`app/README.md`](../app/README.md). The contracts are
data at the top of the file. A fault added to the app without a contract fails the suite.
A second test per fault checks the app is fully healthy again once the fault is off.

**Adversarial** ([`test_adversarial.py`](test_adversarial.py)). Sends the payloads in
[`payloads/adversarial.yaml`](payloads/adversarial.yaml): prompt injection, oversized,
empty, unicode edge cases, and PII. Each expects either `safe` (200, valid single-line
summary, and the payload's checks hold) or `rejected` (a clean 422). To add a payload,
add a list entry to the YAML. No code change.

**Groundedness** ([`test_groundedness.py`](test_groundedness.py)). Checks that each
summary does not contradict its ticket. Healthy summaries must pass, the fallback summary
must pass, and the summary produced under the `llm_hallucinate` fault must fail. That last
one is the point of the harness: the app returns that summary with a 200 and no warning.

## The groundedness judge

Two methods, chosen by `groundedness.judge` in [`config.yaml`](config.yaml):

- **LLM judge.** Uses the Anthropic SDK to score the summary 1 to 5 against the rubric in
  [`groundedness_rubric.md`](groundedness_rubric.md). Edit the rubric to change what
  counts. Grounded means no contradiction and a score at or above `min_score`.
- **Keyword overlap.** No network. Grounded means at least `min_overlap` of the summary's
  content words appear in the ticket, and the summary contains no "all clear" phrase
  (such as "no repair" or "fully operational") that the ticket does not.

`auto` uses the judge when `ANTHROPIC_API_KEY` is set and keywords otherwise. If a judge
call fails, that one check falls back to keywords and the verdict's rationale says so.
The report states which method was used. Judge spend is reported separately from the
app's token budget.

## The token quota

`token_budget.run` in `config.yaml` is the most tokens the app may spend in one harness
run. Spend is read from the app's own `/metrics`, so the fake provider's estimates count
too and the budget behaves the same offline. If the budget is crossed, the run stops
after the current test, is marked failed, and the terminal summary says during which test
it happened. Any single test over `token_budget.per_test` is flagged as a hot spot. The
report lists spend per test either way.

The budget covers the whole pytest process, so running `uv run pytest` (tests and harness
together) counts both. Point `HARNESS_CONFIG` at another YAML file to use a different
budget or thresholds without editing the checked-in one.

## The report

[`REPORT.md`](REPORT.md) is the template. Every `{{placeholder}}` is filled at the end
of the run and the result written to `reports/harness-report.md` (the path is in
`config.yaml`). Sections: provider health, a degradation table of contract versus
observed, adversarial results per category with any failures spelled out, groundedness
counts including whether the injected hallucination was caught, and token spend.

## What the first online run found

Running against the real API for the first time surfaced three things, all fixed since:

- The fallback summary (the ticket title) skipped the PII guard, so an email address in
  a title leaked whenever the LLM was unavailable.
- The triage model decoded asset codes: `STAIR-N-3` became "north stairwell, level 3" in
  a summary. The judge scored it unsupported. The system prompt now says asset ids are
  opaque.
- Dropped connections between the runner and the API turned into fallbacks because SDK
  retries were off. They are on now, and the harness's "prove healthy" baseline retries
  a transient `llm_unavailable` rather than reporting it as a contract failure.

## Extending it

- New fault in the app: add a `Contract` in `test_degradation.py`. The suite tells you if
  you forget.
- New adversarial payload: add it to the YAML.
- Different groundedness standard: edit the rubric, or the thresholds in `config.yaml`.
- Another service: the harness only depends on the shared fixtures in
  `tests/framework/`, so it comes along with them.

## Layout

```
harness/
  config.yaml              budgets, thresholds, judge mode, paths
  conftest.py              harness fixtures, quota monitor, report writer
  settings.py              typed view of config.yaml
  health_checks.py         probe functions, also runnable as a script
  quota.py                 QuotaMonitor
  groundedness.py          GroundednessChecker: LLM judge + keyword fallback
  groundedness_rubric.md   the judge's instructions
  adversarial.py           YAML loader and response evaluator
  payloads/adversarial.yaml
  report.py                ReportCollector and template filling
  REPORT.md                the template
  test_*.py                the four suites
```
