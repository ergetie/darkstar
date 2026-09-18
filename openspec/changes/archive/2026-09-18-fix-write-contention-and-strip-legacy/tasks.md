## 1. Atomic JSON write helper

- [x] 1.1 Create `backend/core/atomic_json.py` with `write_json_atomic(path, payload, *, encoder=None, indent=2)`: create a `tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=<target's parent>, prefix=f".{name}.", suffix=".tmp", delete=False)`, `json.dump` into it, close, then `Path(tmp).replace(target)`. Model it on `backend/core/ev_state.py:47` (`_write_ev_state_unlocked`).
- [x] 1.2 In `write_json_atomic`, on any serialization exception, unlink the temp file (`contextlib.suppress(OSError)`) and re-raise, so a failed write never replaces the target.
- [x] 1.3 Ensure the target's parent directory exists (`parent.mkdir(parents=True, exist_ok=True)`) before creating the temp file.
- [x] 1.4 Do NOT add an `EXDEV`/`EBUSY`/`ETXTBSY` streaming-copy fallback. `data/` is a directory bind mount where `os.replace` is verified working; a fallback here would be an untestable branch. (See design Decision 1.)
- [x] 1.5 Add `tests/core/test_atomic_json.py`: writes land correctly; a serialization failure leaves the original file byte-identical and leaves no `.tmp` file behind; the temp file is created in the target's own directory.

## 2. Single schedule path constant

- [x] 2.1 In `planner/output/schedule.py`, add `DEFAULT_SCHEDULE_PATH = Path("data/schedule.json")` at module level and use it as the default for `save_schedule_to_json`'s `output_path` parameter (currently the literal `"data/schedule.json"` at line 46).
- [x] 2.2 In `planner/pipeline.py`, replace the hardcoded `Path("schedule.json")` at line 816 with an import of `DEFAULT_SCHEDULE_PATH` from `planner.output.schedule`.
- [x] 2.3 Leave `executor/config.py:294` (`schedule_path`) alone — it is user-configurable by design and already defaults to `data/schedule.json`.

## 3. Atomic schedule writes

- [x] 3.1 Replace the `with Path(output_path).open("w", ...)` + `json.dump` block at `planner/output/schedule.py:115-116` with a `write_json_atomic` call, passing the existing `DateTimeEncoder` as the encoder.
- [x] 3.2 Replace the `with schedule_path.open("w")` + `json.dump` block at `backend/api/routers/schedule.py:514-515` with a `write_json_atomic` call, preserving the existing `default=str` behavior.
- [x] 3.3 Add `tests/planner/test_schedule_atomic_write.py`: after a simulated write failure the pre-existing schedule file is unchanged; a successful write produces valid JSON at the target and leaves no `.tmp` files in the directory.
- [x] 3.4 Add a guard test at `tests/utils/test_no_truncating_schedule_write.py` that greps non-test modules for a truncating open of the schedule path and fails naming the offending file. Mirror the structure of the existing guard `tests/utils/test_no_bare_tz_calls.py`.

## 4. Executor single-flight guard

- [x] 4.1 In `executor/engine.py.__init__`, add `self._tick_lock = threading.Lock()`. **It must be `threading.Lock`, not `asyncio.Lock`** — the scheduled loop runs in its own thread with its own event loop (`engine.py:970`, `:995`) while `run_once()` runs on the FastAPI loop in the main thread, so an asyncio primitive would never block and the guard would silently do nothing. (See design Decision 2.)
- [x] 4.2 Wrap the body of `_tick()` with `if not self._tick_lock.acquire(blocking=False):` → log `logger.warning("Executor tick already running, skipping concurrent request")`, set `self.status.last_run_status = "skipped"` and `self.status.last_skip_reason = "tick_already_running"`, and return `{"success": False, "skipped": True, "reason": "tick_already_running"}`. Release in a `finally`.
- [x] 4.3 Acquire with `blocking=False`, never a blocking acquire — a blocking acquire would queue ticks behind a slow one and fire them back-to-back against stale state.
- [x] 4.4 Guard the body of `_tick()` itself, not the two call sites (`run_once()` at line 981 and the scheduled loop at line 1090), so a future third caller cannot bypass it.
- [x] 4.5 Add `tests/executor/test_tick_single_flight.py`. The test MUST drive the two entrants **from different threads** to mirror loop-thread vs. API-thread; a single-threaded asyncio test would pass against a broken `asyncio.Lock` implementation. Assert: the second entrant returns immediately with `skipped: True`; only one tick body executes; the lock is released after a tick that raises.

## 5. Remove battery cost tracking

