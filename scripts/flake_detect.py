"""Run a test suite several times and report tests whose result changes between runs.

    uv run python scripts/flake_detect.py --suite tests --runs 5
    uv run python scripts/flake_detect.py --suite harness --runs 3 -m "not slow"
    uv run python scripts/flake_detect.py --suite tests --runs 5 --apply

A test is flaky if it passed in at least one run and failed or errored in at least one
other. Skipped runs are ignored. With --apply, each flaky test gets

    @pytest.mark.flaky  # quarantined YYYY-MM-DD by scripts/flake_detect.py: failed 2 of 5 runs

inserted above its definition, which the CI quarantine rule then honours. Nothing is
committed; review the diff.

Exit code is 0 whether or not flaky tests were found. When run inside GitHub Actions the
count is written to $GITHUB_OUTPUT as flaky_count so a workflow can branch on it.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKER_RE = re.compile(r"^\s*@pytest\.mark\.flaky\b")


@dataclass(frozen=True)
class Flaky:
    file: str
    name: str  # test function name, parameters included
    outcomes: list[str]

    @property
    def nodeid(self) -> str:
        return f"{self.file}::{self.name}"

    @property
    def function(self) -> str:
        """Bare function name: parameters and any class prefix stripped."""
        return self.name.split("[", 1)[0].rsplit("::", 1)[-1]

    @property
    def failed_runs(self) -> int:
        return sum(1 for o in self.outcomes if o in ("failed", "error"))


def run_once(suite: str, marker: str | None, extra: list[str], xml_path: Path) -> None:
    """One pytest run. The exit code is deliberately ignored; the XML is what matters."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        suite,
        "-q",
        "-p",
        "no:cacheprovider",
        "-o",
        "junit_family=xunit1",  # xunit1 includes the file attribute we need for --apply
        f"--junitxml={xml_path}",
    ]
    if marker:
        cmd += ["-m", marker]
    cmd += extra
    subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, check=False)


def parse_results(xml_path: Path) -> dict[tuple[str, str], str]:
    """Map (file, name) to passed / failed / error / skipped."""
    results: dict[tuple[str, str], str] = {}
    if not xml_path.exists():
        return results
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        file = case.get("file") or case.get("classname", "").replace(".", "/") + ".py"
        file = file.replace("\\", "/")  # same nodeid on every OS
        name = case.get("name", "")
        if case.find("failure") is not None:
            outcome = "failed"
        elif case.find("error") is not None:
            outcome = "error"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        results[(file, name)] = outcome
    return results


def find_flaky(runs: list[dict[tuple[str, str], str]]) -> list[Flaky]:
    by_test: dict[tuple[str, str], list[str]] = defaultdict(list)
    for run in runs:
        for key, outcome in run.items():
            by_test[key].append(outcome)
    flaky = []
    for (file, name), outcomes in sorted(by_test.items()):
        seen = set(outcomes) - {"skipped"}
        if "passed" in seen and seen & {"failed", "error"}:
            flaky.append(Flaky(file, name, outcomes))
    return flaky


def render_report(suite: str, runs: int, total_tests: int, flaky: list[Flaky], date: str) -> str:
    lines = [
        "# Flake detection report",
        "",
        f"Suite `{suite}` run {runs} times on {date}. {total_tests} tests seen.",
        "",
    ]
    if not flaky:
        lines += ["No inconsistent results. Nothing to quarantine.", ""]
        return "\n".join(lines)
    lines += [
        f"{len(flaky)} test(s) had inconsistent results:",
        "",
        "| Test | Failed runs | Outcomes in order |",
        "| --- | ---: | --- |",
    ]
    for f in flaky:
        lines.append(f"| `{f.nodeid}` | {f.failed_runs} of {runs} | {' '.join(f.outcomes)} |")
    lines += [
        "",
        "To quarantine them so they stop blocking the pipeline:",
        "",
        "```",
        f"uv run python scripts/flake_detect.py --suite {suite} --runs {runs} --apply",
        "```",
        "",
    ]
    return "\n".join(lines)


def apply_markers(flaky: list[Flaky], runs: int, date: str) -> list[str]:
    """Insert the flaky marker above each affected test function. Returns a change log."""
    changes: list[str] = []
    # One marker per function. A parametrized test records its worst case.
    worst: dict[tuple[str, str], int] = {}
    for f in flaky:
        key = (f.file, f.function)
        worst[key] = max(worst.get(key, 0), f.failed_runs)
    by_file: dict[str, dict[str, int]] = defaultdict(dict)
    for (file, function), failed in worst.items():
        by_file[file][function] = failed

    for file, functions in by_file.items():
        path = REPO_ROOT / file
        if not path.exists():
            changes.append(f"skipped {file}: not found")
            continue
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for function, failed in functions.items():
            def_re = re.compile(rf"^(?P<indent>\s*)(async\s+)?def\s+{re.escape(function)}\s*\(")
            index = next((i for i, line in enumerate(lines) if def_re.match(line)), None)
            if index is None:
                changes.append(f"skipped {file}::{function}: definition not found")
                continue
            if _already_marked(lines, index):
                changes.append(f"unchanged {file}::{function}: already marked flaky")
                continue
            indent = def_re.match(lines[index]).group("indent")  # type: ignore[union-attr]
            marker = (
                f"{indent}@pytest.mark.flaky  # quarantined {date} by scripts/flake_detect.py: "
                f"failed {failed} of {runs} runs\n"
            )
            lines.insert(index, marker)
            changes.append(f"marked {file}::{function}")
        if not any(line.startswith("import pytest") for line in lines):
            first_import = next(
                (i for i, line in enumerate(lines) if line.startswith(("import ", "from "))), 0
            )
            lines.insert(first_import, "import pytest\n")
        path.write_text("".join(lines), encoding="utf-8")
    return changes


def _already_marked(lines: list[str], def_index: int) -> bool:
    """Look upward from the def through its decorators for an existing flaky marker."""
    i = def_index - 1
    while i >= 0 and lines[i].lstrip().startswith("@"):
        if MARKER_RE.match(lines[i]):
            return True
        i -= 1
    return False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run a suite N times and report inconsistent tests.",
        epilog="Anything after -- is passed to pytest.",
    )
    parser.add_argument("--suite", default="tests", help="path pytest should collect")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("-m", "--marker", help="pytest -m expression, e.g. 'not slow'")
    parser.add_argument("--apply", action="store_true", help="insert @pytest.mark.flaky")
    parser.add_argument("--report", type=Path, help="write the Markdown report here too")
    parser.add_argument("pytest_args", nargs="*")
    args = parser.parse_args(argv)

    date = datetime.now(UTC).date().isoformat()
    with tempfile.TemporaryDirectory(prefix="flake-detect-") as tmp:
        runs = []
        for n in range(1, args.runs + 1):
            print(f"run {n} of {args.runs} ...", file=sys.stderr)
            xml_path = Path(tmp) / f"run-{n}.xml"
            run_once(args.suite, args.marker, args.pytest_args, xml_path)
            runs.append(parse_results(xml_path))

    flaky = find_flaky(runs)
    total_tests = len({key for run in runs for key in run})
    report = render_report(args.suite, args.runs, total_tests, flaky, date)
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")

    if args.apply and flaky:
        for change in apply_markers(flaky, args.runs, date):
            print(change)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"flaky_count={len(flaky)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
