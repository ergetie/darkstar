## Why

Three production incidents in the last week trace to the same root: shared state on the planner→executor path is written without any guard. The executor read a half-written `schedule.json` (2026-09-14) because the planner truncates and rewrites the live 256 KB file in place. Four `database is locked` errors (2026-09-17 22:15) came from two executor ticks running at once — the planner has a concurrency guard, the executor has none. While tracing the second, a third defect surfaced: the planner reads the previous schedule from the wrong path, so water-heater mid-block locking has never once fired in production.

The same investigation found that nine database tables are written or defined but read by nothing, including the `battery_cost` tracker — which builds a fresh database engine, fetches Nordpool prices, and writes a row every 5 seconds to feed a value that no code, API, or screen consults. That dead write is one of the three writers that collided in the lock incident, so removing it is part of the fix rather than separate housekeeping.

## What Changes

**Durability — stop the torn read**

- Write `schedule.json` atomically (temp file in the same directory, then `os.replace`) from both writers: `planner/output/schedule.py` and `POST /api/schedule/save`.
- Add a shared helper so a future third writer cannot reintroduce the bug, and a guard test that fails when a writer opens the live schedule in truncating mode.

**Concurrency — stop the overlapping tick**

- Guard the executor tick with a non-blocking `threading.Lock`. A second entrant returns "already running" and logs the skip, mirroring the planner's existing behavior.
- **The lock must be a `threading.Lock`, not an `asyncio.Lock`.** The scheduled loop runs in a background thread with its own event loop; `run_once()` is called from the FastAPI event loop in the main thread. An `asyncio.Lock` is neither shared across event loops nor thread-safe, so copying the planner's pattern verbatim would produce a guard that silently does nothing.

**Removal — strip the legacy surface**

- Delete battery-cost tracking entirely: `backend/battery_cost.py`, `_update_battery_cost` and its call site, the `BatteryCost` model, and the per-tick Nordpool fetch that exists only to feed it.
- Drop nine dead tables and their ORM models in one migration: `battery_cost`, `antares_rl_runs`, `antares_training_runs`, `antares_policy_runs`, `training_episodes`, `strategy_log`, `daily_water`, `sensor_totals`, `realized_energy`. None has a reader anywhere in the codebase.
- Remove the `training_episodes` write path (`log_training_episode`'s gate, `store_training_episode`, `get_episodes_count`), the permanently-zero `training_episodes` field from `GET /api/learning/status`, the orphaned `bin/inspect_episodes.py`, and the dead row in `scripts/health_check.py`.

**Correctness — the silent water-heater bug**

- Fix `planner/pipeline.py` to read the previous schedule from the path the planner actually writes (`data/schedule.json`, resolved from config rather than hardcoded), and log a warning when the previous schedule is missing or empty instead of continuing silently.

No breaking changes for users. The removed API field is consumed by nothing; the dropped tables have no readers.

## Capabilities

### New Capabilities

- `durable-schedule-write`: every writer of `schedule.json` persists atomically, so a concurrent reader can never observe a partial file. Mirrors the existing `durable-config-write` contract for the schedule file.
- `executor-single-flight`: at most one executor tick runs at a time across the scheduled loop and the manual trigger endpoint, with skips logged rather than silent.

### Modified Capabilities

- `executor`: removes the requirement "Executor fetches current Nordpool import price for battery cost tracking" and its three scenarios. Battery cost tracking ceases to exist, so the per-tick price fetch it mandates must go with it.
- `stabilization-hygiene`: extends the existing dead-table requirement (which already covers `schedule_planned`) to the nine tables removed here, including migration and downgrade parity.
- `planner`: the existing mid-block locking requirement gains an explicit contract that the previous schedule is read from the path the planner writes, and that a missing or empty previous schedule is logged rather than silently treated as "no heater active".

## Impact

**Code**

- `planner/output/schedule.py:115` and `backend/api/routers/schedule.py:514` — the two non-atomic writes.
- `executor/engine.py` — tick guard around `_tick()`; `run_once()` (line 981) and the scheduled loop (line 1090) are the two entrants. Removal of `_update_battery_cost` (line 2413) and its call (line 1815).
- `planner/pipeline.py:816` — the wrong schedule path feeding mid-block locking at lines 856–892.
- `backend/battery_cost.py` — deleted. `backend/learning/models.py` — nine model classes removed. `backend/learning/engine.py:112,344` and `backend/learning/store.py` — training-episode paths removed.
- New Alembic migration dropping nine tables, with a downgrade that recreates them empty for rollback parity.
- Tests: `tests/executor/test_executor_engine.py` (lines 1179, 1551–1577, 1623), `tests/ml/test_learning_engine.py:142-148`. New tests for atomic write, tick single-flight, and mid-block locking.

**Systems**

- Planner and executor scheduling. One database migration against live beta-tester data. No config migration; no frontend change.

**Risk**

- The migration is the only irreversible step. It is low risk because no code reads the dropped tables, but it runs against users' live databases, so a backup must precede it and the downgrade must restore the schema.
- The executor lock sits on the control path. A lock taken blocking rather than non-blocking would queue ticks instead of skipping them and turn a 5-second cadence into a backlog; it must be `acquire(blocking=False)`.

**Out of scope**

- The `projected_battery_cost` field hardcoded to `0.0` at `planner/solver/adapter.py:633` and surfaced in `planner/output/debug.py:139-160`. Same era, but it flows into the debug payload rather than being unreferenced, so it needs its own look.
- Whether mid-block locking should detect heating from a power sensor (as the `planner` spec's wording suggests) rather than from the previous schedule. This change makes the existing mechanism work; changing the detection source is a separate decision.
