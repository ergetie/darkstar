# Proposal: EV Fractional Planning and Quota Floor

## Why

A real, active EV goal (2.6 kWh, deadline next day) produced **zero scheduled charging** across a 32-hour horizon with `status: Optimal` and no warning. Two compounding defects: (1) the Kepler solver models every EV charger as a binary full-power-or-off decision per 15-min slot, so the smallest schedulable unit is `max_power_kw × 0.25h` (2.425 kWh for an 11 kW charger) — even for `type: current` chargers that can modulate 6–16 A continuously; (2) the multi-day quota spreader splits goals purely by price with no awareness of that minimum unit, so it can allocate every day a slice smaller than one unit (`{today: 0.88, tomorrow: 1.72}`), and the per-day hard cap in the solver then makes charging infeasible on every day. The whole goal silently converts to shortfall penalty.

## What Changes

- **Fractional EV planning for `type: current` chargers**: the Kepler solver plans a continuous charging power in `[min_power_kw, max_power_kw]` when the charger is on (semi-continuous: on ⇒ at least the configured minimum amps, off ⇒ 0). `type: binary` chargers keep the existing full-power-or-off model. No new config — `min_power_kw` derives from the existing per-charger `min_current_a` and phase configuration.
- **Chunk-aware multi-day quota**: each day's allocation is either 0 or at least one minimum schedulable slot's energy (`min chunk` = min plannable power × slot duration, which differs by charger control type); sub-chunk remainders are redistributed. When a goal is smaller than one chunk, the planner still schedules one minimum-power slot (bounded overshoot beats silent failure — the car stops at 100% anyway).
- **No more silent zero-outs**: when quota/feasibility interactions still prevent scheduling any of an active goal, a clear warning is logged.
- Schedule output, executor amp conversion, source isolation, surplus charging, and charts all continue to work — the executor already converts arbitrary planned kW to amps (`planned_kw_to_amps`); the planner-side minimum bound is set with a small margin so the executor's floor-rounding never lands below `min_current_a`.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `per-device-ev-scheduling`: the "Per-device MILP decision variables" requirement changes — `ev_charge[d][t]` is no longer unconditionally binary; `type: current` chargers get a semi-continuous power model with a minimum-power floor derived from `min_current_a` × phases.
- `multi-day-deferral-controller`: new requirement — daily quotas must respect the minimum schedulable energy unit per day (0 or ≥ one chunk), with redistribution and a single-chunk floor for sub-chunk goals.

## Impact

- `planner/solver/kepler.py` — EV decision variables, energy linking, source-isolation/`any_ev_charging` constraints, per-day quota constraint.
- `planner/solver/types.py` — `EVChargerInput` gains a minimum-power field.
- `planner/solver/adapter.py` — compute min power from `min_current_a` + phases config.
- `planner/strategy/multi_day_planner.py` + `planner/pipeline.py` — chunk-aware quota allocation and warning.
- Tests: solver EV tests, multi-day planner tests, pipeline quota tests; regression test reproducing the observed 2.6 kWh zero-out.
- No config schema changes, no API changes, no frontend changes (fractional kW values already render).
