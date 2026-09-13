"""Collect findings during a harness run and fill in the REPORT.md template."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.groundedness import JudgeUsage
from harness.health_checks import HealthSummary
from harness.quota import QuotaMonitor
from tests.framework.budget import SpendLedger


@dataclass
class ReportCollector:
    provider: str = "unknown"
    judge: str = "unknown"
    health: HealthSummary | None = None
    degradation: list[dict[str, Any]] = field(default_factory=list)
    adversarial: list[dict[str, Any]] = field(default_factory=list)
    groundedness: list[dict[str, Any]] = field(default_factory=list)
    outcomes: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record_outcome(self, outcome: str) -> None:
        self.outcomes[outcome] += 1

    def render(
        self,
        template: Path,
        ledger: SpendLedger,
        quota: QuotaMonitor,
        judge_usage: JudgeUsage | None,
    ) -> str:
        passed = self.outcomes.get("passed", 0)
        failed = self.outcomes.get("failed", 0)
        skipped = self.outcomes.get("skipped", 0)
        result = "FAILED" if failed or quota.exceeded else "PASSED"
        values = {
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "provider": self.provider,
            "judge": self.judge,
            "result": result,
            "summary_line": f"{passed} passed, {failed} failed, {skipped} skipped.",
            "health_table": self._health_table(),
            "degradation_table": self._degradation_table(),
            "adversarial_table": self._adversarial_table(),
            "adversarial_failures": self._adversarial_failures(),
            "groundedness_table": self._groundedness_table(),
            "groundedness_failures": self._groundedness_failures(),
            "quota_line": quota.status_line(ledger),
            "quota_table": self._quota_table(ledger, quota),
            "judge_spend_line": self._judge_spend_line(judge_usage),
        }
        text = template.read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        return text

    # --- sections ---------------------------------------------------------------------

    def _health_table(self) -> str:
        h = self.health
        if h is None:
            return "_No health probes were run._"
        rows = [
            ("Provider / model", f"{h.provider} / {h.model}"),
            (
                "Reachable",
                "yes" if h.reachable else f"no ({h.failures} of {h.probes} probes failed)",
            ),
            (
                "Probe latency min / avg / max",
                f"{h.min_latency_ms:.2f} / {h.avg_latency_ms:.2f} / {h.max_latency_ms:.2f} ms",
            ),
        ]
        if h.errors:
            rows.append(("Errors", ", ".join(sorted(set(h.errors)))))
        return _table(["Check", "Value"], [[k, v] for k, v in rows])

    def _degradation_table(self) -> str:
        if not self.degradation:
            return "_No degradation results recorded._"
        rows = [
            [
                r["fault"],
                r["contract"],
                r["observed"],
                "pass" if r["passed"] else "**FAIL**",
            ]
            for r in sorted(self.degradation, key=lambda r: r["fault"])
        ]
        return _table(["Fault", "Contract", "Observed", "Verdict"], rows)

    def _adversarial_table(self) -> str:
        if not self.adversarial:
            return "_No adversarial payloads were run._"
        by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in self.adversarial:
            by_category[r["category"]].append(r)
        rows = []
        for category, results in sorted(by_category.items()):
            passed = sum(1 for r in results if r["passed"])
            rows.append([category, str(len(results)), str(passed), str(len(results) - passed)])
        return _table(["Category", "Payloads", "Safe", "Failed"], rows)

    def _adversarial_failures(self) -> str:
        failures = [r for r in self.adversarial if not r["passed"]]
        if not failures:
            return "All payloads handled."
        lines = ["Failures:", ""]
        for r in failures:
            lines.append(f"- `{r['category']}/{r['id']}`: {'; '.join(r['problems'])}")
        return "\n".join(lines)

    def _groundedness_table(self) -> str:
        if not self.groundedness:
            return "_No summaries were checked._"
        total = len(self.groundedness)
        grounded = sum(1 for r in self.groundedness if r["grounded"])
        injected = [r for r in self.groundedness if r["expected_grounded"] is False]
        caught = sum(1 for r in injected if not r["grounded"])
        rows = [
            ["Summaries checked", str(total)],
            ["Grounded", str(grounded)],
            ["Ungrounded", str(total - grounded)],
            [
                "Injected hallucinations caught",
                f"{caught} of {len(injected)}" if injected else "none injected",
            ],
        ]
        return _table(["Measure", "Count"], rows)

    def _groundedness_failures(self) -> str:
        wrong = [r for r in self.groundedness if r["grounded"] != r["expected_grounded"]]
        if not wrong:
            return "Every verdict matched expectations."
        lines = ["Verdicts that did not match expectations:", ""]
        for r in wrong:
            expected = "grounded" if r["expected_grounded"] else "ungrounded"
            got = "grounded" if r["grounded"] else "ungrounded"
            lines.append(f"- `{r['test']}`: expected {expected}, got {got} ({r['rationale']})")
            lines.append(f"  - ticket: {r['ticket_title']}")
            lines.append(f"  - summary: {r['summary']}")
        return "\n".join(lines)

    def _quota_table(self, ledger: SpendLedger, quota: QuotaMonitor) -> str:
        if not ledger.by_test:
            return "_No spend recorded._"
        hot = {test for test, _ in quota.hot_spots(ledger)}
        rows = [
            [test, str(spent), "hot spot" if test in hot else ""] for test, spent in ledger.top(10)
        ]
        return _table(["Test (top 10 by spend)", "Tokens", ""], rows)

    @staticmethod
    def _judge_spend_line(usage: JudgeUsage | None) -> str:
        if usage is None or usage.calls == 0:
            return "The groundedness judge made no API calls."
        line = (
            f"The groundedness judge made {usage.calls} API calls and spent "
            f"{usage.total_tokens} tokens. Judge spend is not counted against the app budget."
        )
        if usage.failures:
            line += f" {len(usage.failures)} judge calls failed and fell back to keywords."
        return line


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)
