## Context

`executor/engine.py` ~1751-1775: when `water_boost.active` and `state.current_soc_percent < min_soc + 10`, the executor clears `_water_boost_until`, warns and notifies, returning no override. Otherwise it returns FORCE_HEAT (priority 8) with `soc_target = max(int(SoC - 10), int(min_soc + 10))` (engine.py ~1778-1785).

The override goes through `Controller._apply_override` (`executor/controller.py` ~158-232): `mode_intent = "idle"` (default; only `force_charge` changes it), `charge_value = discharge_value = 0.0`, `write_charge/discharge = False`, `soc_target = int(actions.get("soc_target", 10))`. Nothing in this path discharges the battery, so the guard protects nothing. Boost heating therefore comes from PV or grid, as with EV isolation.

## Goals / Non-Goals

**Goals:** boost is never blocked/cancelled by SoC; boost never discharges; `soc_target` written is always sensible.
**Non-Goals:** changing priorities, override ordering, EV logic, UI, or the min-SoC guard itself.

## Decisions

### D1: Remove the SoC branch entirely
The `else` branch (FORCE_HEAT) becomes unconditional. No `_water_boost_until.clear()`, warning or notification. The user's explicit Cancel (engine.py ~1092) remains the only way to end a boost besides expiry.

### D2: `soc_target` = current plan slot's `soc_target`

What `soc_target` does in `idle` per profile (all evidence from `profiles/`):
- Deye (`profiles/deye.yaml:151-163`): idle writes work_mode "Zero Export To CT", grid charging off, `max_discharge_current` 15, and `soc_target` -> Time-of-Use program 6 SoC (`deye.yaml:54-60`). With grid charging off it acts only as the discharge floor; a target above SoC cannot charge.
- Generic (`profiles/generic.yaml:145-155`): idle writes `soc_target`, grid charging false, `max_discharge_current` 0. Same semantics.
- Sungrow (`profiles/sungrow.yaml:152-164`): idle has no `soc_target` entity write; value unused.
- Fronius (`profiles/fronius.yaml:124-129`): idle only sets "Block Discharging"; value unused.

EV isolation passes `slot.soc_target` (the plan's value, `controller.py` ~277-283, `_follow_plan` idle branches), and hold slots likewise; `force_stop` quick action passes constant 10 (engine.py ~1736, controller.py ~150-153). So idle callers pass either the plan's floor or a fixed floor; none passes a value derived from live SoC.

Options considered:
1. Keep `max(SoC-10, min_soc+10)`: at SoC 6% writes 20, above SoC. Nonsensical; rejected.
2. Live SoC clamped at min_soc: changes every tick (extra Deye writes, noise) and still ends above SoC at low SoC.
3. `min_soc_percent`: rejected. On Deye, idle still allows up to 15 A discharge (`deye.yaml:159`), so a min_soc floor would let a long boost trickle the battery down to min_soc. Boost must be grid-fed.
4. Plan slot `soc_target` (chosen): identical to what EV isolation and hold slots write in idle (`controller.py` ~329), so boost behaves exactly like those grid-fed idle states and never drains below the plan's floor for the slot. Without a plan slot (`slot is None`), use `max(round(SoC), min_soc_percent)`: hold current charge, as the existing keep-SoC override does (`override.py:186`).

Caveat: Deye idle caps discharge at 15 A, not 0 (`deye.yaml:159`), so "blocked" is a trickle limit there; this is existing idle behavior shared with EV isolation and hold slots and is out of scope.

### D3: Interaction with the min-SoC guard
`decide()` returns `_apply_override` early (controller.py ~150-152), before `_follow_plan` and before `_update_min_soc_guard` (called at ~302 inside `_follow_plan`). So during boost the guard is neither evaluated nor applied, and the latch (`BatteryPlanState.min_soc_guard`, not reset by `enter()`, controller.py ~53-62) is frozen. This is safe because the override is already `idle`, the guard's own outcome. The latch release (min_soc+2) is evaluated on the first plan-following tick after boost ends. `_apply_override` calls `plan_state.enter(None, None)`, which only resets the charge latch. No change needed.

## Risks / Trade-offs

- A boost at 6% SoC heats from grid, costing money: intended (user decision, same as EV isolation).
- Profile where `soc_target` is user-meaningful beyond floor: only Deye/generic write it; semantics verified above.

## Migration Plan
Code-only; no config or data migration. Rollback is a revert.

## Open Questions
- None. User decision 2026-10-27: plan slot `soc_target`, not min_soc.
