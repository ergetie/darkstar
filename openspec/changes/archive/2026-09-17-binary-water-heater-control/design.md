## Context

The water heater control path is temperature-only end to end. The planner decides per-device heating in kW, the controller converts that to a per-device target temperature (`ControllerDecision.water_temps`), and the executor writes that temperature with `ActionDispatcher.set_water_temp`, which calls `HAClient.set_input_number`. That writer's domain guard (`_get_safe_domain(entity_id, {"number", "input_number"})`) rejects anything else, so a relay-driven tank (`switch.vvb`) cannot be controlled.

`water_heaters[].type` looks like it might already express this, and it does not. It accepts `"binary"` and `"modulating"` (`WATER_HEATER_LOAD_TYPES` in `backend/loads/base.py:16`), it describes the *load model* consumed by `backend/loads/service.py:68`, and it **defaults to `"binary"`**. Every existing heater is therefore already `type: "binary"` while being temperature-controlled — the current production config pairs `type: binary` with `target_entity: input_number.vvbtemp`. Reading `type` as a control type would reclassify every deployed heater as switch-driven and fail validation on configs that work today.

`WaterHeaterDeviceConfig` (`executor/config.py:116`) carries only `id`, `name`, `target_entity`, `power_kw`, so nothing about control reaches the executor beyond the entity id. Config save only warns about a malformed *power sensor* and never checks that `target_entity` is a domain the executor can actually write, so a switch entity saves cleanly and then silently does nothing forever.

The on/off writer already exists: `ActionDispatcher.set_balanced_entity` writes on/off to arbitrary `switch.` / `input_boolean.` entities, and is used today for excess-PV custom-entity sinks and load-balancing custom-entity loads.

Two adjacent facts constrain the design:

- **Manual boost is broken for multi-device setups, and is repaired here.** Boost predates multi-device water heaters and was never updated. `EnergyExecutor.set_water_boost` calls `dispatcher.set_water_temp(temp_boost)` with no target entity, which falls back to the legacy single-heater `config.water_heater.target_entity`. The engine holds one global `_water_boost_until` rather than per-heater state. During the boost window the override path builds a `ControllerDecision` with only the scalar `water_temp` set and `water_temps` empty (`executor/controller.py:152`), so the per-device loop at `executor/engine.py:1579` is skipped and execution falls to the same legacy entity. On an entity-array config that entity is normally unset, so **boost writes nothing at all** — for temperature heaters as much as binary ones. `WaterBoostRequest` (`backend/api/routers/water.py:33`) carries only `duration_minutes`, so there is no way to say which heater to boost either. Fixing this is in scope: binary boost is otherwise untestable end to end, and the existing behavior is dead code on any current config.
- **The load balancer sheds water heaters by forcing `temp_off`** (`executor/engine.py:1587`). Whatever translation binary control uses must make shed mean OFF without a second code path.

## Goals / Non-Goals

**Goals:**

- A water heater whose HA entity is a switch can be scheduled, executed, and shed exactly like a temperature-controlled one.
- The heater's control type reaches the executor and drives which write path is used.
- Misconfiguration is caught at config-save time with a clear error instead of at runtime with silence.
- Manual boost actually reaches the heater, targets a heater the user chooses, and works for both control types.
- Existing temperature-controlled heaters are untouched in their scheduled behavior, including configs that never set `type`.

**Non-Goals:**

- Changing the planner or the MILP. Planning stays in temperatures and kW; binary control is purely an executor-side translation.
- Scheduled boost (`water_heating_boost` from the plan). That path already works per-device; only *manual* boost is repaired here.
- `type: "modulating"` water heaters. The value is accepted by validation today but has no distinct execution path; this change does not add one.
- Inferring the control type from the entity's domain. The type is declared, and validation checks the entity against it.

## Decisions

### Translate temperature to ON/OFF in the executor, at the write boundary

The planner and controller keep producing temperatures for every heater regardless of type. The executor's per-device loop translates for binary heaters: **ON when the resolved temperature is strictly greater than `temp_off`, OFF otherwise.**

