"""Review drafted tests: run them, and inspect them for weakness and duplication.

Static checks (via the ast module, so nothing is imported or executed):
  - no assertions            the test cannot fail for a behavioural reason
  - only trivial assertions  `assert True`, `assert x is not None`, bare truthiness...
  - no marker                the framework requires a suite marker
  - duplicate coverage       same coverage fingerprint as another generated or existing test

A coverage fingerprint is the set of HTTP calls made, status codes asserted, response
fields asserted, and faults used. Two tests with the same fingerprint check the same thing.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from app.faults import ALL_FAULTS  # only for recognising fault-name strings

CLIENT_CALLS = frozenset(
    {"get", "post", "put", "request", "triage", "triage_raw", "triage_healthy", "health",
     "metrics", "recent", "get_faults", "set_faults"}
)  # fmt: skip


@dataclass
class TestInfo:
    name: str
    file: Path
    lineno: int
    assertions: int = 0
    trivial_assertions: int = 0
    marked: bool = False
    fingerprint: frozenset[str] = frozenset()
    weaknesses: list[str] = field(default_factory=list)

    @property
    def nodeid(self) -> str:
        return f"{self.file.as_posix()}::{self.name}"


@dataclass
class RunResult:
    outcome: str  # passed / failed / error / skipped / missing
    message: str = ""
    seconds: float = 0.0


# --- static analysis --------------------------------------------------------------------


def analyze_file(path: Path) -> list[TestInfo]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_marked = any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
        for node in tree.body
    )
    tests: list[TestInfo] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.name.startswith("test"):
            continue
        info = TestInfo(name=node.name, file=path, lineno=node.lineno)
        info.marked = module_marked or any(_is_mark(d) for d in node.decorator_list)
        _inspect_body(node, info)
        info.weaknesses = _weaknesses(info, node)
        tests.append(info)
    return tests


def _is_mark(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(target, ast.Attribute) and "pytest.mark" in ast.unparse(target)


def _inspect_body(func: ast.FunctionDef | ast.AsyncFunctionDef, info: TestInfo) -> None:
    prints: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            info.assertions += 1
            if _is_trivial(node.test):
                info.trivial_assertions += 1
            prints.update(_assertion_facts(node.test))
        elif isinstance(node, ast.Call):
            callee = node.func
            if isinstance(callee, ast.Attribute) and callee.attr in CLIENT_CALLS:
                first = node.args[0] if node.args else None
                path = first.value if isinstance(first, ast.Constant) else ""
                path = path if isinstance(path, str) else ""
                prints.add(f"call:{callee.attr} {path}".strip())
        elif isinstance(node, ast.Constant) and node.value in ALL_FAULTS:
            prints.add(f"fault:{node.value}")
    # Parametrize values are part of what a test covers, even though they sit outside
    # the body. Without them, two parametrized 422 tests look identical.
    for decorator in func.decorator_list:
        if isinstance(decorator, ast.Call) and "parametrize" in ast.unparse(decorator.func):
            for node in ast.walk(decorator):
                if isinstance(node, ast.Constant) and _is_param_value(node.value):
                    prints.add(f"param:{str(node.value)[:40]}")
    info.fingerprint = frozenset(prints)


def _is_param_value(value: object) -> bool:
    return isinstance(value, str | int) and not isinstance(value, bool)


def _assertion_facts(test: ast.expr) -> set[str]:
    """What an assertion is about: fields, status codes, operators, literal values."""
    facts: set[str] = set()
    for node in ast.walk(test):
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, int) and 100 <= value < 600:
                facts.add(f"status:{value}")
            elif isinstance(value, int | float | str):
                facts.add(f"const:{str(value)[:40]}")
        elif isinstance(node, ast.Attribute):
            facts.add(f"field:{node.attr}")
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                facts.add(f"field:{node.slice.value}")
        elif isinstance(node, ast.Compare):
            facts.update(f"cmp:{type(op).__name__}" for op in node.ops)
    return facts


def _is_trivial(test: ast.expr) -> bool:
    if isinstance(test, ast.Constant):
        return True  # assert True / assert 1
    if isinstance(test, ast.Name | ast.Attribute):
        return True  # assert response  (bare truthiness)
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        left, op, right = test.left, test.ops[0], test.comparators[0]
        if isinstance(left, ast.Constant) and isinstance(right, ast.Constant):
            return True  # assert 1 == 1
        if isinstance(op, ast.IsNot) and isinstance(right, ast.Constant) and right.value is None:
            return True  # assert x is not None
        if (
            isinstance(left, ast.Call)
            and isinstance(left.func, ast.Name)
            and left.func.id == "len"
            and isinstance(op, ast.GtE)
            and isinstance(right, ast.Constant)
            and right.value == 0
        ):
            return True  # assert len(x) >= 0
    return False


def _weaknesses(info: TestInfo, func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    found: list[str] = []
    uses_raises = any(
        isinstance(n, ast.Call) and "raises" in ast.unparse(n.func) for n in ast.walk(func)
    )
    if info.assertions == 0 and not uses_raises:
        found.append("no assertions")
    elif info.assertions > 0 and info.assertions == info.trivial_assertions:
        found.append("only trivial assertions")
    if not info.marked:
        found.append("no suite marker")
    return found


def flag_duplicates(drafted: list[TestInfo], existing: list[TestInfo]) -> None:
    """Annotate drafted tests whose fingerprint matches an existing or earlier drafted test."""
    seen: dict[frozenset[str], TestInfo] = {}
    for test in existing:
        if test.fingerprint:
            seen.setdefault(test.fingerprint, test)
    for test in drafted:
        if not test.fingerprint:
            continue
        match = seen.get(test.fingerprint)
        if match is not None:
            where = "existing" if match.file != test.file else "drafted"
            test.weaknesses.append(f"duplicates {where} test {match.nodeid}")
        else:
            seen[test.fingerprint] = test


def analyze_tree(root: Path) -> list[TestInfo]:
    tests: list[TestInfo] = []
    for path in sorted(root.rglob("test_*.py")):
        tests.extend(analyze_file(path))
    return tests


def describe_fingerprint(test: TestInfo) -> str:
    return ", ".join(sorted(test.fingerprint)) or "(no calls or assertions recognised)"


# --- running ----------------------------------------------------------------------------


def run_pytest(
    paths: list[Path], junit_path: Path, cwd: Path, extra_args: list[str] | None = None
) -> dict[str, RunResult]:
    """Run pytest on the drafts. `extra_args` is where the caller pins the project's
    config, rootdir and fixture plugin, so drafts outside the repo still get them."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *[str(p) for p in paths],
        "-q",
        "-p",
        "no:cacheprovider",
        "-o",
        "junit_family=xunit1",
        f"--junitxml={junit_path}",
        *(extra_args or []),
    ]
    subprocess.run(cmd, cwd=cwd, capture_output=True, check=False)
    if not junit_path.exists():
        return {}
    return aggregate(parse_junit(junit_path))


