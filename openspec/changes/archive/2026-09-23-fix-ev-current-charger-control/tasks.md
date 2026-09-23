## 1. Current-charger switch control (executor)

- [x] 1.1 Add `_stop_current_charger()` in `executor/engine.py`. It sets `switch_entity` to `charge_disabled_value` (select-like) or `off` (switch-like) and never writes 0 A. Route every stop path in `_control_ev_charger_current` through it: target None, below minimum, plan end, balancer pause, safety timeout, override/force_stop.
- [x] 1.2 Start path: write the clamped setpoint, then set `switch_entity` to `charge_enabled_value`/`on`. Both writes are idempotent. Re-check the switch every tick while charging is desired.
- [x] 1.3 Keep-on path: close the switch at `min_current_a`.
- [x] 1.4 Tests: go-e style select charger. Start sends amps then `charge`. Stop sends `dont_charge` with no `number.set_value`. Below-minimum pauses via the switch. An external `dont_charge` is corrected. Keep-on works.

## 2. Config validation (backend + UI)

- [x] 2.1 `executor/config.py` and the settings validator: enabled `type: current` chargers require a non-empty `switch_entity`. The error names the charger.
- [x] 2.2 Settings EV charger editor: the charging-control entity is required for type current, and save is blocked while it's missing. Update `config-help.json`.
- [x] 2.3 Tests: backend validation and editor (`EntityArrayEditor.evtype.test.tsx`).

## 3. EV action logging, dedup, backoff

- [x] 3.1 Add a `_log_ev_action(charger_id, result, mode)` helper that writes success and failure records (`source="ev_charger"`, error_message, charger_id, new_value). Replace the success-only logging at every EV site: binary on/off, current setpoint, stop, phase mode.
- [x] 3.2 Deduplicate identical consecutive failures within 5 min, carrying the repeat count into the next record.
- [x] 3.3 Per-charger failure backoff `min(60·2^(n-1), 600)` s. Reset on success or on a desired-state change.
- [x] 3.4 `executor/actions.py`: include the attempted value in failure logs and fix the failure message wording in `set_ev_charger_current`. Check the switch and phase-mode methods for the same problem.
- [x] 3.5 Tests: failed writes recorded, dedup count, backoff skips HA calls and resets on state change, phase-mode record.

## 4. Execution history source filter (backend + UI)

- [x] 4.1 `executor/history.py` and `GET /api/executor/history`: optional `source` filter, applied to the CSV export too.
- [x] 4.2 `frontend/src/pages/Executor.tsx`: All / Inverter / EV filter. Add `MODE_BADGES` for `ev_charge_start|stop|current|ev_phase_mode`. Details show charger id, value sent and error.
- [x] 4.3 Tests: API filter and UI rendering.

## 5. Goal shortfall diagnostics

- [x] 5.1 `planner/pipeline.py`: compute per-charger `required/scheduled/shortfall/reason` from `KeplerResult.ev_shortfall_kwh` and the slot inputs, following the design's classification. Persist `ev_goal_diagnostics` (with deadline) in schedule meta. Extend the ZERO warning with the reason.
- [x] 5.2 `backend/api/routers/ev.py`: `at_risk` status with `shortfall_kwh`/`shortfall_reason`, including the stale-goal guard.
- [x] 5.3 `EVChargingCard.tsx`: amber AT RISK pill and a reason line using design-system tokens. Update the API types.
- [x] 5.4 Tests: reproduce the 2026-09-23 case (8 kW cap, 3 kW water heater forced on, 4.14 kW minimum, 0.6 kWh by 18:30) → `grid_limit`. Also cover `deadline_too_close`, `cost_tradeoff`, the stale guard, and the card render.

## 6. Solver time limit

- [x] 6.1 Add `solver_time_limit_s` to `KeplerConfig`. The adapter reads `kepler.solver_time_limit_s` (default 60, range 10–600). Pass it to CBC/GLPK and replace the literal 30 in the timeout branch.
- [x] 6.2 Detect time-limit hits (duration ≥ limit − 0.5 s): log a WARNING and set `time_limit_hit` on the result and in schedule meta.
- [x] 6.3 `config.default.yaml` + config migration: add `kepler.solver_time_limit_s: 60`. Add a settings UI field and help text.
- [x] 6.4 Tests: config plumbing, validation range, time-limit flag.

## 7. Verification

- [x] 7.1 Run `./scripts/lint.sh` (all checks) and the full test suite.
- [x] 7.2 Setpoint idempotency reads live HA state: the engine always calls the dispatcher (which skips when HA already holds the target) instead of gating on the in-memory `current_setpoint_a`, so external amps changes are corrected every tick. Tests: unchanged setpoint re-checked against HA, external amps change corrected.

Post-deployment (not part of this change's completion): on production, confirm in the Executor history (EV filter) that the go-e receives `charge`/`dont_charge` and that no 0 A writes occur.
