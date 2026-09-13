"""A short in-memory history of triage requests so individual records can be inspected."""

from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime

from app.models import ErrorResponse, Ticket, TriageRecord, TriageResponse

DEFAULT_CAPACITY = 100


class TriageHistory:
    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self._records: deque[TriageRecord] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def record(
        self,
        ticket: Ticket,
        faults: frozenset[str],
        status_code: int,
        response: TriageResponse | None = None,
        error: ErrorResponse | None = None,
    ) -> None:
        entry = TriageRecord(
            received_at=datetime.now(UTC).isoformat(timespec="milliseconds"),
            status_code=status_code,
            faults_applied=sorted(faults),
            ticket=ticket,
            response=response,
            error=error,
        )
        with self._lock:
            self._records.append(entry)

    def recent(self, limit: int) -> list[TriageRecord]:
        """Newest first."""
        with self._lock:
            return list(reversed(self._records))[:limit]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
