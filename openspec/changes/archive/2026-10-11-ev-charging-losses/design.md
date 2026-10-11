## Context

Kepler counts every wallbox kWh as energy delivered to the car (`planner/solver/kepler.py:679`, `delivered_terms`). The only EV cost is the grid import itself; there is no notion of charging overhead or start losses. Investigation on the maintainer's install (24 Sep – 10 Oct 2026, TeslaMate vs `sensor.go_echarger_417263_eto`):

- ~95% wall→car on normal days, 62–70% on days dominated by 1-phase relief; 58% for 1-phase ~2 kW sessions vs 90% for 2-phase ~6–7 kW sessions.
- Session fit: ~0.28 kW fixed overhead while charging + ~0.15 kWh per start. A proportional (heat) term could not be separated reliably from the noisy data.
- Tesla's `charge_energy_added` is itself an estimate; some days exceed 100%.
- The 1-phase sessions are load-balancer relief (`executor/load_balancer.py` `_degrade_at_floor` and `_refit_paused`), not planner choices.

Existing building blocks: per-slot wallbox energy in `ev_charger_observations` (written by `backend/recorder.py` → `LearningStore._replace_ev_charger_observations`), the Reflex mechanism that writes learned values into `config.yaml` with daily rate limits (`backend/learning/reflex.py`), the config defaults merge for array entries (`backend/config_migration.py merge_arrays`), and `executor/goal_risk.py pause_puts_goal_at_risk`, which today is only evaluated after a pause, for notifications.

## Goals / Non-Goals

**Goals:**
- The planner sees the real cost of slow and on/off EV charging and prefers fewer, higher-power sessions.
- Three per-charger loss parameters (overhead kW, start loss kWh, efficiency) exist as EV-tab settings with sensible defaults and are learned automatically.
- The load balancer avoids inefficient 1-phase relief when pausing is safe for the goal.

**Non-Goals:**
- House battery / inverter loss modelling (investigated: near-linear, already covered by the constant efficiency).
- Non-linear (I²) loss models or ML models inside the MILP.
- Per-phase load awareness in the planner (separate backlog item).
- Changing how phase modes are planned for normal (non-relief) charging.

## Decisions

### D1. Linear three-term loss model
Car energy per slot = `efficiency × wall_kwh − overhead_kw × h × on[t] − start_loss_kwh × start[t]`. All terms are linear in existing variables, so the MILP stays linear.
Alternatives: a piecewise efficiency curve (no evidence of curvature; adds variables) or LightGBM (cannot be embedded in the MILP).

### D2. Kepler integration
- `delivered_terms` (goal constraint) uses the loss-adjusted energy. Grid import and the energy balance keep the full wall energy (`kepler.py:451-452, 498`), so losses cost money and still need to be covered.
- Start indicator: a new continuous `ev_start[d][t] ∈ [0,1]` with `ev_start[t] ≥ on[t] − on[t−1]`. It is debited only through the goal (start loss) and as a cost `start_loss_kwh × import price[t]`, so the solver minimises it naturally.
- `on[t−1]` for t=0 comes from a new `EVChargerInput.charging_now: bool` field. The adapter fills it from the charger's measured power, above a small threshold.
- `on[t]` is `ev_charge[d][t]` for scheduled charging. Surplus charging (`ev_surplus_kw`, mutually exclusive with `ev_charge`) gets a new binary `ev_surplus_on[d][t]` with `ev_surplus_kw ≤ max_kw × ev_surplus_on`. The overhead and start loss apply to `on = ev_charge + ev_surplus_on`, so surplus charging pays the overhead too.
- The deadline, min/max power and grid-only rules are unchanged.

### D3. Required-energy fallback and progress use car-side energy
- When SoC is unavailable, `_calculate_required_kwh` subtracts delivered energy (`_ev_delivered_today_kwh`). It will use recorded car energy where present, else `wall × efficiency`.
- Goal diagnostics and progress use the same rule. This prevents over-crediting the goal.

