"""A deliberately unreliable test, for demonstrating flake detection and quarantine.

By default this test passes every time. Set SIMULATE_FLAKY=1 and it fails on a coin
flip. CI sets that variable only in the quarantine step (tests marked flaky, never
blocking), and the weekly flake-detection workflow has a "simulate flaky" input that
sets it so the detector has something to find.

Nothing else in the repo depends on this file. Delete it if the demo is not wanted.
"""

from __future__ import annotations

import os
import random

import pytest

pytestmark = pytest.mark.regression


def test_simulated_flake() -> None:
    if os.environ.get("SIMULATE_FLAKY") == "1":
        assert random.random() < 0.5, "simulated intermittent failure (SIMULATE_FLAKY=1)"
