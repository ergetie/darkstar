# Proposal: dependency-upgrade-pass

## Why

Dependencies are a mix of loose ranges and deliberate holds: runtime deps in `requirements.txt` use `>=` ranges (so CI and local can silently resolve different versions — the exact failure mode that broke CI in June), dev tools are frozen at known-good-but-aging versions (`pyright==1.1.408`, `ruff==0.15.5`), `pnpm` is held at 9 because the Docker images' apt-installed Node lacks Node 22's `node:sqlite` (blocking pnpm 10), and `pulp` carries a `<4.0.0` ceiling with a known migration debt (`prob.constraints` dict access, used in `planner/solver/kepler.py`). This change is the deliberate, controlled catch-up-and-pin pass that the `harden-ci-and-tests` work (2026-06-10) intentionally deferred. **(BIG — multi-session change; every phase ends at a green-CI checkpoint so work can pause/resume between sessions.)**

## What Changes

- **Dev tools:** bump `ruff`, `pyright`, `pytest`/`pytest-asyncio`/`pytest-cov` to current; fix everything the stricter versions flag (pyright strict is the expected pain point); keep exact `==` pins.
- **Runtime Python deps:** upgrade in small groups (web stack / data-ML stack / rest), running the local CI gate after each group; then convert `requirements.txt` from `>=` ranges to exact `==` pins so CI and local always resolve identically.
- **Node + pnpm:** install Node 22 in all three Dockerfiles (replacing the apt default), align CI's `node-version` to 22, then move pnpm 9 → 10 with a lockfile migration.
- **PuLP:** check whether PuLP 4.0 has been released at implementation time. If yes: migrate `prob.constraints[...]` dict usages in `planner/solver/kepler.py` to the 4.0 API, verify solver output parity, lift the ceiling. If no: keep `pulp` on latest 3.x with the `<4.0.0` ceiling and leave the migration note in place.
- **Frontend packages:** minor/patch updates only via `pnpm update` within existing semver ranges + lockfile refresh. Major version bumps of frontend libraries are explicitly OUT of scope (each is its own decision).
- **Lock strategy decision (resolved):** keep `requirements*.txt` with exact pins; do NOT migrate to `pyproject.toml` + `uv.lock` in this change (the current `uv.lock` is an empty stub; a packaging migration would multiply the blast radius of an already-big change). Delete the misleading empty `uv.lock`.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `ci-quality-gate`: ADDED requirement — Python dependencies SHALL be exactly pinned so CI and local resolve identical versions, and toolchain versions (Python/Node/pnpm) SHALL match across CI and the Dockerfiles.

## Impact

- **Files:** `requirements.txt`, `requirements-dev.txt`, `Dockerfile`, `darkstar/Dockerfile`, `darkstar-dev/Dockerfile`, `.github/workflows/ci.yml`, `frontend/pnpm-lock.yaml` (+ `frontend/package.json` only if pnpm 10 requires field changes), `planner/solver/kepler.py` (only if PuLP 4.0 is out), `uv.lock` (deleted), and whatever code the stricter pyright/ruff flag.
- **Risk:** each bump can break behavior subtly; mitigated by group-wise bumps with `scripts/ci_local.sh` (full lint+typecheck+tests) after every group, and pause-able checkpoints.
- **Rollback:** per-phase — each checkpoint is independently revertable.
- **No behavior/feature changes intended anywhere.**
