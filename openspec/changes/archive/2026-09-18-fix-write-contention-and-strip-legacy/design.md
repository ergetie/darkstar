## Context

Three defects share a root cause: shared state on the planner→executor path is written without a guard.

**Evidence, from retained production logs (7–8 days).**

Torn read, 2026-09-14:

```
04:17:15,348 ERROR executor.engine | Failed to load schedule: Expecting ':' delimiter ... (char 196756)
04:17:16,020 INFO  darkstar.services.planner | Planner completed: 175 slots in 76185ms
```

The executor read the file 0.7 s before the planner finished writing it. `data/schedule.json` is 256 KB; the parse died at 196 KB.

Write contention, 2026-09-17:

```
22:14:00,001  Executing scheduled tick            <- loop tick
22:14:00,400  Executor tick started               <- a SECOND tick, concurrently
22:14:01,474  Slow request: POST /api/executor/run took 1075ms
22:15:30,731  SLOW TICK: 30.73s                   <- 30 s busy-timeout, fully exhausted
22:15:57,434  Slow request: POST /api/executor/run took 62106ms
```

Four `database is locked` errors fell inside one 40-second window. Every engine already sets a 30 s busy-timeout (`executor/history.py:86`, `backend/battery_cost.py:43`, `backend/learning/store.py:38`, `planner/vacation_state.py:23`), and the failing ticks took 30.73 s and 31.76 s — the timeout was exhausted, not absent. **Raising the busy-timeout would fix nothing.** The holder was a second executor tick: the planner guards concurrency (`backend/services/planner_service.py:49`), the executor has no lock of any kind.

Silent water-heater bug: `planner/pipeline.py:816` reads `Path("schedule.json")` while the writer saves to `data/schedule.json`. In the container `/app/schedule.json` is a 48-byte stub (`{"schedule": [], "meta": {"initialized": true}}`), so `previous_schedule` is always `[]`. Grepping 8 days of logs for `Mid-block lock` returns **0 hits** on a system with an enabled water heater. The feature has never fired. It fails silently because the `except` catches only read errors, and an empty-but-valid file is not one.

**Dead surface found during the same trace.** Nine tables have no reader anywhere. Verified by grepping ORM class names (not table strings, which miss usage):

| Table | Class | Prod rows | Only reference |
|---|---|---|---|
| `battery_cost` | `BatteryCost` | 1 | write-only via `executor/engine.py:2438` |
| `antares_rl_runs` | `AntaresRLRun` | 22 | `models.py` only |
| `antares_training_runs` | `AntaresTrainingRun` | 2 | `models.py` only |
| `antares_policy_runs` | `AntaresPolicyRun` | 7 | `models.py` only |
| `strategy_log` | `StrategyLog` | 148 | `models.py` only |
| `daily_water` | `DailyWater` | 172 | `models.py` only |
| `sensor_totals` | `SensorTotal` | 6 | `models.py` only |
| `realized_energy` | `RealizedEnergy` | 0 | `models.py` only |
| `training_episodes` | `TrainingEpisode` | 0 | write gated off, see below |

Antares (the abandoned RL experiment) has no code left — only `docs/archive/ANTARES_*.md` and two dead git branches. `training_episodes` is written only when `debug.enable_training_episodes` is true; that key appears at exactly one `if` statement in the entire repo and in no config file or UI, so it is unreachable. Its own comment reads `# 1. Log to training_episodes (Legacy/Debug only)` … `for RL`.

`battery_cost` is the costly one. `executor/engine.py:2413` runs every 5 s and, per tick: constructs a fresh `BatteryCostTracker` (a new SQLAlchemy engine and pool, never disposed), fetches Nordpool price data, and writes a row. ~17,280 writes/day feeding a value that `get_current_cost()` and `reset()` — both with zero callers — would have read. It was one of the three writers in the lock incident.

This was already half-done: `docs/archive/PLAN.old-25-12-25.md` records the decision to *"**IGNORE** historical WAC"* and to remove `BatteryCostTracker` from the solver. The read side was removed in Dec 2025; the write side was left running for nine months.

## Goals / Non-Goals

**Goals:**

- A reader of `schedule.json` can never observe a partially written file.
- At most one executor tick runs at a time, and a rejected entrant is visible in the logs.
- Battery-cost tracking and the nine dead tables are gone from code, schema, and API surface.
- Water-heater mid-block locking actually reads the file the planner writes, and says so when it cannot.

