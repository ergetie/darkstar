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

echo "▶ [0/8] Upstream sync check"
# Fail fast (before the slow checks) when the remote branch has commits we lack:
# the push would be rejected anyway. Offline / no upstream: warn and continue.
if upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)"; then
  remote="${upstream%%/*}"
  branch="${upstream#*/}"
  if timeout 15 git fetch --quiet "$remote" "$branch" 2>/dev/null; then
    if ! git merge-base --is-ancestor "$upstream" HEAD; then
      behind="$(git rev-list --count "HEAD..$upstream")"
      echo "✗ $upstream has $behind new commit(s) — run: git pull --rebase, then push again" >&2
      exit 1
    fi
  else
    echo "  (could not fetch $upstream — offline? skipping upstream check)"
  fi
else
  echo "  (no upstream configured — skipping upstream check)"
fi

echo "▶ [1/8] Ruff (lint)"
uv run ruff check backend/ planner/ ml/ executor/

echo "▶ [2/8] Pyright (types)"
uv run pyright

echo "▶ [3/8] Pytest (full suite)"
uv run python -m pytest -q

echo "▶ [4/8] OpenAPI schema export + validate"
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

echo "▶ [5/8] Frontend ESLint"
if command -v pnpm >/dev/null 2>&1; then
  (cd frontend && pnpm lint)
else
  echo "  (pnpm not found — skipping frontend lint; CI still runs it)"
fi

echo "▶ [6/8] Frontend typecheck (tsc)"
if command -v pnpm >/dev/null 2>&1; then
  (cd frontend && pnpm typecheck)
else
  echo "  (pnpm not found — skipping frontend typecheck; CI still runs it)"
fi

echo "▶ [7/8] Frontend tests (vitest)"
if command -v pnpm >/dev/null 2>&1; then
  (cd frontend && pnpm test)
else
  echo "  (pnpm not found — skipping frontend tests; CI still runs them)"
fi

echo "▶ [8/8] Frontend build (vite)"
if command -v pnpm >/dev/null 2>&1; then
  (cd frontend && pnpm build)
else
  echo "  (pnpm not found — skipping frontend build; CI still runs it)"
fi

echo "✓ All CI checks passed — safe to push."
