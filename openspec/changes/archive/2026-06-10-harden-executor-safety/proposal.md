## Why

The executor follows the plan verbatim and has three confirmed defensive gaps surfaced by the stabilization review (findings #22, #23, #35): an optional "manual override" still writes inverter settings (the opposite of its promise), EV charging ignores manual override and the stop button, and a crashed planner's stale plan is followed silently with no freshness check. None threaten the battery (the BMS is the hardware backstop), but each lets the executor do the wrong thing when the user or the upstream plan says otherwise.

## What Changes

- **Manual override stops touching the inverter (#22).** When the configured `manual_override_entity` is `on`, the executor skips all inverter writes for that tick — same early-return behavior the pause button already has — instead of pushing a full idle-mode profile that overwrites the user's manual settings.
- **EV charging respects manual control (#23).** EV charger switching now honors manual override and the `force_stop` quick action: under either, a plan-scheduled EV charge is stopped rather than continuing.
- **Stale-plan freshness check (#35).** Before acting, the executor checks how old the loaded schedule is; if it is older than a configured threshold it warns (via the existing alert path) and falls back to the safe "hold" behavior instead of executing a stale plan on stale prices.
- **Remove dead `min_soc_floor` plumbing (#35).** The unused `min_soc_floor` parameter is deleted. Per the OQ6 decision, battery-level safety stays delegated to the planner + inverter BMS — no execution-time SoC clamp is added. **BREAKING:** none (the parameter is currently never read).
- **Out of scope:** no execution-time battery-SoC clamp and no execution-time export clamp — the planner owns both (OQ6 decision). Finding #34 (planner-side PV-to-AC export cap) is deferred to planner work, not this change.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `executor`: manual override must not write inverter settings; EV charger control must obey manual override and `force_stop`; the executor must reject a stale schedule and fall back to hold; the dead `min_soc_floor` safety-floor plumbing is removed (battery-SoC safety remains delegated to planner + BMS).

## Impact

- **Code:** `executor/override.py` (manual-override handling, remove `min_soc_floor`), `executor/engine.py` (EV control gating on override/quick-action, schedule-freshness check + hold fallback, drop `min_soc_floor` wiring), `executor/controller.py` (manual-override no-write path).
- **Config:** new optional setting for the schedule-freshness threshold (hours); existing `executor.manual_override_entity` behavior changes.
- **Behavior:** users with a `manual_override_entity` configured regain true hands-off control; EV charging is stoppable via override/stop; a dead planner no longer silently runs a stale plan.
- **No schema/migration changes; no dependency changes.**
