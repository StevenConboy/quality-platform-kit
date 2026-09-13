"""Regression: the authoring tool's spec reader, static reviewer and report. No model calls."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.main import create_app
from authoring.generator import extract_code, render_prompt
from authoring.review import RunResult, aggregate, analyze_file, analyze_tree, flag_duplicates
from authoring.spec import extract_operations, render_operations

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DRAFT = REPO_ROOT / "authoring" / "examples" / "triage_draft.py"


def test_spec_reader_describes_the_triage_endpoint() -> None:
    spec = create_app().openapi()

    ops = extract_operations(spec, "/triage")
    text = render_operations(ops)

    assert [op.method for op in ops] == ["POST"]
    assert ops[0].request_schema is not None
    assert "asset_id" in json.dumps(ops[0].request_schema)  # $ref was inlined
    assert "x-fault" in json.dumps(ops[0].parameters)
    assert set(ops[0].responses) >= {"200", "422", "503"}
    assert "### POST /triage" in text


def test_spec_reader_rejects_unknown_endpoint() -> None:
    with pytest.raises(KeyError, match="known paths"):
        extract_operations(create_app().openapi(), "/nope")


def test_static_review_flags_weak_tests() -> None:
    by_name = {t.name: t for t in analyze_file(EXAMPLE_DRAFT)}

    assert by_name["test_summary_exists"].weaknesses == ["no assertions"]
    assert by_name["test_triage_responds"].weaknesses == ["only trivial assertions"]
    assert by_name["test_missing_asset_id_is_rejected_with_422"].weaknesses == []
    assert "status:422" in by_name["test_missing_asset_id_is_rejected_with_422"].fingerprint
    assert "const:60" in by_name["test_summary_is_never_longer_than_100_characters"].fingerprint
    assert "fault:llm_rate_limit" in by_name["test_rate_limit_fault_produces_fallback"].fingerprint


def test_static_review_flags_duplicate_of_existing_test() -> None:
    drafted = analyze_file(EXAMPLE_DRAFT)
    existing = analyze_tree(REPO_ROOT / "tests" / "regression")

    flag_duplicates(drafted, existing)

    dup = next(t for t in drafted if t.name == "test_unknown_fault_header_is_rejected")
    assert any("duplicates existing" in w and "test_unknown_fault_name_is_rejected" in w
               for w in dup.weaknesses)  # fmt: skip
    clean = next(t for t in drafted if t.name == "test_rate_limit_fault_produces_fallback")
    assert not any(w.startswith("duplicates") for w in clean.weaknesses)


def test_parametrized_cases_fold_into_one_result() -> None:
    raw = {
        "test_a[x]": RunResult("passed", "", 0.1),
        "test_a[y]": RunResult("failed", "AssertionError: boom", 0.2),
        "test_a[z]": RunResult("passed", "", 0.1),
        "test_b[1]": RunResult("passed", "", 0.1),
        "test_b[2]": RunResult("passed", "", 0.1),
        "test_c": RunResult("passed", "", 0.1),
    }

    folded = aggregate(raw)

    assert folded["test_a"].outcome == "failed"
    assert folded["test_a"].message == "1 of 3 cases: AssertionError: boom"
    assert folded["test_b"] == RunResult("passed", "2 cases", 0.2)
    assert folded["test_c"].message == ""


def test_parametrize_values_are_part_of_the_fingerprint(tmp_path: Path) -> None:
    source = tmp_path / "test_params.py"
    source.write_text(
        "import pytest\n"
        "pytestmark = pytest.mark.regression\n"
        "@pytest.mark.parametrize('field', ['title', 'asset_id'])\n"
        "def test_x(client, ticket, field):\n"
        "    assert client.post('/triage', json_body=ticket).status_code == 422\n"
        "@pytest.mark.parametrize('n', [201, 4001])\n"
        "def test_y(client, ticket, n):\n"
        "    assert client.post('/triage', json_body=ticket).status_code == 422\n"
    )

    x, y = analyze_file(source)

    assert {"param:title", "param:asset_id"} <= x.fingerprint
    assert x.fingerprint != y.fingerprint


def test_unmarked_module_is_flagged(tmp_path: Path) -> None:
    source = tmp_path / "test_unmarked.py"
    source.write_text("def test_x(client):\n    assert client.health().status == 'ok'\n")

    (info,) = analyze_file(source)

    assert info.weaknesses == ["no suite marker"]


def test_prompt_rendering_and_code_extraction() -> None:
    assert (
        render_prompt("write {{count}} tests {{unknown}}", count="3") == "write 3 tests {{unknown}}"
    )
    text = "Here you go:\n```python\nimport pytest\n\ndef test_a() -> None:\n    pass\n```\nBye."
    assert extract_code(text).startswith("import pytest")
    assert extract_code("no fence here") == "no fence here\n"


def test_end_to_end_review_from_draft_file(tmp_path: Path) -> None:
    """The CLI with --draft: no model, real pytest run, real report."""
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(create_app().openapi()))

    result = subprocess.run(
        [
            sys.executable, "-m", "authoring", "generate",
            "--spec", str(spec_path), "--endpoint", "/triage",
            "--draft", str(EXAMPLE_DRAFT), "--out", str(tmp_path / "review"),
        ],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip

    assert result.returncode == 0, result.stderr
    report = (tmp_path / "review" / "triage" / "REVIEW.md").read_text(encoding="utf-8")
    assert "7 tests drafted" in report
    assert (
        "| `test_triage_returns_documented_priority_and_category` | passed | none "
        "| ready for review |" in report
    )
    assert "`test_summary_exists` | passed | no assertions | needs work" in report
    assert (
        "`test_missing_asset_id_is_rejected_with_422` | passed | duplicates existing test tests/"
        in report
    )
    assert "`test_summary_is_never_longer_than_100_characters` | failed: AssertionError" in report
    assert "investigate: failed" in report
    assert "Nothing here is merged automatically" in report