**Non-Goals:**

- Changing SQLite tuning. Busy-timeout, WAL, and pool settings are already correct and stay as they are; the fix is to stop the concurrent writer, not to tolerate it longer.
- Changing *how* mid-block heating is detected. The `planner` spec's wording suggests a power sensor; the implementation uses the previous schedule's `heating_kw`. This change makes the existing mechanism work and leaves the detection source alone.
- Serializing the planner against the executor. The planner already has its own guard, and the two never wrote the same row.
- `projected_battery_cost`, hardcoded `0.0` at `planner/solver/adapter.py:633` and surfaced via `planner/output/debug.py:139-160`. Same era, but it reaches the debug payload rather than being unreferenced.

## Decisions

### 1. One shared atomic-JSON helper, in `backend/core/`

Add `backend/core/atomic_json.py` exposing `write_json_atomic(path, payload, *, encoder=None, indent=2)`. It creates a `NamedTemporaryFile` **in the target's own directory**, writes, closes, then `os.replace`s onto the target — exactly the pattern already proven at `backend/core/ev_state.py:47`.

Both writers call it: `planner/output/schedule.py:115` and `backend/api/routers/schedule.py:514`.

*Why `backend/core/`:* `planner/pipeline.py:23` already imports `backend.core.ev_goal`, so the planner importing `backend.core` introduces no new dependency direction.

*Why not reuse `_write_config`:* that helper is YAML-specific and carries timestamped-backup and validation logic that the schedule does not want on a 30-minute cadence.

**No bind-mount fallback is needed, and none should be written.** `config.yaml` needs one because it is a *single-file* bind mount — you cannot rename over a mount point. `data/` is a *directory* mount, so a temp file inside it renames within the same filesystem. Verified on production:

```
$ docker exec darkstar python -c "os.replace('/app/data/.probe.tmp', '/app/data/.probe')"
os.replace in /app/data: OK
```

`ev_state.py` has used this exact path in that exact directory without a single failure. Copying `_write_config`'s `EBUSY/EXDEV/ETXTBSY` fallback here would add an untestable branch guarding against a condition that does not exist.

*Alternative considered — file locking between planner and executor.* Rejected: `os.replace` is atomic at the filesystem level, so the reader either sees the old complete file or the new complete file. A lock would add a failure mode (stale lock stalls the executor) to solve a problem the rename already solves.

### 2. The executor guard must be a `threading.Lock`, not an `asyncio.Lock`

This is the single most important implementation detail in this change.

There are two entrants to `_tick()`:

- the scheduled loop — `executor/engine.py:1090`, running inside `_run_loop` (line 992), which is a **`threading.Thread`** (line 970) that calls **`asyncio.run`** (line 995), i.e. its own event loop in its own thread;
- `run_once()` — `executor/engine.py:981`, called from `backend/api/routers/executor.py:158` on the **FastAPI event loop in the main thread**.

An `asyncio.Lock` is bound to the event loop that created it and is not thread-safe. Copying the planner's `asyncio.Lock` pattern (`planner_service.py:49`) would produce a guard that **silently never blocks** — the bug would look fixed and would not be.

Use a `threading.Lock` created in `__init__`, acquired **non-blocking**:

```python
if not self._tick_lock.acquire(blocking=False):
    logger.warning("Executor tick already running, skipping concurrent request")
    return {"success": False, "skipped": True, "reason": "tick_already_running"}
try:
    ...
finally:
    self._tick_lock.release()
```

*Why non-blocking:* a blocking acquire queues ticks behind a slow one. The loop fires every 5 s; a 60 s tick would leave twelve queued ticks firing back-to-back against stale state. Skipping is correct — the next tick is 5 s away.

*Where to put it:* wrap the body of `_tick()` itself, not the two call sites. A guard at the call sites has to be duplicated and can be bypassed by a third caller.

*Why the skip is logged at WARNING:* the silent-skip failure mode is precisely what made the retry-timezone bug invisible for so long (see `openspec/changes/archive/2026-09-18-fix-planner-retry-timezone`). Every rejected entrant must leave a trace.

### 3. Remove battery cost rather than optimize it

The obvious cheap fix is to skip the write when nothing changed — prod logs show the identical row (`1.218 SEK/kWh`, grid `0.00`, pv `0.00`) rewritten every 5 s for hours. Rejected: the value has no reader, so the correct amount of work is zero, not less. Removing it also deletes the per-tick Nordpool fetch and the per-tick engine construction, which the optimization would have kept.

