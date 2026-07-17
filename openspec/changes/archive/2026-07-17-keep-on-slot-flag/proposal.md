# Proposal: keep-on-slot-flag

## Why

When `keep_on_after_target` is active, `_apply_keep_on_after_target` (planner/pipeline.py:238-293) injects fake max-power EV charging into keep-on slots (`ev_charger_results[id] = max_kw`, `ev_charge_kw = sum`) without touching `grid_import_kwh`, `cost_sek`, or the energy balance. The published schedule shows phantom charging energy with no matching import or cost — every consumer summing plan energy gets inconsistent numbers, charts show charging that isn't planned, and the executor history logs full-power intent for slots where the vehicle draws only what it needs. (Backlog item "Keep-On-After-Target Energy Not Reflected in Schedule Totals", found in the post-merge review of price-forecasting-module-4/5, 2026-07-09.)

## What Changes

- Planner: keep-on slots carry an explicit per-charger `keep_on` flag instead of fake power; `ev_charger_results`/`ev_charge_kw` stay 0 for keep-on slots. Schedule JSON gains a per-slot `ev_keep_on` field (per-charger dict). Schedule totals become energy-consistent.
- Executor: all three plan-power decision sites become flag-aware so keep-on still closes the switch / commands current — `_control_ev_charger` (engine.py:2958), `_run_load_balancer` planner-target derivation (engine.py:2637), `_run_ev_surplus_and_phase` (engine.py:2526). `SlotPlan` gains an `ev_keep_on` field parsed from the schedule (including the aggregate backward-compat fallback path).
- Executor: battery source isolation (`engine.py:1340-1377`, controller.py:202) stays active during keep-on slots (closes the pre-draw isolation gap).
- Executor history: keep-on mentioned in the tick reason text (KISS — no DB migration, per user decision 2026-07-12).
- Status API: `current_slot_plan` exposes the keep-on flag.
- Frontend: schedule chart renders a thin "EV standby" band (no kW height) for keep-on slots instead of a charging bar; Executor page badges show "🔌 EV standby" when keep-on is active with 0 planned kW.
- Tests: rewrite the 6 assertions in `tests/planner/test_keep_on_after_target.py` (currently expect fake 11.0 kW); add the missing executor-level test that the switch closes when `keep_on` is set and planned kW is 0.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `ev-target-charging`: keep-on-after-target representation changes — keep-on slots SHALL carry a distinct flag with zero planned energy, and published schedules SHALL be energy-consistent (no phantom charging power).
- `executor`: EV charging decisions (switch close, load-balancer planner target, phase-mode target) SHALL honor the keep-on flag when planned power is 0; battery source isolation SHALL remain active during keep-on slots; status API SHALL expose the flag.
- `executor-mode-display`: EV context badge SHALL distinguish keep-on standby from planned charging.
- `chart-planned-actual-display`: keep-on slots SHALL render as a standby indicator, not as planned-power bars.

## Impact

- **Planner:** `planner/pipeline.py` (`_apply_keep_on_after_target`), `planner/solver/types.py` (`KeplerResultSlot`), `planner/solver/adapter.py` (`kepler_result_to_dataframe`), `planner/output/formatter.py`, `data/schedule.json` format (additive field).
- **Executor:** `executor/engine.py` (5 sites), `executor/controller.py`, `executor/override.py` (`SlotPlan`).
- **Frontend:** `frontend/src/components/ChartCard.tsx`, `frontend/src/pages/Executor.tsx`, `frontend/src/lib/types.ts`.
- **Tests:** `tests/planner/test_keep_on_after_target.py` (rewrite), new executor keep-on test.
- **Compatibility:** additive schema — old schedules without `ev_keep_on` behave as before for solved charging; a stale pre-change schedule on disk during a rolling deploy loses keep-on for at most one planner cycle (fake power is gone but flag absent), which is acceptable and self-heals on the next plan.
- **Not touched:** HA actuation calls (`set_ev_charger_switch`'s `charging_kw` param is logging-only), learning/observation recording (reads measured `ev_charging_kwh`, a different field), execution_log DB schema.
