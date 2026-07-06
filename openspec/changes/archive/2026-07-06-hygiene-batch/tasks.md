# Tasks — hygiene-batch

Each task is self-contained. File paths and line numbers are from the current tree; if a line has shifted, match on the quoted code. After each group, run `uv run python -m pytest` for the touched area. Full gate is group 8.

## 1. Remove dead `schedule_planned` table (#1)

- [x] 1.1 In `backend/learning/models.py`, delete the entire `class SchedulePlanned(Base)` block (currently ~lines 159-165: `__tablename__ = "schedule_planned"`, `id`, `date` with `index=True`, `planned_kwh`, `created_at`). Leave the classes before (`...config_overrides_json`) and after (`class RealizedEnergy`) intact.
- [x] 1.2 Grep the whole repo for `SchedulePlanned` and `schedule_planned`. Confirm zero remaining references in `backend/`, `planner/`, `executor/` (test fixtures/migrations may still mention it until 1.3). If any live reader/writer exists, STOP — the finding's premise (dead table) is wrong; report it.
- [x] 1.3 Get the current migration head: `uv run alembic heads`. Create a new revision file `uv run alembic revision -m "drop dead schedule_planned table"`; set its `down_revision` to that head. In `upgrade()` call `op.drop_table("schedule_planned")`. In `downgrade()` recreate the table with the same 5 columns (id PK autoincrement, date String indexed, planned_kwh Float, created_at String) — empty, for rollback parity only.
- [x] 1.4 Verify: on a scratch copy of the DB (never the production file), `uv run alembic upgrade head` succeeds and the table is gone; `uv run alembic downgrade -1` recreates it empty. Do NOT run against production — the operator deploys migrations.

## 2. Executor history: per-thread connections (#19)

- [x] 2.1 In `executor/history.py` (~lines 85-100, the `create_engine` call using `poolclass=StaticPool`), remove `poolclass=StaticPool`. Keep `connect_args={"check_same_thread": False, "timeout": 30.0}` and the WAL `PRAGMA` exactly as-is (SQLAlchemy then uses its default `QueuePool` for the file URL). Remove the now-unused `StaticPool` import if nothing else uses it.
- [x] 2.2 Verify: run the executor-history tests (`uv run python -m pytest tests -k "history or executor_history"`) — all green. Confirm WAL is still enabled (the pragma block is unchanged).

## 3. Config truthfulness (#20)

- [x] 3.1 Delete the dead key `executor.controller.inverter_ac_limit_kw` from both `config.yaml` and `config.default.yaml`. Confirm via repo grep that `inverter_ac_limit_kw` is read by no code (the live limit is `system.inverter.max_ac_power_kw`, read at `planner/solver/adapter.py:434-438`).
- [x] 3.2 Single-source `charge_efficiency`: in `executor/config.py` (~line 527, `ControllerConfig` loader), change the resolution so it reads `battery.charge_efficiency` from the top-level config when present, and only falls back to `ctrl_data.get("charge_efficiency", ...)` / the `0.92` class default when the battery section omits it. Then remove the `executor.controller.charge_efficiency` key from `config.yaml` and `config.default.yaml`.
- [x] 3.3 Behavior-preservation check (REQUIRED): with this instance's config (`battery.charge_efficiency: 0.92`), load config and assert the executor controller's resolved `charge_efficiency == 0.92` (unchanged). Verify the value still flows to `executor/engine.py:1924` (`getattr(self.config.controller, "charge_efficiency", 0.92)`).
- [x] 3.4 Document timestamp conventions: add a short comment where the mixed conventions live — `slot_start` is local ISO with offset; `slot_plans.created_at` is naive UTC via `func.current_timestamp()` (`backend/learning/store.py:359`); `execution_log.executed_at` is local ISO. One comment block near each write site noting "compare only after converting to a common tz". No code change.

## 4. Missing `generated_at` is stale (#23a)