def parse_junit(junit_path: Path) -> dict[str, RunResult]:
    """One entry per test case as pytest names it, parameters included."""
    results: dict[str, RunResult] = {}
    for case in ET.parse(junit_path).getroot().iter("testcase"):
        name = case.get("name", "")
        seconds = float(case.get("time", 0.0))
        problem = case.find("failure")
        if problem is not None:
            results[name] = RunResult("failed", _first_line(problem), seconds)
            continue
        problem = case.find("error")
        if problem is not None:
            results[name] = RunResult("error", _first_line(problem), seconds)
            continue
        if case.find("skipped") is not None:
            results[name] = RunResult("skipped", "", seconds)
            continue
        results[name] = RunResult("passed", "", seconds)
    return results


def aggregate(results: dict[str, RunResult]) -> dict[str, RunResult]:
    """Fold parametrized cases (`test_x[a]`, `test_x[b]`) into one result per function.
    Any failure fails the function; the message names how many cases failed."""
    grouped: dict[str, list[RunResult]] = {}
    for name, result in results.items():
        grouped.setdefault(name.split("[", 1)[0], []).append(result)
    folded: dict[str, RunResult] = {}
    for name, cases in grouped.items():
        seconds = sum(c.seconds for c in cases)
        bad = [c for c in cases if c.outcome in ("failed", "error")]
        if bad:
            note = bad[0].message
            if len(cases) > 1:
                note = f"{len(bad)} of {len(cases)} cases: {note}"
            folded[name] = RunResult(bad[0].outcome, note, seconds)
        elif all(c.outcome == "skipped" for c in cases):
            folded[name] = RunResult("skipped", "", seconds)
        else:
            note = f"{len(cases)} cases" if len(cases) > 1 else ""
            folded[name] = RunResult("passed", note, seconds)
    return folded


def _first_line(node: ET.Element) -> str:
    text = (node.get("message") or node.text or "").strip()
    return text.splitlines()[0][:200] if text else ""
