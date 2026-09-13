"""Flip faults on and off through the app's /faults endpoint, and prove they are off."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.faults import ALL_FAULTS
from tests.framework.client import TriageClient
from tests.framework.structured_log import StructuredLogger


class FaultToggler:
    def __init__(self, client: TriageClient, log: StructuredLogger) -> None:
        self.client = client
        self.log = log

    def state(self) -> dict[str, bool]:
        return self.client.get_faults()

    def enable(self, *names: str) -> None:
        self._check_names(names)
        self.log.step("fault on", faults=list(names))
        self.client.set_faults(**dict.fromkeys(names, True))

    def disable(self, *names: str) -> None:
        self._check_names(names)
        self.log.step("fault off", faults=list(names))
        self.client.set_faults(**dict.fromkeys(names, False))

    def clear(self) -> None:
        self.client.set_faults(**dict.fromkeys(ALL_FAULTS, False))

    @contextmanager
    def enabled(self, *names: str) -> Iterator[None]:
        """Enable faults for the duration of a block, then switch them off again."""
        self.enable(*names)
        try:
            yield
        finally:
            self.disable(*names)

    def assert_off(self, *names: str) -> None:
        """Prove the faults are not on globally before a test flips them.

        A test that skips this step can pass for the wrong reason: if the fault was
        already on, the "before" and "after" behaviour are the same.
        """
        self._check_names(names)
        state = self.state()
        still_on = [name for name in names if state[name]]
        assert not still_on, f"faults already enabled before the test started: {still_on}"
        self.log.step("fault proven off", faults=list(names))

    @staticmethod
    def _check_names(names: tuple[str, ...]) -> None:
        unknown = set(names) - ALL_FAULTS
        assert not unknown, f"unknown faults {sorted(unknown)}; known: {sorted(ALL_FAULTS)}"
