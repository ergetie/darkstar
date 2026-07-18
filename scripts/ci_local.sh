#!/usr/bin/env bash
#
# Local CI gate — runs the SAME checks as .github/workflows/ci.yml so that a
# clean run here means a clean run in GitHub Actions. Wired to `git push` via the
# pre-commit `ci-gate` hook (stages: [pre-push]); also runnable by hand:
#
#     ./scripts/ci_local.sh
#
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# Deps are managed via requirements*.txt (uv pip install), not `uv sync`/uv.lock
# (see pyproject.toml [tool.uv] package = false). Without this, `uv run` treats
# the repo as a uv project and regenerates a meaningless uv.lock stub on every call.
export UV_NO_SYNC=1

echo "▶ [1/5] Ruff (lint)"
uv run ruff check backend/ planner/ ml/ executor/

echo "▶ [2/5] Pyright (types)"
uv run pyright

echo "▶ [3/5] Pytest (full suite)"
uv run python -m pytest -q

echo "▶ [4/5] OpenAPI schema export + validate"
uv run python -c "
import sys
sys.path.insert(0, '.')
from backend.main import create_app
app = create_app()
fastapi_app = app.other_asgi_app
schema = fastapi_app.openapi()
assert 'openapi' in schema, 'Missing openapi version'
assert 'info' in schema, 'Missing info section'
assert 'paths' in schema, 'Missing paths section'
assert len(schema['paths']) > 50, f'Expected 50+ routes, got {len(schema[\"paths\"])}'
print(f'OpenAPI schema valid: {len(schema[\"paths\"])} paths defined')
"

echo "▶ [5/5] Frontend ESLint"
if command -v pnpm >/dev/null 2>&1; then
  (cd frontend && pnpm lint)
else
  echo "  (pnpm not found — skipping frontend lint; CI still runs it)"
fi

echo "✓ All CI checks passed — safe to push."
