# Demo script

A step-by-step walkthrough of the whole kit, with the exact commands and what to expect.
Budget about twenty minutes for everything, or pick the sections that matter. Every step
except the two marked *online* works with no API key and no network.

Commands are shown for PowerShell and for bash. Run them from the repo root.

## Before you start

```powershell
uv sync --all-groups          # once
uv run pytest -q              # expect: 124 passed in about 15 seconds
```

Open a second terminal for the app. The short timeout makes the timeout demo take two
seconds instead of eight.

```powershell
# PowerShell
$env:TRIAGE_LLM_TIMEOUT_SECONDS = "2"; uv run uvicorn app.main:app --port 8000
```

```bash
# bash
TRIAGE_LLM_TIMEOUT_SECONDS=2 uv run uvicorn app.main:app --port 8000
```

Open http://localhost:8000/docs in a browser. Everything below can also be done there:
expand an endpoint, "Try it out", fill the `x-fault` box, Execute.

Save the demo ticket once so the commands stay short:

```powershell
$t = '{"title":"Gas smell near boiler room","description":"Faint gas odour in the corridor outside the boiler room since about 9am. Call Sam on 555-010-9999.","asset_id":"BOILER-B1"}'
function triage($fault) { $h = @{}; if ($fault) { $h["X-Fault"] = $fault }; (Invoke-WebRequest -UseBasicParsing -Method Post http://localhost:8000/triage -ContentType application/json -Body $t -Headers $h).Content }
```

```bash
t='{"title":"Gas smell near boiler room","description":"Faint gas odour in the corridor outside the boiler room since about 9am. Call Sam on 555-010-9999.","asset_id":"BOILER-B1"}'
triage() { curl -s localhost:8000/triage -H 'content-type: application/json' ${1:+-H "X-Fault: $1"} -d "$t"; echo; }
```

## Part 1: the app and its faults (5 minutes)

**Say:** "This is a small service that triages maintenance tickets with an LLM. It has
seven faults built in, switchable per request with a header, so we can rehearse every
way an LLM integration fails in production without a real outage."

### 1.1 A normal request

```powershell
triage
```

Expect `"priority":"critical","category":"safety"`, a summary that restates the ticket,
`"source":"llm"`, `"degraded":false`, `"faults_applied":[]`, and non-zero token usage.

**Point out:** the phone number is not in the summary. The prompt forbids it and an
output guard enforces it.

### 1.2 The LLM times out

```powershell
triage llm_timeout
```

Takes two seconds. Expect `"source":"fallback"`, `"degraded":true`,
`"degradation_reason":"llm_timeout"`, `"warnings":["category_from_cache"]`, summary equal
to the title, and `"faults_applied":["llm_timeout"]`.

**Say:** "The caller still gets a usable answer. Priority came from keyword rules and
never goes below medium while degraded; category came from what the LLM said about this
asset last time. And the response is honest about all of it."

### 1.3 The LLM leaks personal data

```powershell
triage pii_leak
```

Expect the summary to end with `Contact: [redacted-phone].` and
`"warnings":["pii_redacted"]`.

### 1.4 The budget is spent

```powershell
try { triage quota_exceeded } catch { $_.ErrorDetails.Message }
```

```bash
triage quota_exceeded
```

Expect HTTP 503 with `"error":"token_budget_exhausted"` and a `Retry-After` header.

**Say:** "This one fails loudly on purpose. A spent budget is something an operator has
to act on; quietly serving fallbacks would hide it until the invoice."

### 1.5 The LLM lies

```powershell
triage llm_hallucinate
```

Expect a 200, `"source":"llm"`, `"degraded":false`, no warnings, and the summary
"Routine cosmetic touch-up requested; the asset is fully operational and no repair is
required." Priority low, category general. For a gas smell.

**Say:** "Everything about this response looks healthy. The app has no way to know the
summary contradicts the ticket. That is the gap the harness exists to close."

### 1.6 What the operator sees

```powershell
(Invoke-WebRequest -UseBasicParsing "http://localhost:8000/health?probe=true").Content
(Invoke-WebRequest -UseBasicParsing "http://localhost:8000/triage/recent?limit=5").Content
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/metrics).Content
```

```bash
curl -s "localhost:8000/health?probe=true"; curl -s "localhost:8000/triage/recent?limit=5"; curl -s localhost:8000/metrics
```

Health: `status`, the LLM's last error, probe latency, budget. Recent: the five requests
above, newest first, each with `faults_applied` and the full response. Metrics: counts,
latency percentiles, `faults_injected` per fault name, token spend.

## Part 2: the shared test framework (3 minutes)

**Say:** "Every suite in the repo is built on one set of fixtures. Another team adopts
them by copying `tests/framework` and adding one line to their conftest."

```powershell
uv run pytest tests -q
```

Expect 55 passed and a "token spend" table listing the top spenders per test.

Open [`tests/regression/test_triage_faults.py`](tests/regression/test_triage_faults.py)
and show one fault test: prove the fault is off, flip it on, assert the documented
degradation. Then show [`tests/README.md`](tests/README.md): the five-minute recipe.

To show what a failure looks like, break an assertion, run the one test, and point at
the "API exchanges" section pytest prints: every request and response the test made,
headers included. Undo the change.

