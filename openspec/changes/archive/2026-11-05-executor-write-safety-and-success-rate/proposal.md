## Why

A production install (Solinteg custom profile using `{{export_with_load_w}}`) wrote 17400-18200 W to `input_number.darkstar_power_rec_w`, whose HA `max` was 17500 (earlier 17200). HA rejected every such write: 82 failures on 2026-09-22 and 314 over Sep-Oct. Three defects made this hard to see and fix:

1. Darkstar never reads an entity's `min`/`max`/`step` before writing a number. `export_with_load_w` (`executor/controller.py:316-326`, built as export + load rounded to step) and `export_power_w` (`controller.py:317`) are never clamped, while charge values are (`controller.py:436`, `:457`). Templates using them: `profiles/fronius.yaml:115` (`export_with_load_w`), `profiles/generic.yaml:133`, `profiles/deye.yaml:131`, `profiles/sungrow.yaml:134` (`export_power_w`).
2. `_write_entity` (`executor/actions.py:617-653`) swallows the `HACallError`, so the profile-action `ActionResult` carries `error_details=None` and the message "Failed to set X" (`actions.py:876-896`). Users cannot see why a write failed.
3. The `command_success` monitor (`backend/monitors.py:255-284`, threshold `COMMAND_SUCCESS_MIN` at `:72`) computes its rate over `execution_log` rows. Rows are throttled (`executor/engine.py:3047-3110`: healthy ticks only on change or 15 min heartbeat, failures always), so failures are over-weighted (true ~94.2 % vs reported 57.5 %). Per-write `source='ev_charger'` rows (`engine.py:4850-4910`) are also counted. The message names no action. In addition, the EV zero-power heuristic (`_check_ev_charge_failure`, `engine.py:4287`) sets `success=0` on the tick record (`engine.py:2266-2270`) with no error or action, so an EV that merely draws no power fails "command success" with no explanation.

Evidence: `debugging/command-success-2026-11/`.

## What Changes

- Numeric writes are clamped to the entity's `min`/`max` and snapped to `step`, using the entity state already fetched before the write. Missing attributes: write unchanged. Clamping is logged, rate-limited.
- `export_power_w` and `export_with_load_w` are clamped at the source in the controller to the configured max discharge power.
- Profile-action failures carry the HA error text in `ActionResult.error_details` (and the message).
- The executor counts every executed tick unthrottled (total, failed, failed per action with entity and last error) and persists hourly buckets in the existing `system_state` key/value table (key `executor_tick_stats`). **No DB schema change.** `command_success` reads those buckets; `ev_charger` rows and `execution_log` are no longer used for the rate.
- The monitor message names the top failing actions, entity and error text.
- EV zero-power charge failure no longer fails the tick record; it is persisted as an EV notice (`system_state` key `executor_ev_charge_notice`) and surfaced as a new invariant `ev_charge_delivery`.
- **BREAKING (behavioural, internal):** `execution_log.success` no longer turns 0 for `ev_charge_failed`; the existing ev-charge-failure-detection requirement is modified accordingly.

## Capabilities

### New Capabilities
- `executor-write-safety`: entity-range clamping of numeric writes, source clamping of export power, error text on failed profile actions.

### Modified Capabilities
- `runtime-invariant-monitors`: `command_success` from unthrottled persisted tick counters with failing-action message; new `ev_charge_delivery` invariant.
- `ev-charge-failure-detection`: the heuristic no longer marks the tick as failed; it raises its own notice.

## Impact

- Code: `executor/actions.py`, `executor/controller.py`, `executor/engine.py`, `executor/history.py`, new `executor/tick_stats.py`, `backend/monitors.py`.
- Data: new JSON values under two `system_state` keys; no migration.
- Coordination: `battery-power-limits-unification` (archived) defined the unit-aware battery limit in `planner/battery_limits.py`. The controller reads the max discharge power through a single helper (`_max_discharge_power_w`) that mirrors that rule from the typed executor config (see design D2); this change does not modify the planner module.
- Tests: `tests/executor/test_executor_actions.py`, `test_executor_controller.py`, `test_ev_charge_failure_detection.py`, `test_execution_log_throttling.py`, new `tests/executor/test_tick_stats.py`, `tests/backend/test_monitors.py`.
