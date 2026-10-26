## Context

`Controller._follow_plan` handles a hold slot in the branch `elif slot.discharge_kw == 0 and not slot.discharge_blocked_by_ev` (`executor/controller.py` L287-293), the fifth of seven branches. It enters a "hold" plan-state block keyed by `(kind, soc_target)` and delegates to `_hold_mode`: `self_consumption` while SoC > `max(target - 2, min(target, min_soc))`, `idle` once at or below it, latched until SoC >= target and above the floor. `BatteryPlanState.enter` resets `latched` whenever kind or target changes.

Planner side: the plan is recomputed every 30 minutes from live SoC; every hold slot target equals the entry SoC. Executor and planner therefore disagree about a hold slot. The planner assumes zero discharge; the executor allows 2 points of discharge per target value, and each replan hands out a fresh 2 points from a lower anchor.

Existing state that interacts: the min-SoC guard latch (`_update_min_soc_guard`, `BatteryPlanState.min_soc_guard`, never reset by `enter`), the charge-target latch (`_grid_charge_or_hold`, also `BatteryPlanState.latched`), the two EV isolation branches (PV-charge branch and the `ev_isolating` branch, both idle with `EV_ISOLATION_REASON`), and the discharge-slot-at-floor branch (`live_soc <= slot.soc_target`).

Current branch order in `_follow_plan`: export (discharge to grid); grid charge; PV charge (idle with `EV_ISOLATION_REASON` while isolating, otherwise `self_consumption`); `ev_isolating` (idle, `EV_ISOLATION_REASON`); hold (this change); discharge slot at floor; default `self_consumption`. Self-consumption uses max charge unless the slot plans export (L350), so the hold change never touches that path.

## Decisions

**D1. A hold slot is always `idle`.** In the hold branch set `mode_intent = "idle"` with a hold reason note, independent of SoC, target, PV and forecasts. Hold semantics become: no battery discharge, PV may still charge, grid covers load. This is what the planner modeled, so executor behaviour equals the plan and no replan can change it. It removes the ratchet (no margin to re-arm), the drift, and the Auto/Block flapping (the mode is constant across a hold block).

**D2. Inverter profile check: idle keeps PV charging possible on every profile (universal design).** Read from `profiles/`:
- `fronius.yaml` L124-129: idle writes only `work_mode = "Block Discharging"`; note L173: "Block discharging: Only PV charging allowed". Historical data over 479 idle slots with PV > load confirms PV still charges the battery and surplus exports when full.
- `deye.yaml` L151-163: idle = Zero Export To CT, grid charging off, `max_discharge_current` 15 (comment L159: keeps the EN50549 grid profile from cutting PV at 100% SoC), `max_charge_current = {{max_charge}}` (full charge limit), soc_target written. PV charging allowed.
- `sungrow.yaml` L152-164: idle = self-consumption mode, forced command Stop, `max_discharge_power` 10, `max_charge_power = {{max_charge}}`; description "Allow PV charge".
- `generic.yaml` L145-155 and `schema.yaml` L124-134 templates: no charge-limiting write in idle; `max_discharge` 0, `work_mode` is user-configured (generic is `CONFIGURE_ME`).
No profile writes a zero charge limit in idle, so no profile blocks PV charging or surplus export in idle. This also satisfies the project rule: extra PV above forecast goes into the battery, charging is never capped unless export is planned (the hold branch never caps charge; idle writes no charge cap). Known residuals, accepted and unchanged: Deye idle can discharge up to 15 A and Sungrow idle up to 10 W (same residuals already accepted for EV isolation in `ev-isolation-pv-charge-and-deye-cap`). If a user's generic `work_mode` mapping does not block discharge, that is a profile configuration matter, as it already is for every other idle use.

