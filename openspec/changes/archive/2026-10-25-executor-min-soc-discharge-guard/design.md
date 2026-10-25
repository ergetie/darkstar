# Design: executor-min-soc-discharge-guard

## Context

See proposal.md. Verified: the `elif slot.charge_kw > 0:` branch in `_follow_plan` returns `self_consumption` unconditionally. Fronius "Auto" and Sungrow have no SoC floor of their own below the inverter reserve. Deye and generic write `soc_target` in every mode. Fronius "Block Discharging" (idle) still charges from PV. `BatteryPlanState.enter()` resets per block. The main tick passes `self._battery_plan_state` itself to `make_decision`; only the status-display call (~L604) passes a copy (`replace(...)`). Precedent: `min-soc-floor-tracking` (`openspec/changes/archive/2026-10-21-min-soc-floor-tracking`).

## Goals / Non-Goals

**Goals:** executor never lets plan-following modes discharge below `min_soc_percent`, on every profile, without flapping.

**Non-Goals:** planner changes, price logic, writing Fronius `minimum_reserve` (forbidden), override paths (`_apply_override` only yields idle/charge or no actions).

## Decisions

### D1: Shared guard after mode intent is chosen
In `controller.py`, once `_follow_plan` has chosen the mode intent, a latched guard maps `self_consumption` and `export` to `idle`. `charge` and `idle` pass through. This is not profile-specific: it is a no-op in practice on Deye, where `soc_target` already floors the SoC.

### D2: Latch with a +2 release
Engage at `live_soc <= min_soc_percent`, release at `live_soc >= min_soc_percent + SOC_TRACKING_MARGIN` (existing constant, 2, not a setting). Idle still charges from PV, so release comes from PV or a planned charge. Switching is bounded to about one cycle per 2 % (about 0.4 kWh on 19.2 kWh).

### D3: State persists in BatteryPlanState
The latch is a new field on `BatteryPlanState` (`executor/controller.py`) that `enter()` does not reset. The engine already keeps one instance for its lifetime (~L424) and passes it to the main tick by reference, so the latch survives slot changes and replans without new plumbing. The status-display call already passes a copy, so it cannot mutate the latch. The latch is updated on every plan-following tick from the live SoC, whatever mode the plan chose, so an `idle` slot can still engage or release it.

### D4: Unreadable SoC
If `state.soc_available` is False (`current_soc_percent` is a 50.0 placeholder), the guard neither engages nor releases and keeps the previous latch state.

### D5: Reason text
New constant, for example `MIN_SOC_GUARD_REASON = "min SoC reached, blocking discharge"`, set as the decision note like `HOLD_MARGIN_REASON`, so it shows in logs and UI.

### D6: No price logic
Grid import while latched (up to about 2 % of capacity per cycle) is accepted. The planner owns economics. The drift tolerance from min-soc-floor-tracking stays: below min the plan holds and refills by price within 6 h, and the guard stops further decline.

## Alternatives rejected
- Hold until the plan wants a discharge: adds nothing once the +2 margin exists.
- Writing Fronius `minimum_reserve`: forbidden.
- Profile-only fix: the bug is in shared controller logic.
- Configurable margin: a setting nobody should tune; same reasoning as min-soc-floor-tracking D5.

## Risks / Trade-offs
- [Idle at min imports from the grid for house load] -> Intended, it respects the configured minimum. Bounded by the +2 release.
- [Latch stuck engaged if SoC stays unreadable] -> Safe direction: discharge stays blocked, and a charge slot still works.
- [Overrides (manual, slot failure) skip `_follow_plan`, so the latch is not updated during them] -> Accepted: overrides never discharge (idle/charge/no actions), and the latch re-evaluates on the first plan-following tick.
