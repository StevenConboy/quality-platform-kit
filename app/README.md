# ticket-triage

A small FastAPI service that triages facilities maintenance tickets with an LLM. It is the
target application for the rest of this kit: the test framework, the resilience harness, and
the CI pipeline all point at it.

It exists to be broken on purpose. Every failure mode a real LLM integration hits in
production can be switched on here without a real LLM.

## Endpoints

| Method | Path             | What it does                                                        |
| ------ | ---------------- | ------------------------------------------------------------------- |
| POST   | `/triage`        | Accepts a ticket, returns priority, category and a one-line summary |
| GET    | `/health`        | App status plus what the app has observed about the LLM             |
| GET    | `/health?probe=true` | Same, but actively pings the provider first                     |
| GET    | `/metrics`       | Request counts, latency percentiles, LLM call outcomes, token spend |
| GET    | `/faults`        | Faults enabled globally, with a description of each                 |
| PUT    | `/faults`        | Enable or disable faults globally for this process                  |
| POST   | `/faults/reload` | Re-read `faults.json`                                               |
| GET    | `/docs`          | Interactive OpenAPI docs                                            |

### POST /triage

Request:

```json
{
  "title": "Breaker tripping in server room",
  "description": "Main breaker for rack B trips every few hours. Smell of burning plastic.",
  "asset_id": "SRV-ROOM-2"
}
```

Response:

```json
{
  "ticket_id": "b07e27b5-...",
  "priority": "high",
  "category": "electrical",
  "summary": "Breaker tripping in server room on SRV-ROOM-2: Main breaker for rack B trips every few hours.",
  "source": "llm",
  "degraded": false,
  "degradation_reason": null,
  "warnings": [],
  "model": "fake-triage-v1",
  "usage": { "input_tokens": 199, "output_tokens": 38 },
  "latency_ms": 0.17
}
```

Field notes:

- `source` is `llm` when the model answered, `fallback` when the app answered on its own.
- `degraded` and `degradation_reason` say whether and why the fallback path was used.
- `warnings` lists anything the app did to the response that a caller should know about:
  `pii_redacted`, `llm_output_retried`, `category_from_cache`, `category_from_keywords`,
  `unknown_priority_coerced:<value>`, `unknown_category_coerced:<value>`.
- Validation is strict: unknown fields, blank text, oversized text, and asset IDs outside
  `[A-Za-z0-9_-]` all return 422.

Priorities: `critical`, `high`, `medium`, `low`.
Categories: `electrical`, `plumbing`, `hvac`, `structural`, `safety`, `it`, `general`.

## Running it

```bash
make install          # uv sync
make run              # http://localhost:8000, FakeProvider, no network
```

