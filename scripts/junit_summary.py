"""Turn pytest JUnit XML into a short Markdown summary for the CI job page.

    uv run python scripts/junit_summary.py --title "Smoke" reports/junit-smoke.xml
    uv run python scripts/junit_summary.py --quarantine --title "Flaky" reports/junit-flaky.xml

A missing file is reported, not an error, so a step that produced no XML still summarises.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Suite:
    name: str
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    seconds: float = 0.0
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return self.tests - self.failures - self.errors - self.skipped


def parse(path: Path) -> list[Suite]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    parsed: list[Suite] = []
    for node in suites:
        suite = Suite(
            name=node.get("name", path.stem),
            tests=int(node.get("tests", 0)),
            failures=int(node.get("failures", 0)),
            errors=int(node.get("errors", 0)),
            skipped=int(node.get("skipped", 0)),
            seconds=float(node.get("time", 0.0)),
        )
        for case in node.iter("testcase"):
            problem = case.find("failure")
            if problem is None:
                problem = case.find("error")
            if problem is not None:
                message = (problem.get("message") or problem.text or "").strip().splitlines()
                first = message[0] if message else ""
                suite.problems.append(f"{case.get('classname')}::{case.get('name')}: {first}")
        parsed.append(suite)
    return parsed


def render(title: str, files: list[Path], quarantine: bool) -> str:
    lines = [f"## {title}", ""]
    if quarantine:
        lines += ["These tests are marked `flaky`. They run but do not block the pipeline.", ""]
    lines += [
        "| Suite | Tests | Passed | Failed | Errors | Skipped | Time |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    problems: list[str] = []
    any_tests = False
    for path in files:
        if not path.exists():
            lines.append(f"| {path.name} | _no results file_ | | | | | |")
            continue
        for suite in parse(path):
            any_tests = any_tests or suite.tests > 0
            lines.append(
                f"| {suite.name} | {suite.tests} | {suite.passed} | {suite.failures} | "
                f"{suite.errors} | {suite.skipped} | {suite.seconds:.1f}s |"
            )
            problems.extend(suite.problems)
    if not any_tests:
        lines += ["", "_No tests ran._"]
    if problems:
        lines += ["", "Failures:", ""]
        lines += [f"- `{p}`" for p in problems]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--title", default="Test results")
    parser.add_argument("--quarantine", action="store_true", help="label as non-blocking")
    args = parser.parse_args(argv)
    print(render(args.title, args.files, args.quarantine))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
