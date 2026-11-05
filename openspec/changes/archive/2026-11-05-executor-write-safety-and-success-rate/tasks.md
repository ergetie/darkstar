## 1. Entity-range clamp (actions.py)

- [x] 1.1 Add pure `_clamp_to_entity_range(value, attributes)` returning `(value, note | None)` per design D1 (half-up rounding via `math.floor(x + 0.5)`, snap from `min`, re-clamp into `[min, max]`, ignore non-numeric/`any`/non-positive step, 9-decimal noise rounding).
- [x] 1.2 In the profile action path (`executor/actions.py` ~813) replace `get_state_value` with `get_state`, derive `previous_value` from the state dict, and clamp `resolved_value` for `number`/`input_number` before `_values_match` and the deadband check; set `new_value` to the clamped value and note the requested value in the message.
- [x] 1.3 Add optional `entity_state` parameter to `_write_entity`; for number domains apply the same clamp (fetch state once when not supplied). Verify every `set_number`/`_write_entity` call site in `actions.py` (water temp, balanced load, `max_export_power`, EV setpoints) goes through it.
- [x] 1.4 Add rate-limited clamp logging (`_clamp_log_at`, one warning per entity per hour, else debug).

## 2. Error text on profile actions (actions.py)

- [x] 2.1 Add `ha_unavailable: bool = False` to `ActionResult`.
- [x] 2.2 In the profile path call `_write_entity(..., raise_errors=True)` in `try/except HACallError`; set `error_details=str(e)`, `ha_unavailable = e.status_code is None`, message `Failed to set <entity>: <error>`.

## 3. Source clamp (controller.py)

- [x] 3.1 Add `_max_discharge_power_w()` (W unit: `max_discharge_w`; A unit: `max_discharge_a * nominal_voltage_v`; non-positive = no clamp).
- [x] 3.2 Clamp `export_power_w` (~317) and `export_with_load_w` (after step rounding, ~324) with it. Do not touch charge/discharge clamping or anything owned by `battery-power-limits-unification`.

## 4. Tick statistics persistence

- [x] 4.1 Add sync `get_system_state(key)` and `set_system_state(key, value)` (raw SQL upsert on `system_state`) to `executor/history.py`. No migration.
- [x] 4.2 Create `executor/tick_stats.py` with `TickStats` (hourly UTC buckets, `record`, `prune` at 25 h, `to_json`/`from_json` with `{"v":1}` envelope, 20-action cap, 200-char error cap; tolerant of corrupt JSON).
- [x] 4.3 Wire into `ExecutorEngine`: load at init; record once per executed tick after step 6 (skip when paused, disabled, shadow, `skip_writes`, stale-schedule hold); failed if any non-skipped failed action or the outer `except` (action `engine_tick`); reason "HA unavailable" when `ha_unavailable` or an `HACallError` without status / aiohttp client/timeout error; flush when dirty and >= 30 s since last flush and on stop; swallow and debug-log flush errors.
- [x] 4.4 Ensure `_log_ev_action` rows and `ev_charge_failed` never feed the counters.

## 5. Monitor (backend/monitors.py)

- [x] 5.1 Rewrite `_eval_command_success` to read `system_state.executor_tick_stats` read-only, sum buckets in the trailing 24 h, add `COMMAND_SUCCESS_MIN_TICKS = 12`, skipped when absent/invalid/too few; keep `COMMAND_SUCCESS_MIN = 0.95`.
- [x] 5.2 Build the violation detail naming the top two failing actions with count, entity and last error (design D6 format); update the module docstring basis (~lines 30-40) and remove the stale throttling comment in the evaluator.
- [x] 5.3 Add `ev_charge_delivery` to `INVARIANT_NAMES` and the evaluator map, reading `executor_ev_charge_notice` (violation when active and < 6 h old, pass when inactive, skipped when absent).

## 6. EV charge failure as a notice (engine.py)

- [x] 6.1 Remove `not ev_charge_failed and` from the `success=` expression (~2266-2270).
- [x] 6.2 When `_check_ev_charge_failure` fires, persist `executor_ev_charge_notice` (`active`, `since`, `message`, `actual_kw`); clear it when the zero-power counter resets (recovery or not commanded). Skip entirely when `_has_ev_charger` is false.

## 7. Tests

- [x] 7.1 `tests/executor/test_executor_actions.py`: clamp helper cases (above max 18200 vs max 17500; negative range -18000 vs min -17500; step snap from min 50 -> 450; rounding past max 1040 -> 1000; missing/`unavailable`/`any` attributes; numeric string attributes; non-finite value); profile path writes the clamped value, skips when already at limit, and keeps working when `get_state` returns None; update existing tests that mock `get_state_value` for the profile path.
- [x] 7.2 `tests/executor/test_executor_actions.py`: HACallError with HTTP 400 and body populates `error_details` and message; status-less error sets `ha_unavailable`; clamp warning logged once per hour (use a patched monotonic clock).
- [x] 7.3 `tests/executor/test_executor_controller.py`: `export_with_load_w` 12 kW + 6 kW load clamped to `max_discharge_w=17500`; ampere unit 40 A x 230 V -> 9200; zero export -> 0; step rounding then clamp. Use a fixed 96-quarter-hour slot fixture on a pinned date (e.g. 2026-03-28 and 2026-10-25 not required; use 2026-06-15).
- [x] 7.4 New `tests/executor/test_tick_stats.py`: record/prune with pinned UTC instants across an hour and day boundary, round-trip through the real `ExecutionHistory` on a temp sqlite file (not `/tmp`; use pytest `tmp_path`), corrupt JSON tolerated, 20-action cap, restart restores counters.
- [x] 7.5 `tests/executor/test_tick_stats.py` (engine wiring; covers): unthrottled counting (many healthy ticks, few logged rows -> counters equal ticks); paused/shadow/manual-override ticks not counted; HA down counted failed with "HA unavailable"; `ev_charger` rows not counted; `ev_charge_failed` leaves `record.success` true and writes/clears the notice.
- [x] 7.6 `tests/executor/test_ev_charge_failure_detection.py`: update the assertion that expected `success = 0`; add notice persisted, cleared on recovery, not written without EV.
- [x] 7.7 `tests/backend/test_monitors.py`: replace execution_log-based command_success tests; cover pass (18/1321), violation message naming action/entity/error (82/1410), skipped for < 12 ticks and absent key, buckets older than 24 h ignored with a pinned `now`; `ev_charge_delivery` violation/pass/skipped/stale-notice.
- [x] 7.8 Run `UV_NO_SYNC=1 uv run python -m pytest tests/executor tests/backend/test_monitors.py -v` and `./scripts/lint.sh`; fix findings.
