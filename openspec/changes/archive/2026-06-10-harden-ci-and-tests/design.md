## Context

This change implements stabilization-review findings #3, #5, #11, #37, #38 (see `openspec/changes/stabilization-review/findings.md`). It is the foundation change in the stabilization roadmap: it raises the CI/runtime floor so the existing **1051-test** suite (Phase 0 baseline, all passing locally) actually gates merges, before the other fix-changes (recorder-ssot, fix-ml-forecast-correctness, etc.) start touching application code.

Current state:
- CI (`.github/workflows/ci.yml`) runs only `tests/api/test_api_routes.py`. Pyright strict is configured in `pyproject.toml` but enforced only locally via `.pre-commit-config.yaml`.
- `backend/` core infra has ~22 modules with no dedicated tests, including `ha_socket.py` (~855 lines) and the planner/executor service wrappers.
- `planner/inputs/weather.py:62` and `ml/evaluate.py:100` emit operational warnings via `print()`.
- WAL on `planner_learning.db` is set only as a side-effect of executor init (`executor/history.py`), which is gated on `executor.config.enabled`; `store.ensure_wal_mode()` has test-only callers.
- Several `async def` API routes (`price_forecast.py`, `price_outlook.py`, `executor.py`) run synchronous `sqlite3`/SQLAlchemy reads directly on the event loop; the price connections omit `timeout=`.

This is a hardening change with **no intended behavior change** to planning, forecasting, or control.

## Goals / Non-Goals

**Goals:**
- CI gates merges on the full Python test suite + pyright strict.
- The two highest-risk untested infra modules get characterization tests.
- Operational warnings go through the structured logger, guarded by lint.
- `planner_learning.db` is in WAL mode from startup regardless of executor state.
- Synchronous DB reads in hot API routes no longer block the event loop and have a sane busy-timeout.

**Non-Goals:**
- No full coverage push — only `ha_socket.py` and the service wrappers are in scope for new tests (#5 names others as later work).
- No refactor of the god files (separate `executor-refactor` change, #36).
- No change to query *results* — DB-access changes are purely about where/how the call runs.
- Frontend test coverage (out of stabilization-review scope).

## Decisions

### D1 — CI: one full-suite job + a separate pyright job
Run `uv run python -m pytest` (whole suite) as the test gate, and a dedicated `pyright` job, both required for merge. **Alternative considered:** a per-package test matrix — rejected for now as unnecessary complexity; a single job mirrors the local baseline command and is the smallest change that closes #3. The API-only step is replaced, not supplemented.

### D2 — Pyright gate may need a baseline-clearing step
Strict pyright has only ever run locally, so the repo-wide strict run may surface pre-existing errors. **Decision:** the pyright job is added as a *required* gate, but if the first full run is not already clean, clearing those errors is part of this change's tasks (or, if large, explicitly carved out). Whether it is clean today is an **open question** to resolve in task 1.

### D3 — print→logger + ruff lint guard
Replace the two `print()` calls with `logger.warning(...)` using each module's existing logger, and enable ruff rule **T201** (`flake8-print`) scoped to library/service packages (`backend/`, `planner/`, `ml/`, `executor/`) while excluding `scripts/` and any CLI entrypoints. **Alternative:** a custom grep check in CI — rejected; ruff already runs and has a purpose-built rule.

### D4 — WAL at startup via the always-constructed store
Call `await store.ensure_wal_mode()` in the `backend/main.py` lifespan right after `LearningStore` is initialized, independent of `executor.config.enabled`. **Alternative considered:** set WAL in the Alembic migration — viable, but the lifespan call is the one-line guaranteed fix and keeps WAL-setup next to DB-open in the app code. WAL is persistent, so this is idempotent and harmless on already-WAL DBs.

### D5 — Offload sync DB reads with `asyncio.to_thread` + busy-timeout
Wrap the synchronous `sqlite3`/SQLAlchemy reads in the affected routes in `asyncio.to_thread(...)`, and add `timeout=30` to the price-forecast `sqlite3.connect` calls (matching the 30 s used elsewhere). **Alternative considered:** rewrite these routes onto the async `LearningStore` — larger blast radius and out of scope for a hardening pass; `to_thread` is the minimal, behavior-preserving fix. Pairs with D4 (WAL reduces lock contention these routes would otherwise hit).

### D6 — Characterization-test scope (#5)
Write characterization (behavior-pinning) tests for `backend/ha_socket.py` and the planner→executor service wrappers (`backend/services/planner_service.py`, `recorder_service.py`) only. These bridge planner→executor and are the prime hiding spots for runtime bugs. The other ~20 untested modules are recorded in #5 as later work, not pulled in here.

## Risks / Trade-offs

- **Full suite in CI is slower than the API subset** → Mitigation: the local baseline runs in ~60s; enable dependency caching. Acceptable for a merge gate.
- **Enabling the full suite or pyright surfaces pre-existing red** → Mitigation: the test baseline is known-green (1051 pass); pyright is the unknown (D2) — task 1 confirms before the gate is marked required.
- **`to_thread` changes timing/ordering of DB reads** → Mitigation: these are read-only queries with no shared mutable state; results are unchanged, only the thread differs.
- **Characterization tests pin current (possibly buggy) behavior** → Trade-off accepted: the point is a regression net for *this* refactor-heavy roadmap; any bug a test pins is separately tracked as its own finding.

## Open Questions

- **Does repo-wide strict pyright pass clean today?** (D2) — determines whether this change also clears a type-error baseline or just adds the gate.
- **Does `ml/training_orchestrator.train_all_models` block the event loop?** This is finding #38's explicitly-unverified residual. If it does, the `to_thread` offload scope grows to include the training path; confirm during task work before finalizing #38's scope.