## Part 3: the resilience harness (4 minutes)

```powershell
uv run pytest harness -q
```

Expect 69 passed, a "harness" section with the token budget, and the report path.

Open `reports/harness-report.md` and walk down it:

- **Provider health**: reachable, probe latency min/avg/max.
- **Degradation**: one row per fault, contract versus observed. Read the
  `llm_hallucinate` row: contract says "undetectable by the app; see groundedness".
- **Adversarial**: thirty payloads across prompt injection, oversized, empty, unicode and
  PII. Open [`harness/payloads/adversarial.yaml`](harness/payloads/adversarial.yaml) and
  show that adding a payload is a YAML edit.
- **Groundedness**: "Injected hallucinations caught: 1 of 1". Offline this is the keyword
  method; with a key it is an LLM judge scoring against
  [`harness/groundedness_rubric.md`](harness/groundedness_rubric.md).
- **Token spend**: the budget, and per-test spend.

**Say:** "The harness also found real bugs the first time it ran against the real API:
the fallback path skipped the PII guard, and the model was decoding asset codes into
locations. Both are fixed with regression tests." (Details in the harness README.)

To show the quota monitor failing a run:

```powershell
(Get-Content harness\config.yaml -Raw) -replace 'run: 60000', 'run: 3000' | Set-Content "$env:TEMP\tight.yaml"
$env:HARNESS_CONFIG = "$env:TEMP\tight.yaml"; uv run pytest harness -q; Remove-Item Env:HARNESS_CONFIG
```

```bash
sed 's/run: 60000/run: 3000/' harness/config.yaml > /tmp/tight.yaml
HARNESS_CONFIG=/tmp/tight.yaml uv run pytest harness -q
```

Expect the run to stop after a dozen tests with "token budget exceeded during ..." and a
non-zero exit code.

## Part 4: flaky tests (3 minutes)

**Say:** "A flaky test is worse than no test: it trains people to ignore red. So we
detect them, quarantine them with a date, and keep running them where they cannot
block anyone."

```powershell
$env:SIMULATE_FLAKY = "1"; uv run python scripts/flake_detect.py --suite tests/demo --runs 6; Remove-Item Env:SIMULATE_FLAKY
```

```bash
SIMULATE_FLAKY=1 uv run python scripts/flake_detect.py --suite tests/demo --runs 6
```

Expect a table with `test_simulated_flake` failing some of the six runs (a coin flip
per run; if all six agree, run it again). Add `--apply` and the script inserts
`@pytest.mark.flaky  # quarantined <date> by scripts/flake_detect.py: failed N of 6 runs`
above the test. It is already applied in the repo, so `--apply` reports "unchanged".

Then show CI: in any regression job, the step "Quarantined regression tests (never
block)" runs that one test with the simulation on, and the job summary shows its result
without affecting the job's colour. The weekly workflow does the same detection on a
schedule and opens an issue; issue #1 in the repo is one it opened.

## Part 5: AI-assisted test authoring (3 minutes)

**Say:** "Copilot types tests. This drafts them from the contract, in our style, runs
them, and grades them. A person still decides what gets merged."

Offline, using a hand-written draft that has problems on purpose:

```powershell
uv run authoring export-spec --out openapi.json
uv run authoring generate --spec openapi.json --endpoint /triage --draft authoring/examples/triage_draft.py
```

Expect seven verdicts: three ready for review, two needing work (no assertions, only
trivial assertions), one discard for duplicating an existing test, and one "investigate"
for a test that failed. Open `authoring/review/triage/REVIEW.md`: the table, then the
coverage fingerprints that explain the duplicate call. Point out the test that "overlaps"
an existing parametrized test but was not flagged: the duplicate check is exact on
purpose, and the fingerprints are there so a reviewer spots the overlap.

*Online.* With `ANTHROPIC_API_KEY` in `.env`:

```powershell
uv run authoring generate --spec openapi.json --endpoint /triage
```

Takes about a minute and roughly 17k tokens. The last run drafted six tests, all rated
ready for review, covering validation cases and a header behaviour the suite did not
have. `authoring/review/triage/prompt_used.md` shows exactly what the model was told.

## Part 6: CI (2 minutes)

Open the Actions tab on GitHub. Show a CI run: lint, typecheck, smoke, regression and
harness offline on Python 3.11 and 3.12; artifacts with JUnit XML and the harness report;
a job summary with the quarantine table.

*Online.* "Run workflow" on CI with `run_online` ticked runs the harness against the real
API with the LLM judge. It is opt-in because each run spends about 40k tokens. The
passing run from 2026-09-13 is in the history.

## Resetting between demos

- Restart the app to clear metrics, history and the category cache.
- `git checkout harness/config.yaml` if you edited it instead of using `HARNESS_CONFIG`.
- `authoring/review/`, `reports/` and `openapi.json` are gitignored; delete them freely.

## If something goes wrong

- `uv` not found: install it from https://docs.astral.sh/uv/ and open a new terminal.
- Port 8000 busy: pass `--port 8001` to uvicorn and adjust the URLs.
- Timeout demo takes eight seconds: the app was started without
  `TRIAGE_LLM_TIMEOUT_SECONDS=2`.
- Flake detector reports nothing: six identical coin flips happen about three percent
  of the time; run it again.
