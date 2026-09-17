## 1. Carry the control type into the executor

- [ ] 1.1 Add a control-type field to `WaterHeaterDeviceConfig` in `executor/config.py`, defaulting to temperature control so configs without `type` are unchanged
- [ ] 1.2 Populate it in the `water_heaters[]` loader (`executor/config.py:597`) from the heater's `type`, normalising case and treating unknown values as temperature control
- [ ] 1.3 Skip a heater whose declared type does not match its `target_entity` domain, logging a warning that names the heater — mirroring the existing skip for heaters with no `target_entity`
- [ ] 1.4 Unit-test the loader: binary type loads, absent type defaults to temperature, mismatched pair is skipped with a warning, mixed-type configs load independently

## 2. Binary write path in the dispatcher

- [ ] 2.1 Add the binary water heater write as `set_water_switch`, delegating to the on/off write used by `set_balanced_entity` rather than duplicating its body, and returning results with `action_type="water_switch"`
- [ ] 2.2 Verify the write is domain-guarded to `switch.` / `input_boolean.`, idempotent (skip when already in state), and honours shadow mode
- [ ] 2.3 Audit every consumer of `action_type == "water_temp"` — execution history, the Executor page, the dashboard, any filters or counters — and make each also recognise `water_switch`
- [ ] 2.4 Unit-test the dispatcher path: on, off, already-in-state skip, shadow mode skip, invalid domain rejected, and that results carry `water_switch`

## 3. Per-device executor loop

- [ ] 3.1 Branch the per-device water heater loop in `executor/engine.py:1583` on control type: temperature heaters keep calling `set_water_temp`, binary heaters dispatch the ON/OFF write
- [ ] 3.2 Apply the translation rule in one place: ON when the resolved temperature is strictly greater than `temp_off`, OFF otherwise — so scheduled heating, boost, and load-balancer shed all flow through it
- [ ] 3.3 Confirm load-balancer shed (`shed_water_heater_ids`) resolves a binary heater to OFF without a second code path
- [ ] 3.4 Ensure a failure or skip on one heater does not prevent the other heaters in the same tick from being controlled
- [ ] 3.5 Test the loop: binary heater on/off per schedule, mixed binary and temperature heaters in one tick, shed turns a binary heater off, boost temperature resolves to ON, no number service call is ever made for a binary heater

## 4. Per-device manual boost

- [ ] 4.1 Replace the engine's single `_water_boost_until` with per-heater boost deadlines, and make `set_water_boost` / `clear_water_boost` / `get_water_boost_status` (`executor/engine.py:809`) take and report heater ids
- [ ] 4.2 Add heater selection to `WaterBoostRequest` and the boost/cancel endpoints in `backend/api/routers/water.py`, defaulting to all enabled heaters with a control entity when none is named, and rejecting an unknown heater id
- [ ] 4.3 Make the boost override populate `ControllerDecision.water_temps` per boosted heater (`executor/controller.py:152`) instead of only the scalar `water_temp`, so boost dispatches through the per-device loop and inherits the binary translation automatically
- [ ] 4.4 Remove the dependence on the legacy single-heater `target_entity` for manual boost, including the immediate one-shot write in `set_water_boost`
- [ ] 4.5 Keep the existing battery-SoC protection and its cancellation notification working, now per heater
- [ ] 4.6 Update the boost status payload consumers — dashboard boost indicator, command bar — for the per-heater shape
- [ ] 4.7 Add heater selection to the boost UI when more than one heater is configured, and keep it a single click when only one is
- [ ] 4.8 Test boost end to end: named heater boosted while the other follows its schedule, unnamed request boosts all, independent expiry, clear affects only one heater, boost reaches a heater's own entity with no legacy entity configured, boost on a binary heater switches it ON, shed still overrides boost, low SoC still cancels and notifies

## 5. Config validation

- [ ] 5.1 In `backend/api/routers/config.py:517`, validate `target_entity` against the declared control type — `number.` / `input_number.` for temperature, `switch.` / `input_boolean.` for binary — at `severity: "error"`
- [ ] 5.2 Word the error so it names the control type that would accept the entity the user entered, so a user with `switch.vvb` is told to set the binary type
- [ ] 5.3 Leave the existing power-sensor check at `severity: "warning"` and confirm a heater with no `sensor` still validates and still controls
- [ ] 5.4 Test validation: switch on a temperature heater rejected, number on a binary heater rejected, matching pairs accepted, missing power sensor is not an error

## 6. Settings UI

- [ ] 6.1 Add the control-type selector to the water heater editor in `frontend/src/pages/settings/components/EntityArrayEditor.tsx`
- [ ] 6.2 Label the control entity field according to the selected type so the expected entity domain is clear
- [ ] 6.3 Hide `temp_normal`, `temp_off` and `temp_boost` for a binary heater while leaving the stored values intact, so switching back to temperature control does not lose them
- [ ] 6.4 Hide the boost temperature control for a binary heater in the boost UI

## 7. Verification

- [ ] 7.1 Run the executor, backend and frontend test suites and confirm no regression in existing temperature-heater behavior
- [ ] 7.2 Verify a temperature-only config produces unchanged scheduled execution behavior, with manual boost now reaching the heater where it previously wrote nothing
- [ ] 7.3 Run `openspec validate binary-water-heater-control --strict`
- [ ] 7.4 Update `openspec/specs/` via the archive/sync step rather than by hand
