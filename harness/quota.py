"""Token quota monitor: fail the run when spend crosses the configured budget."""

from __future__ import annotations

from dataclasses import dataclass

from tests.framework.budget import SpendLedger


@dataclass
class QuotaMonitor:
    run_budget: int
    per_test_budget: int
    exceeded_at: str | None = None  # test id during which the budget was crossed

    def observe(self, ledger: SpendLedger, test_id: str) -> bool:
        """Record the latest total. Returns True the first time the budget is crossed."""
        if self.exceeded_at is None and ledger.total > self.run_budget:
            self.exceeded_at = test_id
            return True
        return False

    @property
    def exceeded(self) -> bool:
        return self.exceeded_at is not None

    def hot_spots(self, ledger: SpendLedger) -> list[tuple[str, int]]:
        return [(test, spent) for test, spent in ledger.top(100) if spent > self.per_test_budget]

    def status_line(self, ledger: SpendLedger) -> str:
        state = "EXCEEDED" if self.exceeded else "within budget"
        return f"{ledger.total} of {self.run_budget} tokens spent ({state})"
