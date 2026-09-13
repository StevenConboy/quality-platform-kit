"""Command line for the authoring tool.

    authoring generate --spec openapi.json --endpoint /triage
    authoring generate --spec openapi.json --endpoint /triage --draft my_draft.py   (no LLM)
    authoring review authoring/review/triage
    authoring export-spec --out openapi.json

Reads a .env file in the working directory for ANTHROPIC_API_KEY if it is not already set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from authoring.generator import DEFAULT_MODEL, Generator, build_user_message, render_prompt
from authoring.report import render_report, review_all
from authoring.review import analyze_file, analyze_tree, flag_duplicates, run_pytest
from authoring.spec import extract_operations, load_spec, render_operations

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = Path(__file__).resolve().parent / "prompt.md"
CONVENTIONS_PATH = REPO_ROOT / "tests" / "README.md"
EXAMPLE_PATH = REPO_ROOT / "tests" / "regression" / "test_triage_faults.py"
EXISTING_TESTS_ROOT = REPO_ROOT / "tests"
DEFAULT_OUT = REPO_ROOT / "authoring" / "review"


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def slug(endpoint: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", endpoint.lower()).strip("_") or "root"


def rel(path: Path) -> str:
    """Repo-relative for display when possible; --out may point anywhere."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


# --- commands ---------------------------------------------------------------------------


def cmd_generate(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    operations = extract_operations(spec, args.endpoint)
    endpoint_text = render_operations(operations)

    out_dir = Path(args.out) / slug(args.endpoint)
    out_dir.mkdir(parents=True, exist_ok=True)
    module = out_dir / f"test_{slug(args.endpoint)}_drafted.py"

    meta: dict[str, str] = {"endpoint": args.endpoint, "spec": args.spec}
    if args.draft:
        module.write_text(Path(args.draft).read_text(encoding="utf-8"), encoding="utf-8")
        meta["source"] = f"draft file {args.draft} (no model call)"
    else:
        existing = analyze_tree(EXISTING_TESTS_ROOT)
        existing_lines = [
            f"{t.nodeid}: {', '.join(sorted(t.fingerprint)) or 'n/a'}" for t in existing
        ]
        system_prompt = render_prompt(
            PROMPT_PATH.read_text(encoding="utf-8"), count=str(args.count)
        )
        user_message = build_user_message(
            endpoint_text=endpoint_text,
            conventions=CONVENTIONS_PATH.read_text(encoding="utf-8"),
            example_path=EXAMPLE_PATH.relative_to(REPO_ROOT),
            example_source=EXAMPLE_PATH.read_text(encoding="utf-8"),
            existing_tests=existing_lines,
            module_name=rel(module),
        )
        print(f"drafting {args.count} tests for {args.endpoint} with {args.model} ...")
        draft = Generator(model=args.model).draft(system_prompt, user_message)
        module.write_text(draft.source, encoding="utf-8")
        meta.update(
            {
                "model": draft.model,
                "tokens": f"{draft.input_tokens} in / {draft.output_tokens} out",
                "stop_reason": str(draft.stop_reason),
                "prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest()[:12],
            }
        )
        (out_dir / "prompt_used.md").write_text(
            system_prompt + "\n\n---\n\n" + user_message, encoding="utf-8"
        )
    (out_dir / "generation.json").write_text(
        json.dumps({**meta, "generated_at": datetime.now(UTC).isoformat()}, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {rel(module)}")
    return review_module(module, args.endpoint, meta)


def cmd_review(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    modules = sorted(folder.glob("test_*.py"))
    if not modules:
        print(f"no test_*.py files in {folder}", file=sys.stderr)
        return 2
    meta_path = folder / "generation.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    endpoint = str(meta.get("endpoint", folder.name))
    code = 0
    for module in modules:
        code = max(code, review_module(module, endpoint, {k: str(v) for k, v in meta.items()}))
    return code


def review_module(module: Path, endpoint: str, meta: dict[str, str]) -> int:
    drafted = analyze_file(module)
    existing = [t for t in analyze_tree(EXISTING_TESTS_ROOT) if t.file != module]
    flag_duplicates(drafted, existing)

    junit = module.parent / "junit.xml"
    runs = run_pytest([module], junit, cwd=REPO_ROOT)
    reviewed = review_all(drafted, runs)

    report_path = module.parent / "REVIEW.md"
    report_path.write_text(render_report(endpoint, module, reviewed, meta), encoding="utf-8")

    print(f"\n{len(reviewed)} tests reviewed; report: {rel(report_path)}")
    for r in reviewed:
        print(f"  {r.run.outcome:<8} {r.test.name:<50} {r.verdict}")
    return 0


def cmd_export_spec(args: argparse.Namespace) -> int:
    """Convenience for this repo: write the app's own OpenAPI document."""
    from app.main import create_app

    Path(args.out).write_text(json.dumps(create_app().openapi(), indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


# --- entry point ------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="authoring", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="draft tests for one endpoint, then review them")
    gen.add_argument("--spec", required=True, help="OpenAPI JSON file path or URL")
    gen.add_argument("--endpoint", required=True, help="path as it appears in the spec")
    gen.add_argument("--count", type=int, default=6, help="how many tests to ask for")
    gen.add_argument("--model", default=DEFAULT_MODEL)
    gen.add_argument("--out", default=str(DEFAULT_OUT), help="review folder root")
    gen.add_argument("--draft", help="use this Python file as the draft instead of the model")
    gen.set_defaults(func=cmd_generate)

    rev = sub.add_parser("review", help="re-run the review on a folder of drafts")
    rev.add_argument("folder")
    rev.set_defaults(func=cmd_review)

    exp = sub.add_parser("export-spec", help="write this repo's app spec to a file")
    exp.add_argument("--out", default="openapi.json")
    exp.set_defaults(func=cmd_export_spec)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
