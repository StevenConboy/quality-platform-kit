"""Tracks what the app has observed about the LLM provider recently."""

from __future__ import annotations

import threading
from datetime import UTC, datetime


class ProviderStatus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.last_error: str | None = None
        self.last_success_at: datetime | None = None
        self.consecutive_failures = 0

    def record_success(self) -> None:
        with self._lock:
            self.last_error = None
            self.last_success_at = datetime.now(UTC)
            self.consecutive_failures = 0

    def record_failure(self, reason: str) -> None:
        with self._lock:
            self.last_error = reason
            self.consecutive_failures += 1

    def reset(self) -> None:
        with self._lock:
            self.last_error = None
            self.last_success_at = None
            self.consecutive_failures = 0

    @property
    def healthy(self) -> bool:
        return self.consecutive_failures == 0