- [x] 5.1 Delete `backend/battery_cost.py`.
- [x] 5.2 Delete `_update_battery_cost` (`executor/engine.py:2413-2491`) and its call site at `executor/engine.py:1815`.
- [x] 5.3 Confirm the per-tick `get_nordpool_data` import and call inside `_update_battery_cost` (lines 2464-2466) go with it, and that no other executor code path depends on that fetch.
- [x] 5.4 Remove battery-cost tests: `tests/executor/test_executor_engine.py` lines 1179, 1551-1577, 1623.
- [x] 5.5 Verify `battery_economics.battery_cycle_cost_kwh` remains untouched — it is a separate mechanism used at `planner/solver/adapter.py:459`, `backend/api/routers/energy.py:241`, and `backend/api/routers/analyst.py:185`, and is governed by the `battery-cost-integrity` spec.

## 6. Remove training-episode paths

- [x] 6.1 Remove the `debug.enable_training_episodes` gate and its body from `log_training_episode` (`backend/learning/engine.py:111-126`), keeping step 2 (`store_plan`) intact.
- [x] 6.2 Remove `store_training_episode` and `get_episodes_count` from `backend/learning/store.py`, and the `TrainingEpisode` import at line 22.
- [x] 6.3 Remove the `training_episodes` field from the `get_status()` return value at `backend/learning/engine.py:344` and its `episodes = await self.store.get_episodes_count()` call.
- [x] 6.4 Delete `bin/inspect_episodes.py`.
- [x] 6.5 Remove the `("training_episodes", "Training Episodes")` row from `scripts/health_check.py:251`.
- [x] 6.6 Remove `test_store_training_episode` from `tests/ml/test_learning_engine.py:142-148`.

## 7. Remove dead ORM models

- [x] 7.1 Before deleting, copy each class's column definitions out of `backend/learning/models.py` — they are needed verbatim for the migration's `downgrade()` in task 8.3.
- [x] 7.2 Delete these classes from `backend/learning/models.py`: `SensorTotal` (140), `TrainingEpisode` (148), `RealizedEnergy` (159), `DailyWater` (170), `StrategyLog` (194), `AntaresRLRun` (213), `AntaresTrainingRun` (230), `AntaresPolicyRun` (247), `BatteryCost` (257).
- [x] 7.3 Do NOT delete `ReflexState` (204) — it is live, used by `backend/learning/reflex.py` and `backend/learning/store.py`.
- [x] 7.4 Grep for each deleted class name across the repo and fix any remaining import or reference.

## 8. Database migration

- [x] 8.1 Create a new Alembic revision with `down_revision = "3fa1a48708be"` (the current head; production is confirmed at this revision).
- [x] 8.2 `upgrade()`: build `existing = set(sa.inspect(op.get_bind()).get_table_names())` and drop each of the nine tables only `if table in existing`. A bare `op.drop_table` on a missing table raises and aborts the upgrade; the baseline migration already uses this conditional idiom.
- [x] 8.3 `downgrade()`: recreate all nine tables empty, using the column definitions saved in task 7.1, for rollback parity. Mirror the structure of `alembic/versions/8dfd5256374c_drop_dead_schedule_planned_table.py`.
- [x] 8.4 Test the migration against a copy of a real database: `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head` again, all clean.
- [x] 8.5 Test `alembic upgrade head` against a database where some of the nine tables are already absent, to confirm the conditional drop does not abort.

## 9. Fix mid-block locking detection

- [x] 9.1 With task 2.2 applied, verify `previous_schedule` at `planner/pipeline.py:812-822` now loads real slot data rather than an empty list.
- [x] 9.2 Add a warning log when the previous schedule file does not exist, fails to parse, or yields an empty `schedule` list — naming the path. Today all three pass silently, which is why this went unnoticed for months.
- [x] 9.3 Add a log line when a mid-block lock fires, including heater id and the number of slots locked (extend the existing message at line 877).
- [x] 9.4 Add `tests/planner/test_mid_block_locking.py`: a previous schedule with an actively heating heater produces non-empty `force_water_by_heater` for that heater and empty for an idle one; a missing or empty previous schedule logs a warning.
- [x] 9.5 Note in the change's release-notes entry that mid-block locking begins functioning for the first time — this alters live schedules and is a behavior change, not a silent fix.

## 10. Verification

- [x] 10.1 Grep the repo for `BatteryCostTracker`, `battery_cost`, `_update_battery_cost`, `TrainingEpisode`, `store_training_episode`, `get_episodes_count`, `enable_training_episodes`, `AntaresRLRun`, `AntaresTrainingRun`, `AntaresPolicyRun`, `StrategyLog`, `DailyWater`, `SensorTotal`, `RealizedEnergy` — confirm zero hits outside migrations and archived docs.
- [x] 10.2 Run the full test suite and the project's lint/type checks; all green.
- [x] 10.3 Update `openspec/specs/` via the sync step for the five affected capabilities (`durable-schedule-write`, `executor-single-flight`, `executor`, `stabilization-hygiene`, `planner`).
- [x] 10.4 Remove the two handled entries from `docs/BACKLOG.md` (Schedule File Write Integrity; Concurrent Planner Run DB Contention), noting in the change that the DB item's suggested `busy_timeout` fix was not the actual cause.
