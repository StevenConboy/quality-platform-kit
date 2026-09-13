"""Write the review report for a batch of drafted tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from authoring.review import RunResult, TestInfo, describe_fingerprint


@dataclass(frozen=True)
class Reviewed:
    test: TestInfo
    run: RunResult

    @property
    def verdict(self) -> str:
        if any(w.startswith("duplicates") for w in self.test.weaknesses):
            return "discard: duplicate coverage"
        if self.run.outcome in ("failed", "error"):
            return "investigate: failed (the test or the app may be wrong)"
        if self.run.outcome == "missing":
            return "investigate: did not run"
        if self.test.weaknesses:
            return "needs work"
        return "ready for review"


def review_all(tests: list[TestInfo], runs: dict[str, RunResult]) -> list[Reviewed]:
    return [Reviewed(t, runs.get(t.name, RunResult("missing"))) for t in tests]


def render_report(
    endpoint: str,
    module: Path,
    reviewed: list[Reviewed],
    meta: dict[str, str],
) -> str:
    counts = {
        "ready for review": 0,
        "needs work": 0,
        "investigate": 0,
        "discard": 0,
    }
    for r in reviewed:
        counts[r.verdict.split(":")[0]] += 1

    lines = [
        f"# Review: drafted tests for {endpoint}",
        "",
        f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} into `{_rel(module)}`.",
        "",
        "| | |",
        "| --- | --- |",
    ]
    lines += [f"| {key} | {value} |" for key, value in meta.items()]
    lines += [
        "",
        f"**{len(reviewed)} tests drafted**: {counts['ready for review']} ready for review, "
        f"{counts['needs work']} need work, {counts['investigate']} to investigate, "
        f"{counts['discard']} to discard.",
        "",
        "Nothing here is merged automatically. To adopt a test, copy it into the right file "
        "under `tests/`, keep or tighten its assertions, and run the suite.",
        "",
        "## Verdicts",
        "",
        "| Test | Ran | Weaknesses | Verdict |",
        "| --- | --- | --- | --- |",
    ]
    for r in reviewed:
        ran = r.run.outcome
        if r.run.message:
            ran += f": {r.run.message}"
        weak = "; ".join(_relativise(w) for w in r.test.weaknesses) or "none"
        lines.append(f"| `{r.test.name}` | {ran} | {weak} | {r.verdict} |")

    lines += [
        "",
        "## Coverage fingerprints",
        "",
        "What each test calls and asserts on, which is how duplicates are found.",
        "",
    ]
    for r in reviewed:
        lines.append(f"- `{r.test.name}`: {describe_fingerprint(r.test)}")
    lines.append("")
    return "\n".join(lines)


def _rel(path: Path) -> str:
    """Repo-relative when possible; reports should not carry one machine's absolute paths."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _relativise(text: str) -> str:
    cwd = Path.cwd().resolve().as_posix() + "/"
    return text.replace(cwd, "")
