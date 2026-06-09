## Context

The executor transmits the plan to the inverter every tick with no independent sanity layer. The stabilization review confirmed three defensive gaps (findings #22, #23, #35). OQ6 (the architecture decision behind this change) was settled with the operator: **battery-SoC and grid-export safety stay delegated to the planner + inverter BMS** — no execution-time clamp on either. What this change adds is the narrow, non-controversial protection that delegation does *not* cover: honoring explicit user intent (manual override, stop button) and refusing to act on a dead planner's stale plan.

Current relevant behavior:
- **Pause** already does the right thing: `pause()` short-circuits the whole tick (`engine.py:1045-1056`), so nothing is written while paused.
- **Manual override** (`OverrideType.MANUAL_OVERRIDE`, `override.py:136-143`) returns `override_needed=True, actions={}` with reason "executor will not change settings" — but `_apply_override` still runs and leaves `mode_intent="idle"`, so the executor writes a full idle profile every tick (`engine.py:1415`). The promise is violated.
- **EV control** (`_control_ev_charger`, `engine.py:1922-2036`) reads only `slot.ev_charger_plans`; it never inspects override or quick-action state, so it keeps charging during manual override / `force_stop`.
- **`min_soc_floor`** is stored on `OverrideEvaluator` (`override.py:122`) and passed in from `engine.py:1207`, but is never read in `evaluate()` — dead plumbing left from the removed Emergency Charge feature.
- **Schedule freshness** is unchecked: `_load_current_slot` (`engine.py:1536-1597`) loads whatever schedule covers `now`, even if the planner died and the plan is hours old (stale prices).

## Goals / Non-Goals

**Goals:**
- Manual override truly leaves the inverter alone (no writes), mirroring pause.
- EV charging obeys manual override and the `force_stop` quick action.
- A stale schedule triggers a warning + safe hold instead of silent execution.
- Remove the dead `min_soc_floor` plumbing so the code matches the delegation design.

**Non-Goals:**
- **No execution-time battery-SoC clamp** — the planner + BMS own deep-discharge protection (OQ6). The existing "Override evaluator does not evaluate low SoC export prevention" behavior is preserved.
- **No execution-time export/grid clamp** — the planner owns export limits (OQ6). Finding #34 (planner-side PV-to-AC cap) is out of scope here.
- No change to the pause mechanism (it already works).

## Decisions

### D1 — Manual override gets an early-return guard, like pause
Add a manual-override short-circuit so that when `state.manual_override_active` is true, the tick performs **no inverter writes** (battery mode, EV switch, water) — the same hands-off contract pause provides. Telemetry/state recording (history, slot observations) still runs so the UI reflects reality.
- **Why over the alternative** (keep routing through `_apply_override` but blank every action): blanking actions is fragile — every new action type must remember to opt out. A single guard at the same layer pause uses is the smallest, safest surface and matches the existing, trusted pattern.

### D2 — EV control consults override + quick-action state
Gate `_control_ev_charger` on the same state the battery decision already sees: under `MANUAL_OVERRIDE` skip EV writes entirely (hands-off); under `force_stop` command the charger **off**. Otherwise behave as today (follow `ev_charger_plans`).
- **Why:** the battery path already handles `force_stop` (sets `soc_target=10`); the EV switch was simply missed. This makes the stop button and manual override consistent across both controllable loads.

### D3 — Schedule-freshness check → warn + hold
When loading the current slot, compare the schedule's `generated_at` to `now`. If older than a configured threshold, do not execute it: emit a warning via the existing `record_forecast_error` / `SystemAlert` path and fall back to the **slot-failure hold** behavior already defined in `override.py:145-160` (`grid_charging=False`, `soc_target=current SoC`). Reuse the existing fallback rather than inventing a new one.
- **New config:** `executor.max_schedule_age_hours` (optional, default **6**). Rationale: the planner replans well within an hour in normal operation, so a 6-hour-old schedule means several missed cycles — a strong signal the planner is down — while staying clear of normal jitter. Configurable so operators can tighten/loosen it.
- **Why hold, not last-known-good math:** holding is the already-tested safe state; re-deriving a "best guess" plan at execution time would re-introduce planning logic into the executor, which the delegation design explicitly avoids.

### D4 — Delete `min_soc_floor` plumbing outright
Remove the parameter from `OverrideEvaluator.__init__`, `evaluate_overrides`, and the `engine.py` call site. It is never read, so removal is behavior-preserving and eliminates the misleading "there is a safety floor here" signal.
- **Why over wiring it into a clamp:** OQ6 decided against an execution-time SoC clamp; leaving the parameter implies a guard that does not (and by decision will not) exist.

## Risks / Trade-offs

- **Manual-override skip could hide a genuinely needed action** → Mitigation: this is the explicit, user-requested "hands off" contract (same as pause); if the user wants Darkstar in control, they turn the entity off. Documented behavior.
- **Freshness threshold too tight → unnecessary holds; too loose → stale plan slips through** → Mitigation: conservative default (6h) plus a config knob; a hold is SoC-safe (it preserves current SoC) and always accompanied by a visible alert, so a false hold is recoverable and never silent.
- **`force_stop` turning the EV charger off may surprise a user mid-charge** → Mitigation: that is the literal intent of a stop action; the battery already behaves this way, so this removes an inconsistency rather than adding a surprise.
- **Removing `min_soc_floor` touches a public-ish constructor signature** → Mitigation: it is internal to the executor package and unused; grep confirms no read. No migration needed.

## Migration Plan

No data/schema migration. `executor.max_schedule_age_hours` is optional with a default, so existing configs keep working. Rollback = revert the change; the removed `min_soc_floor` had no effect, so reverting is safe either way.

## Open Questions

- Confirm the exact `generated_at` field/timestamp available on the loaded schedule object during implementation (finding #35 references it; verify the precise accessor in `_load_current_slot`).
- Default `max_schedule_age_hours = 6` is a starting value; tune once the planner's normal replan cadence is confirmed.
