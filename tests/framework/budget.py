"""Track token spend per test by reading the app's /metrics before and after."""

from __future__ import annotations

from tests.framework.client import TriageClient


class TokenTracker:
    def __init__(self, client: TriageClient, test_id: str) -> None:
        self.client = client
        self.test_id = test_id
        self.start = client.metrics().tokens.spent
        self.end: int | None = None

    @property
    def spent(self) -> int:
        """Tokens spent since the tracker started (live, until finish() is called)."""
        current = self.end if self.end is not None else self.client.metrics().tokens.spent
        return current - self.start

    def finish(self) -> int:
        self.end = self.client.metrics().tokens.spent
        return self.spent

    def assert_under(self, limit: int) -> None:
        spent = self.spent
        assert spent <= limit, f"{self.test_id} spent {spent} tokens, limit is {limit}"


class SpendLedger:
    """Session-wide record of spend per test, printed at the end of the run."""

    def __init__(self) -> None:
        self.by_test: dict[str, int] = {}

    def record(self, test_id: str, spent: int) -> None:
        self.by_test[test_id] = spent

    @property
    def total(self) -> int:
        return sum(self.by_test.values())

    def top(self, n: int = 10) -> list[tuple[str, int]]:
        return sorted(self.by_test.items(), key=lambda item: item[1], reverse=True)[:n]
