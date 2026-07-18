# Design: dependency-upgrade-pass

## Context

Current state (verified 2026-07-13):

- `requirements.txt`: loose `>=` ranges (e.g. `fastapi>=0.109.0,<0.136.0`, `pandas>=2.0.0`, `sqlalchemy>=2.0.48,<3.0.0`), plus the deliberate `pulp>=2.9.0,<4.0.0` ceiling.
- `requirements-dev.txt`: `ruff==0.15.5`, `pyright==1.1.408` exactly pinned (with a comment explaining why); `pytest>=7.0.0`, `pytest-asyncio>=0.21.0`, `pytest-cov>=4.1.0`, type stubs and DX tools loose.
- Dockerfiles ×3 (`Dockerfile`, `darkstar/Dockerfile`, `darkstar-dev/Dockerfile`): all `FROM python:3.12-slim`; Node comes from apt (`nodejs` package of Debian slim — too old for pnpm 10); `npm install -g pnpm@9` pinned with explanatory comments referencing the Node 22 `node:sqlite` requirement.
- CI (`.github/workflows/ci.yml`): `python-version: '3.12'`, `pnpm/action-setup@v4`, `node-version: '20'` — note CI Node (20) already differs from the Docker apt Node; after this change everything is 22.
- `uv.lock`: 134 bytes — an empty stub, misleading; nothing uses uv locking.
- PuLP migration debt: `prob.constraints` dict-access pattern lives ONLY in `planner/solver/kepler.py` (verified by grep across `planner/`).
- The local CI gate is `scripts/ci_local.sh` (lint + typecheck + full test suite; suite = 1576 tests, ~60s).
- Frontend: pnpm 9 lockfile; Vite/React/TS stack; 89 passing tests (vitest).

## Goals / Non-Goals

**Goals:**
- Everything current within one major-version policy sweep; exact `==` pins for all Python deps (runtime + dev) afterward.
- Toolchain parity: Python 3.12 / Node 22 / pnpm 10 identical across CI and all Dockerfiles.
- Each phase ends green (full local CI gate) and is independently committable — the change survives being spread over multiple sessions.

**Non-Goals:**
- No migration to `pyproject.toml` + `uv.lock` (decided against — see proposal; the empty `uv.lock` is deleted instead).
- No frontend major-version bumps (React, Vite, Chart.js majors are each their own future decision).
- No Python 3.13 base-image bump (3.12 is current-enough and the add-on base matters more than novelty; revisit separately).
- No feature/behavior changes; anything a stricter tool flags gets the minimal compliant fix.

## Decisions

### D1: Phase order = dev tools → runtime groups → pinning → Node/pnpm → PuLP check → frontend minors

Dev tools first because the stricter pyright/ruff findings must be fixed against *current* code before runtime bumps add their own noise (one variable at a time). Runtime deps in three groups small enough to bisect a breakage by revert: (a) web stack (fastapi/starlette/uvicorn/httpx/aiohttp/websockets/python-socketio), (b) data/ML (pandas/scikit-learn/lightgbm/numpy-transitives/sqlalchemy/alembic/aiosqlite), (c) rest (pydantic, pyyaml/ruamel, pytz/dateutil, requests, nordpool, astral, open-meteo-solar-forecast, python-json-logger). Exact-pinning happens AFTER upgrades (pin what you just validated). Node/pnpm after Python (independent axis, keeps Docker rebuilds bunched). PuLP last among Python work because it may include a solver-API migration with its own verification.

### D2: Exact pins via `pip freeze`-derived versions of the validated environment

After the upgrade groups pass CI, write `==` pins for every direct dependency in both requirements files (NOT a full freeze of transitives — pin direct deps only, matching the current file structure; transitive pinning belongs to a real lock tool, which we decided against). Preserve the explanatory comments (they carry the project's history — e.g. why pyright was once held back; update their text to reflect the new policy).

### D3: Node 22 via NodeSource in the Dockerfiles, not a base-image change

Keep `FROM python:3.12-slim` (the add-on ecosystem depends on this base) and install Node 22 from NodeSource's Debian repo instead of apt's default `nodejs`. Update all three Dockerfiles identically. CI's `node-version: '20'` → `'22'` in the same phase, so parity is restored in one commit. Then `pnpm@10`: bump the `npm install -g pnpm@9` lines and CI's action-setup, run `pnpm install` to migrate `pnpm-lock.yaml` (lockfile format v9 stays compatible; verify `--frozen-lockfile` still passes in a clean Docker build).

### D4: PuLP is conditional, gated on a release check at implementation time

Task explicitly starts with "check PyPI for pulp 4.0". Not released → bump within 3.x, keep ceiling, done. Released → migrate `planner/solver/kepler.py`'s `prob.constraints[name]` usages to the 4.0 API FIRST, prove solver parity (same plan output on a fixed scenario — the planner tests cover this), then lift the ceiling. Never lift the ceiling without the migration.

### D5: Every phase ends with the same checkpoint ritual

`scripts/ci_local.sh` green → report to the user what was bumped (old → new versions) → user commits (per project rule: AI never commits without explicit permission). A failed bump within a group → bisect by reverting individual packages within the group, fix or hold the offender with a comment, re-run.

## Risks / Trade-offs

- [Stricter pyright breaks many files] The 1.1.408 hold exists precisely because newer strict inference failed checks → budgeted as its own phase with unknown size; if the fix set explodes (>~20 files), stop and report to the user before continuing rather than grinding through silently.
- [Runtime dep changes planner/ML numerics] pandas/scikit-learn/lightgbm bumps can change numeric results legitimately → the test suite plus a before/after run of the planner on a fixed scenario (existing solver tests assert plan properties, not bit-exact floats) gate this; genuine numeric drift gets reported, not hidden.
- [pnpm 10 lockfile migration breaks Docker build] Verified in a clean `docker build` as part of the phase, not just locally.
- [Direct-only pinning still allows transitive drift] Accepted residual risk (a real lock tool was consciously deferred); direct pins remove the failure mode that actually bit this project.
- [Multi-session drift] Other changes may land between phases → each phase starts by re-running the CI gate to confirm a green baseline.

## Migration Plan

Phased, each independently committable and revertable (see tasks). Docker images rebuild on the Node/pnpm phase; the add-on picks the changes up on its normal build. No data or config migration.

## Open Questions

_None — the lock-strategy decision (keep requirements.txt, no uv migration) and frontend-majors exclusion are resolved in this design; PuLP is decision-free (conditional on the release check)._