*Why:* it keeps one scheduling model, so per-device daily minimums, spacing, block duration and gap-comfort penalties all keep working untouched for binary heaters. It also makes load-balancer shedding work for free, since shed already resolves to `temp_off`, which translates to OFF. The alternative — a parallel binary decision path through the controller — would fork the planner contract and duplicate every per-device constraint.

*Consequence to accept:* `temp_normal` and `temp_boost` become meaningless numbers for a binary heater. The settings UI should not offer them for that heater, and the requirement text should say the values are not written anywhere.

### A new `control_type` field, not the existing `type`

Control type is a **new** `water_heaters[].control_type` field with values `"temperature"` (the default) and `"switch"`. The existing `type` field keeps meaning the load model and is not read as a control type anywhere.

*Why:* `type` defaults to `"binary"`, so every deployed heater already carries that value while being temperature-controlled (see Context). Overloading it would reclassify every existing heater as switch-driven, break their control the moment the executor branched on it, and fail validation on configs that work today. The two concepts are genuinely different — a heater can be an on/off *load* while being commanded by a temperature setpoint, which is exactly the common case.

*Naming:* `"temperature"` / `"switch"` rather than reusing the word `binary`, so the two fields cannot be confused in config, code review, or a bug report. The capability keeps the name `binary-water-heater-control` because that is what users call it.

*Alternative considered:* deriving the control type from the `target_entity` domain and storing nothing. Tempting — the domain is unambiguous — but it makes an invalid config unrepresentable rather than detectable, so a typo'd entity silently changes control mode instead of producing an error. Declared-and-validated beats inferred here.

### Carry the control type on `WaterHeaterDeviceConfig`, reusing `target_entity`

Add `control_type` to `WaterHeaterDeviceConfig` and populate it in the loader from the same `water_heaters[]` entry that already supplies `power_kw`. The control entity stays `target_entity` for both control types rather than adding a separate `switch_entity`.

*Why:* one heater has one control entity; a second field invites configs where both are set and neither is obviously authoritative. EV chargers use `switch_entity` because they genuinely have a switch *and* a separate current setpoint; a water heater does not.

### Reuse the shared on/off write, under a distinct `water_switch` action type

Binary heaters dispatch through the same on/off write that `set_balanced_entity` uses — it already handles idempotent skip, shadow mode, domain-safe writes, and returns an `ActionResult` — but the result carries a distinct `action_type` of `water_switch`.

*Why the shared write:* the alternative is a near-copy of ~50 lines.

*Why a distinct action type:* history and the executor UI key off `action_type`. Reusing `water_temp` for a value that is `on`/`off` would make the field name lie about its contents, and reusing `balanced_load_entity` would make a water heater indistinguishable from a load-balancer custom entity in the execution record. Since `set_balanced_entity`'s `action_type` is currently fixed, the implementation either parameterizes it or adds a thin `set_water_switch` wrapper delegating to the shared write — never a duplicated body.

*Consequence to accept:* any consumer that filters execution history on `action_type == "water_temp"` stops seeing binary heaters. The frontend history and executor views must be updated to include `water_switch` wherever they treat `water_temp` as "water heating", and this is an explicit implementation task rather than something to discover later.

### Manual boost becomes per-heater, and resolves to ON for a binary heater

Boost stops being a single global flag. The engine tracks a boost deadline **per heater id**, the boost API takes the heater(s) to boost, and the override populates `ControllerDecision.water_temps` per boosted heater so the existing per-device loop dispatches it — which means boost automatically inherits the binary translation rule and needs no separate binary path. For a binary heater, boost resolves to ON for the boost duration, and no boost temperature is offered in the UI.

*Why per-heater state rather than a global flag plus a heater id:* a global deadline cannot express "boost the upstairs tank" while the main tank follows its schedule, and a user with two tanks will hit that immediately. Per-heater state also makes clear-on-expiry per heater fall out naturally.

*Why route boost through `water_temps` rather than a separate boost dispatch:* it reuses the one place that already knows how to control every heater of every type, including the binary translation and the load-balancer shed interaction. A separate dispatch would be a second code path to keep in sync.