**D3. Remove the hold state and its helpers.** With D1 the hold branch is stateless:
- Delete `_hold_mode`.
- The hold branch calls `self.plan_state.enter(None, None)` like the other stateless branches, so a preceding charge block's latch resets when a hold slot starts. The `"hold"` kind is no longer produced; update the `kind` comment and class docstring to charge-only.
- `BatteryPlanState.latched` stays (charge-target latch uses it). `min_soc_guard` untouched.
- `SOC_TRACKING_MARGIN` stays (L34, comment L30-33 mentions hold margin); remaining users: `_grid_charge_or_hold` (charge resume) and `_update_min_soc_guard` (release). Update its comment (no longer "hold margin", no D2/D1 hold bound).
- `battery.min_soc_percent` and `ControllerConfig.min_soc_percent` stay (guard and ev paths); fix the comment in `executor/config.py` L354 that says it bounds the hold margin.
- Comments in `executor/override.py` L133 and `executor/engine.py` L1931 saying "hold margin does not apply / no hold margin" are reworded to "not a planned hold".
- Check `engine.py` L424 (`BatteryPlanState()` init), L604 (`replace(...)` copy) and L1965 for plan_state handling: the field set is unchanged, so no change expected; verify during implementation.

**D4. Reason note.** Replace `HOLD_MARGIN_REASON` (L37) with `HOLD_REASON = "hold slot, blocking battery discharge"`. It is appended on every hold tick, so the Executor page shows why idle is selected. No frontend or docs reference the old string (verified by search: only `executor/controller.py` and `tests/executor/test_battery_plan_tracking.py`).

**D5. Interactions.**
- Min-SoC guard: it only rewrites `self_consumption`/`export` to `idle`; a hold slot is already `idle`, so the guard does not alter it or its note. The latch still updates from live SoC every tick, so it keeps tracking and keeps blocking after the hold block ends (existing scenario preserved).
- EV isolation: branch order unchanged. Both isolation paths (the PV-charge branch and the `ev_isolating` branch) precede the hold branch and keep `EV_ISOLATION_REASON`. `discharge_blocked_by_ev` slots still skip the hold branch and idle through the isolation branch.
- Discharge slot at floor (`live_soc <= soc_target`) and the export, grid-charge and PV-charge branches: untouched. The hold branch is reached only when none of those apply.
- Charge values: for an `idle` decision the existing code path still computes `charge_value`; profiles do not use it in idle (Deye and Sungrow write `max_charge`), so nothing changes there. The min-SoC "max charge" override applies only to `self_consumption`.
- Deviation replan (`soc_deviation_replan_percent`): previously the 2-point margin was sized so it never triggered a deviation replan alone. With idle holds, SoC can only rise or stay (modulo the residuals above), so deviation shrinks. No change.

**Alternatives considered**
- *Keep the margin, anchor it to the block's original entry SoC across replans.* Needs the executor to know the plan's block origin, which the plan does not carry across replans; adds state and still lets 2 points drain per hold block. Rejected.
- *Hysteresis on the target (ignore target drops of 1-2 points between plans).* Treats the symptom; still allows drift and flapping inside a plan. Rejected.
- *Gate Auto vs Block on PV forecast or on measured PV vs load.* The forecast was 2.5x under actual; a measured-PV gate flaps on cloud and still contradicts the planner's model. Rejected; the fix is forecast-independent.
- *Planner models the drift.* Makes the plan depend on an executor tolerance and still does not stop flapping. Rejected; belongs to the planner, outside this fix.
- *Keep the margin but widen the target in the planner.* Changes planner output semantics for all consumers. Rejected.

## Risks / Trade-offs

- A hold slot with a PV shortfall now imports from the grid for the shortfall instead of drawing the first 2 points from the battery. This is what the planner priced and is the intended hold meaning. It reverses the earlier wish (archived `battery-soc-plan-tracking` D2) to use the battery at an expensive price within a hold; accepted because that margin compounds across replans.
- Hold slots with high SoC and PV below load (evening) import from the grid by design; the planner's hold reasons (price reserve) already account for this.
- Deye 15 A and Sungrow 10 W idle residuals mean those inverters may still discharge slightly in a hold; unchanged and out of scope.

## Open Questions

- Whether to keep a configurable allowance for small battery use in holds: recommended no (universal, no knob); revisit only on user request.
