"""Regression: the flake detector's decision and marker logic (no pytest subprocesses)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import flake_detect

pytestmark = pytest.mark.regression

FILE = "tests/example/test_thing.py"


def test_inconsistent_results_are_flaky_and_consistent_ones_are_not() -> None:
    runs = [
        {(FILE, "test_a"): "passed", (FILE, "test_b"): "failed", (FILE, "test_c"): "passed"},
        {(FILE, "test_a"): "failed", (FILE, "test_b"): "failed", (FILE, "test_c"): "skipped"},
        {(FILE, "test_a"): "passed", (FILE, "test_b"): "failed", (FILE, "test_c"): "passed"},
    ]

    flaky = flake_detect.find_flaky(runs)

    assert [f.name for f in flaky] == ["test_a"]
    assert flaky[0].failed_runs == 1
    assert flaky[0].outcomes == ["passed", "failed", "passed"]


def test_apply_inserts_a_dated_marker_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "test_sample.py"
    source.write_text(
        "import pytest\n\n\n"
        "@pytest.mark.parametrize('n', [1, 2])\n"
        "def test_wobbly(n):\n"
        "    assert n\n\n\n"
        "class TestGroup:\n"
        "    def test_inner(self):\n"
        "        assert True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(flake_detect, "REPO_ROOT", tmp_path)
    flaky = [
        flake_detect.Flaky("test_sample.py", "test_wobbly[1]", ["passed", "failed", "passed"]),
        flake_detect.Flaky("test_sample.py", "test_wobbly[2]", ["failed", "failed", "passed"]),
        flake_detect.Flaky("test_sample.py", "TestGroup::test_inner", ["passed", "error"]),
    ]

    first = flake_detect.apply_markers(flaky, runs=3, date="2026-09-13")
    second = flake_detect.apply_markers(flaky, runs=3, date="2026-09-13")
    text = source.read_text(encoding="utf-8")

    assert first == ["marked test_sample.py::test_wobbly", "marked test_sample.py::test_inner"]
    assert all(change.startswith("unchanged") for change in second)
    assert text.count("@pytest.mark.flaky") == 2
    assert "failed 2 of 3 runs\ndef test_wobbly" in text  # worst case across parameters
    assert "    @pytest.mark.flaky  # quarantined 2026-09-13" in text  # indented for the class


def test_apply_adds_the_pytest_import_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "test_plain.py"
    source.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(flake_detect, "REPO_ROOT", tmp_path)

    flake_detect.apply_markers(
        [flake_detect.Flaky("test_plain.py", "test_x", ["passed", "failed"])], runs=2, date="d"
    )

    assert source.read_text(encoding="utf-8").startswith("import pytest\n")
