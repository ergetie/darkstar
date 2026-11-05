## Context

See proposal for evidence. Relevant facts: the executor writes to the same SQLite file as the monitors (`engine._get_db_path`, `monitors._db_path` both honour `DB_PATH`); the `system_state` key/value table already exists (alembic `b4c2b7eb00b2`); the monitor opens the DB read-only. Executor tick interval defaults to 300 s (`executor/config.py:365`), but can be shorter.

## Goals / Non-Goals

**Goals:** never send HA an out-of-range number; make failures explain themselves; make the success rate true; keep the EV heuristic out of command success.
**Non-Goals:** changing max-discharge config semantics (defined by the archived `battery-power-limits-unification`, `planner/battery_limits.py`), UI changes, DB schema changes, per-user constants.

## Decisions

**D1. Entity-range clamp is a pure helper plus a thin async wrapper (actions.py).**
`_clamp_to_entity_range(value, attributes) -> (value, note|None)` is pure and unit-tested. Algorithm: parse `min`, `max`, `step` as finite floats, ignoring anything else (including `any`, `unknown`, `unavailable`, step <= 0). Clamp to `[min, max]`. If `step`: `snapped = base + round((v - base) / step) * step` with `base = min or 0`; if `snapped > max` use `base + floor((max - base) / step) * step`; if `snapped < min` use ceil analogue; round float noise to 9 decimals. Negative `min` falls out of the same formula. Note: Python `round` is banker's rounding; use `math.floor(x + 0.5)` for deterministic half-up.
The profile path replaces `get_state_value(entity_id)` with `get_state(entity_id)` (the full state dict is the "state already fetched"), derives `previous_value` from it, and clamps `resolved_value` (domains `number`/`input_number` only) before `_values_match` and the deadband check. `_write_entity` additionally accepts an optional `entity_state` and applies the same clamp for number domains (fetching state once if not supplied), so the other numeric call sites (water temp, balanced load, `max_export_power`, EV setpoints) are covered without bespoke code (the direct `set_number`/`set_input_number` calls in `set_water_temp`, `set_max_export_power` and `set_ev_charger_current` now go through `_write_entity(..., raise_errors=True)` with `_number_domain(entity_id)`). Verification compares against the clamped value everywhere: the profile path clamps before `_values_match`/deadband/verify, and the non-profile paths (`set_water_temp`, `_set_max_export_power`, `set_ev_charger_current`) read the entity once through `_read_number_target(entity, value)`, which returns `(current_state, clamped_value, entity_state)`. Skip checks, the write (`entity_state` passed on so `_write_entity` does not refetch), the `_verify_action` read-back and `ActionResult.new_value` all use the clamped value. Without this, a clamped write would have been read back against the unclamped target: it could not flip `success` (it comes from the write itself; `verification_success` is only recorded in `execution_log`), so no failed tick and no error log, but it would have recorded `verification_success=false`, waited the full 2 s verify window every time and, for water temp / export power / EV current, re-sent the clamped value on every tick because the skip check compared against the unclamped target.
Rate limiting: `self._clamp_log_at: dict[str, float]` (monotonic) allows one warning per entity per hour, else debug.

**D2. Source clamp in the controller.** Add `_max_discharge_power_w()` returning `config.max_discharge_w` for unit W, else `config.max_discharge_a * config.nominal_voltage_v`; non-positive disables. Apply `min()` to `export_power_w` and, after step rounding, to `export_with_load_w`. D1 remains the universal safety net for entities with a tighter limit than the config.

