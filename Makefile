.PHONY: install run lint format typecheck check clean

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

# Everything CI runs that does not need a network
check: lint typecheck

clean:
	uv run python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('.mypy_cache', '.ruff_cache', '.pytest_cache')]"