### D4. Car-side energy recording
- New nullable column `car_energy_kwh` on `ev_charger_observations` (alembic migration on top of head `d2a6f1c8e4b7`, applied automatically at startup like existing migrations).
- Source per slot:
  1. Optional per-charger `energy_added_sensor`. Delta over the slot; a drop (session reset) means the new value counts from zero.
  2. Fallback: `ΔSoC% / 100 × battery_capacity_kwh` when SoC was fresh at both slot ends.
  3. Otherwise NULL.
- `car_energy_source` (`sensor` | `soc`) is stored alongside, so learning can weight or filter the sources.

### D5. Automatic learning via Reflex
A new Reflex analyser runs daily per charger:
- **Data:** slots from the last 30 days with wall energy > 0 and non-NULL car energy, aggregated per charging day. Use SoC-sourced data only when no sensor data exists.
- **Clean-up:** discard days with car/wall > 1.02 or < 0.3.
- **Fit:** least squares of `car_kwh = eff × wall − overhead × hours_on − start_loss × starts`, with `hours_on` and `starts` derived from consecutive charging slots.
- **Minimum data:** at least 8 clean charging days and 20 starts; otherwise no update.
- **Bounds:** overhead 0–1.0 kW, start loss 0–0.5 kWh, efficiency 0.80–1.00.
- **Writing:** the existing Reflex daily max-change and `learning.reflex_enabled` gate apply. Values are written into the charger entry in `config.yaml`, so the EV tab shows the learned numbers.
- Alternatives: a separate learned-params table (it would hide values from the settings UI and duplicate Reflex), or session-level matching (too noisy given 10-minute car updates).

### D6. Config and UI
New per-charger keys with defaults in `config.default.yaml` (`merge_arrays` fills them for existing users):
- `charge_overhead_kw: 0.25`
- `start_loss_kwh: 0.15`
- `charge_efficiency: 0.95`
- `energy_added_sensor: ""`

They are validated in `backend/api/routers/config.py` (overhead 0–2, start loss 0–1, efficiency 0.5–1.0) and edited in `EntityArrayEditor.tsx` (three NumberInputs with tooltips plus an EntitySelect).

### D7. Pause instead of 1-phase relief when the goal is on track (except in surplus slots)
- `_run_load_balancer` evaluates `_pause_goal_risk` per charger before the tick and passes `goal_at_risk` on `EVBalancerInput`.
- It also passes `surplus_slot` = the current plan slot's `ev_surplus_kw` for that charger > 0 (the plan flag, not live grid export, which shifts as the car draws; unreadable → False).
- `_degrade_at_floor` and `_refit_paused` offer 1-phase only when `relief_available and (goal_at_risk or surplus_slot)`; otherwise they pause. In a surplus slot, pausing exports the power at a loss, so ~60% efficient 1-phase still beats it. Cheap-grid or manual charging with the goal on track still pauses.
- Evaluation keeps failing open (at risk → relief allowed), so a broken goal lookup never leaves the car paused when it shouldn't be.
- A charger with no active goal counts as not at risk and is paused; the pause triggers the existing balancer replan.

## Risks / Trade-offs

- [Tesla energy_added is an estimate] → day-level aggregation, ratio filter and Reflex rate limits; defaults stay until enough clean data exists.
- [SoC-delta fallback is coarse (1% ≈ 0.6–0.8 kWh) and depends on the configured capacity] → used only without a sensor; capacity error mostly lands in the efficiency term, which is bounded.
- [Pausing delays energy] → only when the goal is on track; the replan moves the energy, and an at-risk goal still gets 1-phase relief.
- [Extra binaries for surplus on/off increase solve time] → one binary per charger per slot only while surplus routing is enabled; check against the existing solve-time limits in tests.
- [Learning writes to config.yaml] → same mechanism and safeguards as existing Reflex parameters.

## Migration Plan

- Alembic migration adds the nullable column; no backfill. Learning starts accumulating from deploy.
- New config keys arrive via the defaults merge; existing behaviour changes immediately with default losses.
- Rollback: revert the code. The extra column and keys are harmless to older versions (the column is nullable and unknown keys are ignored).

## Open Questions

None. Defaults and scope were decided with the maintainer on 2026-10-11.
