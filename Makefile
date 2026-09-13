.PHONY: install run lint format typecheck check test smoke regression test-fast test-live test-anthropic clean

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

# All tests, in-process app, FakeProvider, no network
test:
	uv run pytest

smoke:
	uv run pytest -m smoke

regression:
	uv run pytest -m regression

# Skip anything marked slow
test-fast:
	uv run pytest -m "not slow"

# Against a running server, e.g. `make run` in another terminal
test-live:
	uv run pytest --base-url http://localhost:8000

# In-process app talking to the real Anthropic API; needs ANTHROPIC_API_KEY
test-anthropic:
	uv run pytest --provider anthropic

# Everything CI runs that does not need a network
check: lint typecheck test

clean:
	uv run python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('.mypy_cache', '.ruff_cache', '.pytest_cache')]"
