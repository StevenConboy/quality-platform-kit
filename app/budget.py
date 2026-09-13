"""Token budget tracking."""

from __future__ import annotations

import threading

from app.models import BudgetStatus, TokenUsage


class TokenBudget:
    """Counts tokens spent across all LLM calls and reports when the limit is reached."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._input = 0
        self._output = 0
        self._lock = threading.Lock()

    def record(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self._input += input_tokens
            self._output += output_tokens

    @property
    def spent(self) -> int:
        return self._input + self._output

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit

    def reset(self) -> None:
        with self._lock:
            self._input = 0
            self._output = 0

    def status(self, force_exhausted: bool = False) -> BudgetStatus:
        exhausted = self.exhausted or force_exhausted
        return BudgetStatus(
            limit=self.limit,
            spent=self.spent,
            remaining=0 if exhausted else max(self.limit - self.spent, 0),
            exhausted=exhausted,
        )

    def by_direction(self) -> TokenUsage:
        return TokenUsage(input_tokens=self._input, output_tokens=self._output)