The rule is the one defined by the archived `battery-power-limits-unification` (`planner/battery_limits.py`: `resolve_control_unit` / `resolve_battery_power_limits`: W uses `max_discharge_w`, A uses `max_discharge_a` x nominal battery voltage). The helper mirrors it instead of importing it: those functions take the raw config dict, while the controller only holds the typed `ControllerConfig`/`InverterConfig`, and the executor imports no planner code (that change also kept the executor's own unit resolution out of scope). The typed `ControllerConfig.nominal_voltage_v` is already resolved with the same `nominal_voltage_v` / `system_voltage_v` / 48 V fallback. The unit follows the profile's `behavior.control_unit` first, else `executor.inverter.control_unit`, like the "configured max limits" block of `_follow_plan`; this agrees with the planner resolver whenever the profile and config units agree (SystemTab keeps them in sync). One difference: `ControllerConfig` keeps its own defaults (`max_discharge_a` 185, `max_discharge_w` 5000) where the planner resolver yields 0 for a missing limit, so an unconfigured limit clamps at the default rather than disabling. This cannot cut a legitimately planned export: (a) a planner config without a discharge limit (resolved 0) is rejected by `KeplerConfig` validation (`planner/solver/types.py`, "Battery cannot discharge"), so no plan exists in that state; (b) `config.default.yaml` ships the same 185 A / 5000 W, so unconfigured installs use identical numbers in planner and executor; (c) the two existing executor clamps (`_follow_plan` discharge/charge limits, `controller.py` ~216 and ~347) already use these same `ControllerConfig` values, so the new clamp is consistent with them; (d) the clamped templates (`export_power_w`, `export_with_load_w`) are written to forced-discharge power entities, i.e. battery discharge targets, which cannot exceed the discharge limit anyway. A planned grid export above the limit (PV surplus) never reaches those entities as a discharge target.

**D3. Error text.** The profile path calls `_write_entity(..., raise_errors=True)` inside `try/except HACallError`, mirroring the water paths (`actions.py:1062-1067`). `ActionResult` gains `ha_unavailable: bool = False`, true when `status_code is None`. Message: `Failed to set <entity>: <error>`.

**D4. Tick statistics: persisted in `system_state`, no schema change.**
New `executor/tick_stats.py` with class `TickStats`: in-memory dict of hourly UTC buckets keyed `YYYY-MM-DDTHH` (UTC avoids DST ambiguity); value `{"t": total, "f": failed, "a": {action_type: {"n": count, "entity": id|null, "err": last error <=200 chars}}}`; at most 20 actions per bucket. JSON envelope `{"v": 1, "buckets": {...}}` under key `executor_tick_stats`. API: `record(now, failures: list[(action, entity, error)])`, `to_json()`, `from_json()`, `prune(now)` (drop buckets older than 25 h). `ExecutionHistory` gains sync `get_system_state(key)` / `set_system_state(key, value)` (raw SQL upsert on `system_state`; `updated_at` ISO). The engine loads at init, records in `_tick_unlocked`, and flushes when dirty and at least 30 s since the last flush, plus on stop. Flush errors are logged at debug and never raise. The only writer is the executor; the monitor opens read-only, so no lock contention beyond WAL.
Alternatives rejected: new `executor_tick_stats` table (needs approval, unnecessary); counting execution_log rows (throttled, biased); reconstructing from `recent_errors` (in memory, lost on restart).

**D5. What counts as a tick.** Counted once per tick at the point action results exist (after step 6), only when not paused, disabled (toggle off), `shadow_mode`, `manual_override_active` (`skip_writes`) or holding on a stale/timestamp-less schedule. Paused and toggle-off are early returns; the stale hold is not (the tick continues with default slot values), so it is detected from `slot is None` plus `_stale_schedule_warning`. Ticks that raise before that point are counted from the outer `except` unless one of those conditions already applies. Failed if any `not r.success and not r.skipped`, or the outer `except` fires (action `engine_tick`). Failure reason is "HA unavailable" when `r.ha_unavailable` or the exception is an `HACallError` with no status / an aiohttp client or timeout error. `ev_charge_failed` and `_log_ev_action` rows never feed the counters. A failed tick counts once in `f` but each failing action counts in `a`.

**D6. Monitor evaluator.** `_eval_command_success` selects `value` from `system_state` (read-only), parses, sums buckets whose hour start is after `now_utc - 24h` (so window is 24-25 h, documented), and returns skipped when the key is absent, invalid, or total < `COMMAND_SUCCESS_MIN_TICKS = 12`. The rate threshold stays 0.95. Detail on violation: `tick success 94.20% over 24 h (82/1410 failed): charge_discharge_power failed 82× on input_number.darkstar_power_rec_w: <err>; <second action>`. Top two by count. The module docstring (`monitors.py:30-40`) is updated to describe the new basis.

**D7. EV charge failure becomes a notice.** `engine.py:2266-2270` drops `not ev_charge_failed` from `record.success`. When `_check_ev_charge_failure` fires the engine persists `executor_ev_charge_notice` = `{"active": true, "since": iso, "message": <same text as the notification>, "commanded": true, "actual_kw": x}`; it is cleared (`active: false`) when the counter resets (recovery or no longer commanded). Written only when an EV charger exists (`_has_ev_charger`). `_should_log_execution`'s "execution failed" reason stays valid (it keys off `record.success`). New invariant `ev_charge_delivery` in `INVARIANT_NAMES` and the evaluator map: violation while active (ignored when `since` older than 6 h), pass when inactive, skipped when absent. The monitors only log/hold episodes (no extra alert channel), so there is no double notification; the existing `notify_error` stays.

## Deviations from the original plan (as implemented)

- `_clamp_to_entity_range` additionally ignores `min`/`max` when `min > max` (contradictory attributes) and returns the original value object (same type) when nothing changes.
- `ExecutionHistory.get_system_state`/`set_system_state` use the SQLAlchemy `SystemState` model with a SQLite `INSERT .. ON CONFLICT DO UPDATE` instead of raw SQL; `updated_at` is a timezone-aware datetime from the history timezone (the column type), not a hand-built ISO string. No schema change.
- `TickStats` has a `dirty` flag and the `TickFailure` tuple alias; the engine seeds `_ev_notice_active` from `system_state` so a restart clears a stale active notice without a write on every tick.
- Failure error text gets an `HA unavailable: ` prefix when `ha_unavailable` or the tick exception is status-less/aiohttp/timeout; the tick counters are recorded before the execution record is created so a logging failure cannot hide a tick.
- Non-profile numeric writes use `_read_number_target` (see D1) replacing the plain `get_state_value` read, which also removes the extra GET in `_write_entity`.
- The three direct `set_number`/`set_input_number` calls were routed through `_write_entity(..., raise_errors=True)` via `_number_domain(entity_id)` (unknown prefixes fall back to `number`).

## Edge cases

- No EV: no notice written; invariant skipped.
- HA down: `get_state` returns None, so no attributes and the write proceeds unclamped (and fails, counted "HA unavailable").
- Restart: counters restored; skipped only while < 12 ticks exist.
- Attributes as strings (HA returns numbers or numeric strings): parsed with `float`, non-finite rejected.
- Negative min (-17500) and mixed-sign ranges: formula is sign-agnostic.
- Step float noise (0.1 steps): rounded to 9 decimals.
- Time: buckets are UTC, tests pin fixed instants and never depend on local DST; schedule-related fixtures use 96 quarter-hour slots.

## Risks / Trade-offs

- Extra `get_state` per non-profile numeric write -> one cheap GET only on actual writes (not skipped ones).
- Clamping can differ from plan (e.g., plan wants 18 kW, entity allows 17.5 kW) -> intended, warned once per hour.
- Controller clamp mirrors the planner's unit-aware limit rule -> one helper (`_max_discharge_power_w`) to update if that rule changes.

## Migration Plan

None required; keys are created on first flush. Rollback: remove code, keys are ignored.

## Resolved Decisions

1. Min ticks for `command_success`: 12. Approved.
2. `ev_charge_delivery` violation sends no extra notification (already notified by `notify_error`; the monitors only log episodes and show the existing health banner entry). Approved.
3. The 24 h window is bucketed by hour, so it spans 24-25 h (documented in the monitor docstring). Approved.
4. Non-profile numeric writes (water temp, `max_export_power`, EV current, balanced custom entities) are clamped inside `_write_entity`. SUPERSEDED during verify: the original approval allowed an unverified read-back for clamped non-profile writes, but analysis showed that it would record a false `verification_success=false`, add a 2 s wait and rewrite every tick, so water temp, `max_export_power` and EV current now verify and skip-check against the clamped value (D1). Balanced custom entities have no read-back verification (on/off values; `_write_entity` still clamps number domains).
