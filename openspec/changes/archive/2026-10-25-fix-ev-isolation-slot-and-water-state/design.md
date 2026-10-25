## Context

EV source isolation (`executor/engine.py`, isolation block in `_tick_unlocked`) triggers on `scheduled_ev_charging` (planned kW, keep-on, or an active manual charge in `self._ev_manual_charge`), `actual_ev_charging` or `surplus_eligible`. When it fires the engine replaces `slot` with a hand-built `SlotPlan` (`executor/engine.py`, `slot = SlotPlan(...)` in the isolation block) and passes it to `make_decision` (`make_decision` call right after the block). `SlotPlan` (`executor/override.py:108+`) has grown fields since that code was written; the rebuild was never updated.

`original_slot` is kept for other consumers, which is why only the water path (read from the rebuilt slot) breaks.

## Goals / Non-Goals

**Goals:** isolation changes only discharge; water heaters follow their plan in every isolation case; the battery never discharges while the car charges; no fake temperature in the execution record.

**Non-Goals:** isolation trigger changes, tank temperature sensor for switch heaters, other `SystemState` defaults, inverter profile changes.

## Decisions

### D1: `dataclasses.replace` instead of manual rebuild
`replace(slot, discharge_kw=0.0, discharge_blocked_by_ev=True)` preserves every field, including future ones. A generic test over `dataclasses.fields(SlotPlan)` guards it. Alternative (add the missing fields to the manual rebuild) rejected: it breaks again on the next field.

### D2: Controller idles on `discharge_blocked_by_ev`
`ev_isolating` at the `ev_isolating` assignment in `Controller._follow_plan` becomes `slot.discharge_kw == 0 and (slot.ev_charging_kw > 0.1 or any(slot.ev_keep_on.values()) or slot.discharge_blocked_by_ev)`. The flag is set only by engine isolation, so it is the explicit signal for "isolation active" across all triggers. The `ev_isolating` branch sits before the hold branch  and takes precedence over the hold margin as today; export, charge and grid-charge branches still come first, so planned charging is unaffected. The later `elif live_soc <= slot.soc_target` branch  becomes unreachable for flagged slots; it keeps its comment-level meaning for discharge slots at their floor, so it stays.

Idle behavior per inverter is defined by `profiles/*.yaml` and is not changed.

### D3: `current_water_temp` is `float | None`, default `None`
Nothing reads it for decisions; the only consumer is `before_water_temp` (`executor/engine.py:3181`), already `float | None` in `executor/history.py:54` with a nullable column. `None` means "no reading": switch heaters (never read) and failed reads. Any other reader found at implementation time via grep of `current_water_temp` must handle `None`; at the time of writing there is none besides the recording line and tests.

### D4: Before-state for switch heaters comes from `action_results`
The execution record has no dedicated switch before-state column, but each `water_switch` action result carries `previous_value` ("on"/"off") and `entity_id` (`executor/actions.py:1016-1060`; serialized at `executor/engine.py:3190-3200`; frontend type `ActionResult` at `Executor.tsx:135`). No backend or schema change: the UI derives the display.

Rule in the "Water Temp" cell: if `before_water_temp` is a number, show `N°C`; else if `action_results` has a `water_switch` entry, show the first one's `previous_value` as On/Off (the first heater is the one `current_water_temp` refers to); else show "—" with no unit. A `previous_value` other than on/off (for example "unavailable") shows "—". The label stays "Water Temp" for temperature heaters and becomes "Water Heater" when showing switch state. UI follows `docs/design-system/AI_GUIDELINES.md` (existing tokens/classes only; no new colors).

Edge: mixed setup with a failed temperature read on a first temperature heater and a second switch heater would show the switch state. Accepted: rare, display only.

### D5: Composition with the min-SoC discharge guard
Commit c4033cca (executor-min-soc-discharge-guard) adds a latched guard in `_follow_plan` after the mode intent is chosen: it rewrites only `self_consumption` and `export` to `idle`. An isolated slot already selects `idle` (the `ev_isolating` branch), so the guard never changes it and the isolation reason stays; the guard latch is still updated every tick, so it keeps tracking SoC across isolated slots. Branches ordered before `ev_isolating` (export, grid charge, solar charge) keep their intent and remain subject to the guard exactly as before. No change to the guard is needed.

## Risks / Trade-offs

- Water heaters now stay on during isolation while the EV charges: intended, and the planner already accounted for both loads. The load balancer's shed logic is unaffected (it overrides at `executor/engine.py:2118-2121`).
- Idling for surplus-only and actual-only isolation changes inverter behavior for those cases from self-consumption to idle. This is the stated requirement (battery must not feed the EV).
- Old records with a stored 50.0 stay as recorded; no backfill.
