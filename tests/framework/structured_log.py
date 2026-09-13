"""A small structured logger for tests.

Every line is JSON with the test id attached, so a failing test's log can be read on
its own or grepped out of a CI log. pytest captures it and prints it on failure.
"""

from __future__ import annotations

import json
import logging
from typing import Any


class StructuredLogger:
    def __init__(self, test_id: str, logger_name: str = "tests") -> None:
        self.test_id = test_id
        self._logger = logging.getLogger(logger_name)

    def _emit(self, level: int, event: str, fields: dict[str, Any]) -> None:
        payload = {"test": self.test_id, "event": event, **fields}
        self._logger.log(level, json.dumps(payload, default=str))

    def step(self, event: str, **fields: Any) -> None:
        """Record a step of the test, e.g. log.step("fault on", fault="llm_timeout")."""
        self._emit(logging.INFO, event, fields)

    def warn(self, event: str, **fields: Any) -> None:
        self._emit(logging.WARNING, event, fields)
