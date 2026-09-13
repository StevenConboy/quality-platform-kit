# AI-assisted test authoring

Drafts pytest cases for one endpoint from its OpenAPI description, runs them, and writes a
review report saying which passed, which failed, and which look weak. A person reads the
report and decides what to keep. Nothing is merged automatically.

## Running it

From the repo root, with `ANTHROPIC_API_KEY` in your environment or in `.env`:

```bash
uv run authoring export-spec --out openapi.json
uv run authoring generate --spec openapi.json --endpoint /triage
```

That writes three things into `authoring/review/triage/`:

- `test_triage_drafted.py`, the drafted tests
- `REVIEW.md`, the report
- `prompt_used.md` and `generation.json`, the exact prompt, model, and token counts, so a
  draft can be reproduced or questioned later

Without a key, or to see the report format without spending tokens, hand it a draft file
instead of calling the model. The repo includes one with a deliberate mix of good and bad
tests:

```bash
uv run authoring generate --spec openapi.json --endpoint /triage --draft authoring/examples/triage_draft.py
```

Re-run the review on an existing folder after editing drafts by hand:

```bash
uv run authoring review authoring/review/triage
```

Options for `generate`: `--count` (how many tests to ask for, default 6), `--model`,
`--out` (review folder root). `--spec` accepts a file path or an http(s) URL, so it works
for any service with an OpenAPI document, not only this one; `export-spec` is a
convenience for this repo's app.

## What the review report says

Each drafted test gets a row:

| Column | Meaning |
| --- | --- |
| Ran | passed, failed with the first line of the error, error, or missing |
| Weaknesses | what the static review found, see below |
| Verdict | ready for review, needs work, investigate, or discard |

The static review reads the test with Python's `ast` module, never importing it:

- **no assertions**: the test cannot fail for a behavioural reason.
- **only trivial assertions**: `assert True`, `assert x is not None`, bare truthiness,
  `len(x) >= 0`. The test can only fail on an exception.
- **no suite marker**: the framework requires `smoke`, `regression`, etc.
- **duplicates existing test ...**: the test has the same coverage fingerprint as one
  already in `tests/`. A fingerprint is the set of HTTP calls made, status codes and
  literal values asserted, comparison operators, response fields asserted, faults used,
  and parametrize values. Two tests with equal fingerprints check the same thing,
  whatever their names say. The match is exact on purpose: overlapping-but-different
  coverage is left for the reviewer, and the report lists every fingerprint to help.

A failing draft is marked "investigate", not "discard". Generated tests fail for two
reasons: the test is wrong, or it found something. The report cannot tell which, and
should not pretend to.

## The prompt

[`prompt.md`](prompt.md) is the system prompt. Edit it to change what the model is told
about style, assertions, or what to avoid. `{{count}}` is filled in at run time. The user
message is built from the endpoint's spec, the framework README (`tests/README.md`), one
existing test file as a style example, and the names and fingerprints of every existing
test so the model can steer away from them. `prompt_used.md` in the review folder holds
the full text that was sent.

## How this differs from using Copilot

Copilot is excellent at the typing. This tool is about everything around the typing.

**It is grounded in the contract, not the cursor.** Copilot completes from whatever is on
screen. This reads the OpenAPI document, so it tests documented status codes, schemas and
parameters, including ones no test file mentions yet.

**It knows the house style.** The framework's README, a real test file, and the marker and
fixture conventions go into every request. Drafts arrive using `client`, `faults`,
`assert_off`, and `pytestmark`, not a fresh `requests.post` and a hand-rolled base URL.

**It knows what already exists.** Every existing test's coverage fingerprint is in the
prompt, and the static review checks the output against them anyway. Copilot will happily
write the fifth test of "422 on missing field".

**It runs what it wrote and grades it.** Passed, failed, no assertions, trivial assertions,
duplicate. Copilot's output is done when it stops typing; this tool's output is done when
there is a report a reviewer can act on.

**It leaves a paper trail.** The prompt, model, token counts and the review live next to the
drafts. Six months later you can see why a test exists and what it was checked against.

**It never merges.** The review folder is gitignored. Promotion is a person copying a test
into `tests/` and taking responsibility for it.

## Layout

```
authoring/
  cli.py            generate / review / export-spec
  spec.py           OpenAPI loading, $ref inlining, endpoint rendering
  prompt.md         the editable system prompt
  generator.py      Anthropic SDK call and code extraction
  review.py         static analysis (weakness, fingerprints, duplicates) and pytest runner
  report.py         REVIEW.md rendering and verdicts
  examples/         a hand-written draft for offline demos and tests
  review/           output, gitignored
```

The package imports nothing from `app/` except the fault-name list, used to recognise
fault strings in fingerprints; `export-spec` imports the app only because it is a
convenience for this repo. Lifting the tool into its own repository means copying the
folder and pointing `--spec` at a URL.
