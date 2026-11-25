set shell := ["bash", "-euo", "pipefail", "-c"]

# Run every check: lint, format check, types and tests
check: lint typecheck test

lint:
    uv run ruff check .
    uv run ruff format --check .

typecheck:
    uv run mypy

test *args:
    uv run pytest {{args}}

# Apply ruff fixes and formatting
fix:
    uv run ruff check --fix .
    uv run ruff format .

# Run the server over stdio (needs DISCOGS_TOKEN)
serve:
    uv run runout-mcp