*Default when the caller names no heater:* boost every enabled heater with a control entity. That keeps single-heater setups — the common case, and the only case that ever worked — a one-click action with no selection step, and preserves the current API shape for existing callers.

*Precedence:* the existing battery-SoC protection is unchanged and still cancels boost, and load-balancer shed still wins over boost, since shed resolves the heater to `temp_off` after the boost target is applied. Worth asserting in tests so a future reader does not have to infer it.

### Validation of the control entity becomes a blocking error, not a warning

At config save, a heater with temperature control requires a `number.` / `input_number.` `target_entity`; a binary heater requires `switch.` / `input_boolean.`. A mismatch is `severity: "error"`.

*Why:* the failure it prevents is silent and permanent — the executor's domain guard rejects the write every tick and the user sees nothing. A warning is the status quo that produced the original report. The existing *power sensor* check stays a warning, since a missing or odd power sensor degrades measurement but does not break control.

## Risks / Trade-offs

- **[Existing configs with a switch in `target_entity` start failing validation]** → Those configs are already non-functional (the write is rejected every tick), so the error surfaces an existing breakage rather than causing one. Making the fix obvious matters: the error message should name the control type that would accept the entity they already entered, so the remedy is to set `control_type: "switch"`.
- **[Two similarly-named fields, `type` and `control_type`, on the same object]** → Real confusion risk for future readers. Mitigated by the value vocabularies being disjoint (`binary`/`modulating` vs `temperature`/`switch`), by a comment at both definition sites, and by the settings UI labelling them distinctly. The alternative — renaming `type` to `load_type` — would be clearer but needs a config migration and touches the EV charger path, so it is deliberately left out of scope.
- **[`temp_normal` / `temp_boost` remain in config for binary heaters and look meaningful]** → Hide them in the settings editor for binary heaters and state in the spec that they are not written. Leaving them in the stored config is deliberate, so switching a heater back to temperature control does not lose the values.
- **[Translation rule hides a real distinction]** → `temp > temp_off` collapses "heat to normal" and "heat to boost" into the same ON. That is inherent to the hardware, not to the rule, but it means a binary heater's execution history shows less than a temperature heater's. Acceptable.
- **[Type and entity can drift out of sync via direct config.yaml edits]** → Validation runs on the save path, not on load. A hand-edited config can still reach the executor with a mismatched pair. The executor should log a clear warning and skip that heater rather than raise, matching how it already handles a heater with no `target_entity`.
- **[Reusing the shared on/off write couples two features]** → A future change to load-balancer entity writes would touch water heaters too. Mitigated by the `set_water_switch` wrapper, which the distinct `action_type` requirement likely forces anyway and which gives a natural seam.
- **[`water_switch` is invisible to existing history consumers]** → Anything filtering on `water_temp` silently stops counting binary heaters, which is the same class of silent-miss this change exists to remove. Auditing every consumer of `water_temp` and updating it is a required task, not a follow-up.
- **[Boost repair widens the change well beyond binary control]** → Accepted deliberately: boost is dead code on current configs, and binary boost cannot be verified end to end without it. The risk is a larger diff to review at once; mitigated by keeping the boost work in its own task group and its own capability spec, so it reads as a self-contained fix inside the change.
- **[Per-heater boost state changes the boost WebSocket/status payload]** → `get_water_boost_status` currently returns one global object that the dashboard and command bar consume. Moving to per-heater state changes that shape, so the frontend consumers must be updated in the same change or the boost indicator breaks.

## Migration Plan

No data migration. `control_type` is a new field defaulting to `"temperature"`, so existing configs — all of which are temperature-controlled — load and execute identically, and the existing `type` field is untouched. A boost request that names no heater boosts all of them, so existing API callers keep working. Rollback is a code revert; nothing is written to config or the database that an older build would fail to read.

## Open Questions

None outstanding. The two decisions previously open here — the execution-history action type for binary heaters, and whether to repair manual boost as part of this change — were resolved to `water_switch` and to repairing boost here, and are recorded in Decisions above.
