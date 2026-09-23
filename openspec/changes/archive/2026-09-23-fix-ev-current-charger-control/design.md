## Context

Production test 2026-09-23 (go-e, `type: current`, `switch_entity: select.go_echarger_417263_frc`, `charge_enabled_value: charge`, `charge_disabled_value: dont_charge`, `min_current_a: 6`):

- `_control_ev_charger_current` (`executor/engine.py:3229`) only writes to `current_entity`. The binary path's switch logic is skipped by `continue` at `engine.py:3048`. The go-e remained `dont_charge` → 0 kW.
- Stop writes `set_ev_charger_current(entity, 0)` (`engine.py:3293`) → HA 500 (entity min 6) → 4 retries each tick → 7 s ticks.
- EV `ExecutionRecord`s are only written inside `if result.success` (`engine.py:3104, 3148, 3300, 3340`). Phase-mode results only appear inside the native tick record.
- `KeplerResult.ev_shortfall_kwh` (`types.py:197`) is computed but never consumed. The EV status (`ev.py:_compute_status`, `pipeline.py:_ev_charger_status`) is a pure `max_power × hours_left` heuristic → "ON TRACK" while 0 kWh is scheduled.
- `timeLimit=30` is hardcoded (`kepler.py:849/853`). CBC returns status "Optimal" with its incumbent when it stops at the limit, so the timeout branch (`kepler.py:876`) never runs. Every production solve today took about 30.1 s.
- The config loader already loads `switch_entity` and the enabled/disabled values for every charger type (`executor/config.py:666-681`).

## Goals / Non-Goals

**Goals:**
- Current chargers actually start and stop via user-configured switch values.
- Every EV action is traceable in the execution log and in the Executor UI.
- A goal that won't be met is shown as such in the UI, with the reason.
- The solver time limit is configurable, and hitting it is visible.

**Non-Goals:**
- Changing battery source isolation (the full discharge block stays; user decision).
- Making the solver faster (separate work). This change only raises the limit and makes hitting it visible.
- A DB schema change.

## Decisions

1. **Start/stop order for current chargers.**
   - Start: write the setpoint first (clamped to `[min, max]`), then set `switch_entity` to `charge_enabled_value`. This way the car never starts at a stale high current.
   - Stop: set `switch_entity` to `charge_disabled_value` only. The amps value is left as it is (a later start overwrites it).
   - Idempotency: each write is skipped when HA already holds the target. The switch state is re-checked every tick, like the binary path, so an external change (the go-e app) gets corrected.
   - Alternative rejected: writing `min_current_a` to "stop". That doesn't stop charging.

2. **Pause paths share one stop routine.** The load-balancer pause, the below-minimum target, the end of the plan and the safety timeout all call a single `_stop_current_charger()` that uses the switch. Keep-on still closes the switch at `min_current_a`.

3. **`switch_entity` is required for `type: current`.** It is checked by config validation (`executor/config.py`, the backend settings validator) and by the settings editor (a required field; save is blocked when it's missing). For select-like entities, the existing rule that the two values must be non-empty and different applies. A missing value causes a startup validation error naming the charger, not silent planning-only behaviour. Alternative rejected: falling back to a 0 A write. That was proven broken on go-e.

4. **EV action logging.**
   - One helper, `_log_ev_action(charger_id, result, mode)`, is called for every EV dispatch result (switch on/off, setpoint, stop, phase mode), whether it succeeded or failed.
   - Records use `source="ev_charger"`. `commanded_work_mode` is one of `ev_charge_start | ev_charge_stop | ev_charge_current | ev_phase_mode`, `success` reflects the result, and `error_message` holds the error details.
   - `action_results` carries `charger_id`, `new_value` (the amps or option sent) and `previous_value`.
   - Dedup: an identical consecutive failure (same charger, action, value, error) within 5 minutes is not re-recorded. A repeat counter is kept in memory, and the next record states "repeated N×".
   - Skipped (already-at-target) results are not recorded, to avoid noise.

5. **Per-charger failure backoff.** After a failed EV write, further writes to that charger are skipped for `min(60 s × 2^(n-1), 10 min)`. The backoff resets on success or when the desired state changes (for example a new plan). This prevents the 7 s tick stall. The dispatcher's retry-with-backoff inside one call is unchanged.

6. **History source filter.** `GET /api/executor/history` gets an optional `source` parameter (`native | ev_charger`), filtered in `executor/history.py`. The Executor page gets a segmented filter (All / Inverter / EV) and `MODE_BADGES` entries for the EV modes. EV rows render charger id, value and error in the existing action-results group view.

7. **Shortfall diagnostics.**
   - After the solve, the pipeline builds per-charger `{required_kwh, scheduled_kwh, shortfall_kwh, reason}` using `KeplerResult.ev_shortfall_kwh` and the scheduled energy.
   - Reason classification, applied only when shortfall > 0.01 kWh, over the eligible slots (`end_time ≤ deadline`, `start ≥ now`):
     - no eligible slots → `deadline_too_close`
     - every eligible slot has `max_import_kw·h − (load + water + other EV energy in that slot) < min_power_kw·h` → `grid_limit` (battery discharge is blocked while the EV charges, so the grid must cover everything)
     - otherwise → `cost_tradeoff`
   - The result is persisted in schedule.json meta as `ev_goal_diagnostics[charger_id]`. The existing ZERO warning is extended with the reason.
   - `ev.py` status: when the diagnostics for the current plan show shortfall > 0.01, the status is `at_risk` and `shortfall_kwh`/`shortfall_reason` are added. Otherwise the existing heuristic is kept. Diagnostics tied to an older goal are ignored: they must match the goal's deadline and required energy within 0.05 kWh.
   - The EV card shows an amber "AT RISK" pill and a line such as "0.6 kWh won't be delivered by 18:00 — grid limit (8 kW) leaves no room".

8. **Solver time limit.**
   - `kepler.solver_time_limit_s` (default 60, validated range 10–600) is read by the adapter into `KeplerConfig.solver_time_limit_s` and passed to CBC/GLPK.
   - After the solve, `time_limit_hit = solve_duration ≥ limit − 0.5 s`. When true, the planner logs a WARNING even if the status is "Optimal", and `time_limit_hit` is set on the result and in schedule meta. The non-optimal timeout branch uses the configured limit instead of the literal 30.
   - Settings UI gets a numeric field under advanced solver settings, plus help text.

## Risks / Trade-offs

- [BREAKING validation for current chargers without a switch] → A clear validation message names the charger. Production already has `switch_entity` set.
- [Dedup hides a failure that keeps repeating] → The repeat count is carried into the next record, and the logger still warns on every attempt made outside backoff.
- [Backoff delays a legitimate retry after HA recovers] → The cap is 10 min, and the backoff resets when the desired state changes.
- [A 60 s solve delays the plan] → Acceptable. No API/proxy timeouts were found on `/api/run_planner`.
- [The grid_limit reason heuristic can misclassify combined cases] → It falls back to `cost_tradeoff`. The reason is only used for display.

## Migration Plan

- `config.default.yaml`: add `kepler.solver_time_limit_s: 60`. The config migration adds the key when it's missing.
- No DB migration. Rollback = revert. Old history rows are unaffected.