The planner's battery economics are unaffected. They come from `battery_economics.battery_cycle_cost_kwh` in config (`planner/solver/adapter.py:459`, `backend/api/routers/energy.py:241`, `backend/api/routers/analyst.py:185`) — a separate mechanism. The `battery-cost-integrity` spec governs *that* config parameter and needs no change.

### 4. One conditional migration for all nine tables

New revision with `down_revision = "3fa1a48708be"` (current head; production is confirmed at that revision).

Drop conditionally, via the inspector, rather than a bare `op.drop_table`:

```python
inspector = sa.inspect(op.get_bind())
existing = set(inspector.get_table_names())
for table in DEAD_TABLES:
    if table in existing:
        op.drop_table(table)
```

*Why conditional:* `op.drop_table` on a missing table raises and aborts the upgrade. Not every install necessarily has all nine (some may have been created by `create_all` rather than the baseline). The baseline migration already uses this `if ... not in existing_tables` idiom.

`downgrade()` recreates all nine empty, for rollback parity — the precedent is `alembic/versions/8dfd5256374c_drop_dead_schedule_planned_table.py`, which this migration should mirror in structure. Column definitions come from the current `backend/learning/models.py` classes before deletion.

*Alternative considered — leave the tables, remove only the code.* Rejected by explicit user decision: a table nothing uses is exactly the confusion this change exists to remove.

### 5. Resolve the schedule path from one constant

Define `DEFAULT_SCHEDULE_PATH = Path("data/schedule.json")` in `planner/output/schedule.py`, use it as `save_schedule_to_json`'s default, and import it at `planner/pipeline.py:816`. One symbol, so writer and reader cannot drift apart again.

The executor keeps reading `self.config.schedule_path` (`executor/config.py:294`, same default) — it is configurable by design and already correct.

Additionally, when the previous schedule is missing or has an empty `schedule` list, log at WARNING. Today both cases pass silently, which is why this went unnoticed for months.

*Not done here:* deleting the stale `/app/schedule.json` stub on disk. It is a deployment artifact, not code; once nothing reads it, it is inert.

## Risks / Trade-offs

**[The migration is the only irreversible step, and it runs on beta testers' live databases.]** → Drop is conditional so it cannot abort mid-upgrade, and `downgrade()` restores all nine schemas. The tasks must require a database backup before the migration step. Risk is low in substance — no code reads these tables — but it is the one step that cannot be undone by reverting a commit.

**[A blocking lock acquire would turn a 5-second cadence into a backlog.]** → `acquire(blocking=False)` is mandatory, and a test must assert that a second concurrent entrant returns immediately with `skipped: True` rather than waiting.

**[An `asyncio.Lock` would look correct in review and do nothing at runtime.]** → Covered in Decision 2. The test for this must drive the two entrants from *different threads* (mirroring loop-thread vs. API-thread); a single-threaded `asyncio` test would pass against the broken implementation.

**[Removing `training_episodes` deletes a write path someone might have intended to switch on.]** → It has been unreachable since the flag was introduced (no config key, no UI, 0 rows in 9 months) and its target consumer, Antares, no longer exists. `bin/inspect_episodes.py` goes with it. Recoverable from git if ever wanted.

**[Fixing the schedule path turns mid-block locking on for the first time.]** → This is a genuine behavior change, not a no-op: water heaters mid-block will now have their remaining slots forced on. That is the specified behavior (`openspec/specs/planner/spec.md:240`), but it will alter schedules on live systems, so it belongs in the release notes rather than passing as a silent fix.

**[`GET /api/learning/status` loses its `training_episodes` field.]** → No frontend reference exists (`rg training_episodes frontend/src/` → 0 hits). Any external consumer would be reading a permanent `0`.

## Migration Plan

1. Back up `data/planner_learning.db` before running the migration.
2. `alembic upgrade head` — drops the nine tables.
3. Rollback, if needed: `alembic downgrade -1` recreates all nine empty; the removed code returns by reverting the commit. No data is recoverable from the dropped tables, which is acceptable because none of it was read.

## Open Questions

None. Root causes are confirmed against production logs, the atomic-replace behavior is verified on the production mount, the current Alembic head is confirmed to match production, and the two scope decisions (drop the tables outright; ship all five fixes as one change) were made explicitly by the user.