To use a real model:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
TRIAGE_PROVIDER=anthropic make run
```

All settings are environment variables; see [`.env.example`](../.env.example).

## Providers

The app talks to the LLM through one small interface, `LLMProvider`, in
[`providers/base.py`](providers/base.py): `complete(system, user)` and `ping()`. Two
implementations:

- **FakeProvider** answers instantly and deterministically using keyword rules. Same input,
  same output, no network. Every test in this repo runs against it by default.
- **AnthropicProvider** uses the Anthropic Python SDK. SDK retries are disabled so that a 429
  or timeout reaches the app immediately and the app's own handling is what gets exercised.

The provider returns raw text. Parsing, validation, retry, fallback and output guards all
live in the app ([`triage.py`](triage.py)), so they are tested the same way regardless of
which provider is behind them.

## Fault injection

Faults are switched on in two places:

1. **`faults.json`** at the repo root, read at startup. Edit it and call `POST /faults/reload`,
   or use `PUT /faults` with a body like `{"llm_timeout": true}`.
2. **The `X-Fault` request header**, which overrides the file for one request:
   `X-Fault: llm_timeout,pii_leak` enables two faults, `X-Fault: -llm_timeout` disables one
   that is on globally, and `X-Fault: none` clears everything for that request.

Unknown fault names are rejected with a 400 so a typo cannot silently test nothing.

Faults that change the provider's behaviour are applied by `FaultInjectingProvider`
([`providers/faulty.py`](providers/faulty.py)), a wrapper the service puts around the real
provider only when one of those faults is active. Faults that change the app's own behaviour
(`quota_exceeded`, `slow_response`) are applied in the service itself.

### Design rule

The app **degrades** when the LLM is the thing that failed and the caller can still get a
useful answer. It **fails loudly** when its own guardrails say stop. It **cannot see** some
faults at all, and those are the ones the resilience harness exists to catch.

### The faults

#### `llm_timeout`

The provider sleeps past the app's LLM timeout (`TRIAGE_LLM_TIMEOUT_SECONDS`).

Correct behaviour: `/triage` returns **200** after roughly the timeout, with
`source: "fallback"`, `degraded: true`, `degradation_reason: "llm_timeout"`. Priority comes
from keyword rules and is never `low`. Category is the last category the LLM gave that
asset (`category_from_cache`) or a keyword guess (`category_from_keywords`). Summary is the
ticket title. `/health` reports `status: "degraded"` with `llm.last_error: "llm_timeout"`
until the next successful call. `/metrics` counts the call under `llm_calls.failed` and
`llm_calls.fallbacks`.

#### `llm_rate_limit`

The provider raises a 429.

Correct behaviour: identical to `llm_timeout` but immediate, with
`degradation_reason: "llm_rate_limit"`. The app does not retry a 429 on the caller's time.

#### `llm_garbage`

The provider returns malformed JSON.

Correct behaviour: the app retries once (warning `llm_output_retried`), then falls back with
`degradation_reason: "llm_malformed_output"`. Both attempts' tokens are counted against the
budget. The retry is the only automatic retry the app does, because a malformed reply is the
one failure where a second attempt is cheap and often works with a real model.

#### `llm_hallucinate`

The provider returns well-formed JSON whose summary contradicts the ticket (it claims the
asset is fine and no work is needed).

Correct behaviour: the app returns it with **200**, `source: "llm"`, `degraded: false`.
**The app cannot detect this on its own.** That is the point. This fault exists to prove
that the groundedness check in the harness catches it, and to show the reviewer that
"the app returned 200" is not the same as "the app was right".

#### `quota_exceeded`

The token budget is reported as exhausted. The same path triggers for real once
`TRIAGE_TOKEN_BUDGET` is actually spent.

Correct behaviour: `/triage` returns **503** with `error: "token_budget_exhausted"` and a
`Retry-After` header, and makes no LLM call. `/health` reports `status: "degraded"`,
`llm.status: "quota_exceeded"`, and `token_budget.exhausted: true`. This one fails loudly
rather than falling back because a spent budget is an operational condition someone has to
act on, and silently serving fallbacks would hide it for the rest of the billing period.

#### `slow_response`

Adds `TRIAGE_SLOW_RESPONSE_SECONDS` (default 3) of latency before the request is handled.

Correct behaviour: `/triage` still returns a normal **200** with `source: "llm"`. The only
visible effect is latency: `latency_ms` on the response, the p95/p99 in `/metrics`, and
`probe_latency_ms` on `/health?probe=true`. A test for this fault is a test that the app
reports latency honestly, not a test that the app hides it.

#### `pii_leak`

The provider's summary echoes any email address or phone number found in the ticket. If the
ticket contains none, this fault has nothing to leak and does nothing.

Correct behaviour: the output guard in [`guards.py`](guards.py) replaces them with
`[redacted-email]` / `[redacted-phone]` before the response leaves the app, and adds the
warning `pii_redacted`. The raw values never appear in the response body. The guard runs on
every LLM response, not just when the fault is on, so a real model that ignores the "no PII"
instruction in the system prompt is handled the same way.

### Summary table

| Fault             | HTTP | `source`   | `degraded` | App can detect it | Where it shows                   |
| ----------------- | ---- | ---------- | ---------- | ----------------- | -------------------------------- |
| `llm_timeout`     | 200  | fallback   | yes        | yes               | `/health`, `/metrics.llm_calls`  |
| `llm_rate_limit`  | 200  | fallback   | yes        | yes               | `/health`, `/metrics.llm_calls`  |
| `llm_garbage`     | 200  | fallback   | yes        | yes, after retry  | `/health`, `warnings`            |
| `llm_hallucinate` | 200  | llm        | no         | **no**            | harness groundedness check only  |
| `quota_exceeded`  | 503  | none       | n/a        | yes               | `/health`, `Retry-After`         |
| `slow_response`   | 200  | llm        | no         | latency only      | `/metrics` percentiles           |
| `pii_leak`        | 200  | llm        | no         | yes, redacted     | `warnings: ["pii_redacted"]`     |

## Health semantics

`GET /health` is passive by default: it reports what the app has seen. `llm.status` is:

- `ok` when the last LLM call succeeded
- `degraded` when the last call failed and nothing has succeeded since
- `quota_exceeded` when the budget is spent (or the fault is on)
- `unreachable` when an active probe failed
- `unknown` when the app has not called the LLM yet and no probe was requested

`status` is `ok` for `ok` and `unknown`, and `degraded` otherwise. The app itself being down
is a connection error, not a health payload.

## Layout

```
app/
  main.py                 app factory, routes, middleware
  triage.py               prompt, parsing, retry, fallback, category cache
  faults.py               fault names, faults.json loading, X-Fault parsing
  guards.py               PII redaction, one-line summary
  heuristics.py           keyword rules shared by the fallback and the fake
  budget.py               token budget
  metrics.py              counts and percentiles
  health.py               provider status memory
  models.py               request/response schemas
  config.py               settings from environment
  logging_setup.py        JSON-lines logging
  providers/
    base.py               LLMProvider protocol and error types
    fake.py               offline deterministic provider
    anthropic_provider.py Anthropic SDK provider
    faulty.py             fault-injecting wrapper
```