- [x] 4.1 In `executor/engine.py` `_load_current_slot` (~lines 1582-1603): today the staleness block only runs `if generated_at_str:` and falls through (treated as fresh) when it is empty. Change it so that a missing or unparseable `generated_at` sets `self._stale_schedule_warning` (e.g. "Schedule has no generated_at — holding") and does `return None, None`, instead of falling through to slot lookup. Keep the existing valid-and-recent path unchanged.
- [x] 4.2 Safety check (REQUIRED): confirm no schedule the system writes itself lacks `meta.generated_at` (planner pipeline / `store` / any fallback writer). If a system-written schedule can omit it, fix that writer to always stamp `generated_at` FIRST, so the executor never rejects its own output. **Found and fixed a real gap:** `planner/output/schedule.py` only stamped `meta.planned_at`, never `meta.generated_at` — the sole system writer of `schedule.json`. Added `generated_at` (same timestamp) alongside the existing `planned_at` (kept for other consumers: frontend, `planner_service.py`). Without this fix, 4.1 would have made the executor reject every schedule the planner produces.

## 5. Meter-delta plausibility ceiling (#23b)

- [x] 5.1 Add config `recorder.max_meter_delta_kwh` (default `50.0`) to `config.default.yaml` under a `recorder:` section, with a comment: "reject cumulative-meter deltas above this per-slot ceiling (~200 kW sustained); physically impossible spikes are dropped, not recorded."
- [x] 5.2 In `backend/recorder.py` `RecorderStateStore.get_delta` (lines 88-176), after the time-proportional scaling block and before `return delta, True` (line 176): if `delta` exceeds the configured ceiling, mirror the negative-delta path exactly — log a warning ("Implausible meter delta for {key}: {delta:.1f} kWh > ceiling"), keep the already-updated baseline (`self._state[key] = new_entry`; `self.save()`), and `return None, False`. Thread the ceiling in (constructor arg or read from config where the store is built); default 50.0 if unset.
- [x] 5.3 Verify no double-count: because the baseline advanced to `current_value`, the NEXT reading computes a normal delta. Add/adjust a unit test proving two consecutive spike-then-normal readings yield `(None, False)` then a correct positive delta.

## 6. Mock-entity startup warning (#25)

- [x] 6.1 At startup device/config validation (where enabled devices and their target entities are known — EV, water heater, inverter), add a check: for each ENABLED device, if its target entity id contains `mock` or `test` (case-insensitive), log one `WARNING` naming the device type and entity id (e.g. "EV charger is ENABLED but targets a mock/test entity: input_boolean.ev_mockup"). Non-blocking. Disabled devices and non-mock entities produce no warning.
- [x] 6.2 Verify: a unit test with an enabled device on `input_boolean.ev_mockup` emits exactly one warning; the same device disabled, or pointed at a real entity, emits none.

## 7. Update the fault-injection pins (#23)

- [x] 7.1 In `tests/fault_injection/test_sensor_anomalies.py`, flip `test_unit_outlier_spike_is_recorded_raw` from documenting the gap (currently asserts `valid is True` and `delta ≈ 500`) to asserting the new behavior: the 500 kWh spike returns `(None, False)`. Update the docstring to say the ceiling is now enforced.
- [x] 7.2 In the schedule-staleness fault-injection test, flip `test_schedule_without_generated_at_bypasses_age_check` (currently pins the lenient bypass) to assert that a schedule with no `generated_at` now yields no dispatched slot (held as stale). Update its docstring.

## 8. Verify + gate

- [x] 8.1 Run `uv run python -m pytest` — full suite green.
- [x] 8.2 Run `scripts/ci_local.sh` — all gates (ruff, pyright strict, pytest, OpenAPI, ESLint) pass.
- [x] 8.3 Sanity: start the backend locally; confirm it boots, the mock-entity warning fires for this instance's `ev_mockup`, and no schedule/config errors appear. (Deploy + the Alembic `upgrade head` on production is the operator's step, not part of apply.)
