.PHONY: install run lint format typecheck check test smoke regression test-fast test-live test-anthropic harness harness-online flake-detect clean

# Install runtime and dev dependencies into .venv
install:
	uv sync --all-groups

# Run the ticket-triage app locally with auto-reload
run:
	uv run uvicorn app.main:app --reload --port 8000

lint:
	uv run ruff check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

# The shared test suites, in-process app, FakeProvider, no network
test:
	uv run pytest tests

smoke:
	uv run pytest tests -m smoke

regression:
	uv run pytest tests -m regression

# Skip anything marked slow
test-fast:
	uv run pytest tests -m "not slow"

# Against a running server, e.g. `make run` in another terminal
test-live:
	uv run pytest tests --base-url http://localhost:8000

# In-process app talking to the real Anthropic API; needs ANTHROPIC_API_KEY
test-anthropic:
	uv run pytest tests --provider anthropic

# Resilience harness, offline: fake provider, keyword groundedness
harness:
	uv run pytest harness

# Resilience harness with the real API for both the app and the judge
harness-online:
	uv run pytest harness --provider anthropic

# Run the shared suite five times and report tests with inconsistent results
flake-detect:
	uv run python scripts/flake_detect.py --suite tests --runs 5

# Everything CI runs that does not need a network
check: lint typecheck test harness

clean:
	uv run python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('.mypy_cache', '.ruff_cache', '.pytest_cache')]"
