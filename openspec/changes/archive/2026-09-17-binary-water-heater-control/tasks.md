Line numbers are from the commit that introduced this change and may drift — locate by symbol name if a line does not match.

Terminology: **`control_type`** (values `"temperature"` / `"switch"`) is the NEW field this change adds. **`type`** (values `"binary"` / `"modulating"`) is the EXISTING load-model field and must not be read as a control type — it defaults to `"binary"` on every heater, including temperature-controlled ones.

## 1. Config: carry `control_type` into the executor

- [x] 1.1 In `executor/config.py`, add `control_type: str = "temperature"` to `WaterHeaterDeviceConfig` (line 116), with a comment stating it is the control mode and is distinct from the load-model `type`
- [x] 1.2 In the `water_heaters[]` loader (`executor/config.py:597-611`), read `heater.get("control_type", "temperature")`, lowercase and strip it, map any value other than `"switch"` to `"temperature"`, and pass it to the constructor
- [x] 1.3 In the same loop, after resolving `target_ent`, skip the heater with `logger.warning` naming the heater id when `control_type == "switch"` and `target_ent` does not start with `switch.` or `input_boolean.`, or when `control_type == "temperature"` and it does not start with `number.` or `input_number.` — matching the existing `continue` for heaters with no `target_entity` (line 601)
- [x] 1.4 Add tests in `tests/executor/` for the loader: `control_type: "switch"` loads as switch; absent `control_type` loads as temperature; `type: "binary"` with `target_entity: "input_number.vvbtemp"` and no `control_type` loads as **temperature** (regression guard for the current production config); an unrecognised `control_type` value falls back to temperature; a mismatched control_type/entity pair is skipped and warned; two heaters with different control types load independently

## 2. Dispatcher: the switch write path

- [x] 2.1 In `executor/actions.py`, add `async def set_water_switch(self, entity_id: str, on: bool) -> ActionResult` next to `set_water_temp` (line 787), returning results with `action_type="water_switch"`
- [x] 2.2 Implement it by delegating to the same write `set_balanced_entity` uses (`self._write_entity(entity_id, value, domain)`, `executor/actions.py:937`) rather than duplicating its body; extract the shared portion if that is cleaner than calling through
- [x] 2.3 Preserve the four behaviours `set_balanced_entity` already has: idempotent skip via `_values_match` when the entity is already in the target state, shadow-mode skip, `HACallError` capture into `error_details`, and `previous_value` / `new_value` population
- [x] 2.4 Verify the domain guard rejects anything outside `switch.` / `input_boolean.` — `_get_safe_domain` at `executor/actions.py:411` already enforces this via `set_switch`
- [x] 2.5 Add read-back verification consistent with the other action types, calling `_verify_action(entity_id, "on"/"off")` — note `_values_match` (line 596) already handles on/off vs boolean comparison
- [x] 2.6 In `_maybe_notify`'s action map (`executor/actions.py:1393-1403`), make a switch heater turning on/off notify via the same `on_water_heat_start` / `on_water_heat_stop` flags the temperature path uses (`set_water_temp` picks these at line 872-875)
- [x] 2.7 Add tests in `tests/executor/test_executor_actions.py`: turns on, turns off, skips when already in state, skips in shadow mode, rejects a `number.` entity, and returns `action_type == "water_switch"`

## 3. Executor: branch the per-device loop

- [x] 3.1 In `executor/engine.py:1583-1593`, inside the `for device in self.config.water_heater_devices` loop, branch after `temp` is resolved (so the shed override at line 1587 still applies first): `control_type == "switch"` dispatches `set_water_switch(device.target_entity, temp > self.config.water_heater.temp_off)`, otherwise keep the existing `set_water_temp(temp, device.target_entity)` call
- [x] 3.2 Keep appending the result to `action_results` identically for both branches (line 1593), so history and the Executor page need no structural change
- [x] 3.3 Leave the legacy single-heater fallback at `executor/engine.py:1594-1597` untouched — it is temperature-only by definition
- [x] 3.4 Wrap each heater's dispatch so an exception on one heater is logged and does not abort the loop for the others
- [x] 3.5 Add tests in `tests/executor/test_executor_engine.py`: a switch heater turns on when its planned kW > 0 and off when 0; a switch and a temperature heater in the same tick each get their own call type; a shed switch heater is turned OFF; a tick where the resolved temp equals `temp_boost` still turns the switch heater ON; assert `set_input_number` is never called for a switch heater

## 4. Per-device manual boost

- [x] 4.1 In `executor/engine.py`, replace `self._water_boost_until: datetime | None` (line 234) with a `dict[str, datetime]` keyed by heater id, and update every reader: lines 837, 873-874, 904-914, 1278
- [x] 4.2 Change `set_water_boost(duration_minutes)` (line 809) to `set_water_boost(duration_minutes, heater_ids: list[str] | None = None)`, defaulting `None` to every id in `self.config.water_heater_devices`; reject an id that matches no configured heater
- [x] 4.3 Delete the immediate one-shot `dispatcher.set_water_temp(temp_boost)` call at `executor/engine.py:851` — with 4.5 in place the next tick delivers the boost through the per-device loop, and that call targets the legacy entity that is normally unset
- [x] 4.4 Do the same for `clear_water_boost` (line 870): take optional heater ids, clear only those, and drop the legacy `set_water_temp(temp_off)` call at line 884
- [x] 4.5 In `executor/engine.py:1289-1298`, make the boost `OverrideResult` carry per-heater targets — add a `water_temps` dict mapping each boosted heater id to `temp_boost` alongside the existing scalar `water_temp`
- [x] 4.6 In `executor/controller.py:152`, populate `ControllerDecision.water_temps` from that dict (currently only the scalar `water_temp` at line 170 is set, leaving `water_temps` empty — this is the bug that makes boost a no-op on entity-array configs)
- [x] 4.7 Make `get_water_boost_status` (line 898) return per-heater entries (heater id, `expires_at`, `remaining_seconds`) rather than one global object, keeping a top-level "any boost active" flag so existing consumers have something simple to read
- [x] 4.8 Update `_emit_water_boost_status` (line 919) and the `water_boost_updated` WebSocket payload for the new shape
- [x] 4.9 In `backend/api/routers/water.py`, add `heater_ids: list[str] | None = None` to `WaterBoostRequest` (line 32), pass it through `set_water_boost` (line 58) and the cancel endpoint (line 83), and return 400 for an unknown heater id
- [x] 4.10 Update the boost types and calls in `frontend/src/lib/api.ts` (`water_boost` at line 509, `Api.waterBoost` at line 834) for the per-heater shape
- [x] 4.11 Update `frontend/src/components/CommandBar.tsx` (lines 39, 92-95, 111, 168-173, 212-217) to read per-heater boost state, send the selected heater, and show which heaters are boosted
- [x] 4.12 Add a heater picker to the boost control when `water_heaters[]` has more than one entry, and keep it a single click when there is exactly one
- [x] 4.13 Verify `frontend/src/components/ChartCard.tsx`'s `waterBoost` series (lines 258, 454, 1711-1838) still renders — it reads scheduled boost from the plan, not manual boost status, so it should need no change; confirm rather than assume
- [x] 4.14 Keep the low-SoC boost cancellation and its awaited notification working (`executor/engine.py:1269-1285`), now per heater
- [x] 4.15 Add tests: boosting one heater leaves the other on schedule; an unnamed request boosts all; independent expiry; clearing one heater does not clear the other; boost reaches a heater's own `target_entity` with no legacy entity configured; boost on a switch heater turns it ON; a shed heater stays off despite an active boost; low SoC still cancels and notifies

## 5. Config validation

- [x] 5.1 In `backend/api/routers/config.py`, inside the water heater loop (after the sensor check at line 517), add a `control_type` validation block: `"switch"` requires `target_entity` starting `switch.` or `input_boolean.`, `"temperature"` (including absent) requires `number.` or `input_number.`
- [x] 5.2 Emit these as `severity: "error"`, with a message naming the heater and stating which `control_type` would accept the entity the user entered (e.g. "`switch.vvb` is a switch — set control_type to 'switch' to control this heater")
- [x] 5.3 Validate that `control_type`, when present, is one of `"temperature"` / `"switch"`, emitting a warning and treating anything else as `"temperature"`
- [x] 5.4 Leave the power-sensor check at line 519-526 as `severity: "warning"` and the `type` / `WATER_HEATER_LOAD_TYPES` check at line 530 unchanged
- [x] 5.5 Add tests in `tests/` for config validation: `switch.` entity with no `control_type` is an error; `number.` entity with `control_type: "switch"` is an error; each matching pair passes; a heater with no `sensor` produces no error; `type: "binary"` alone never triggers a control-entity error

## 6. Settings UI

- [x] 6.1 In `frontend/src/pages/settings/components/EntityArrayEditor.tsx`, add `control_type: 'temperature' | 'switch'` to the `WaterHeaterEntity` interface (line 13-24), leaving the existing `type: 'binary' | 'modulating'` field as it is
- [x] 6.2 Default `control_type` to `'temperature'` in the new-water-heater factory (line 73-79)
- [x] 6.3 Add a control-type selector to the water heater editor, labelled so it is clearly about how the heater is commanded, not about the load model
- [x] 6.4 Make the `target_entity` field's label and help text switch with the selection — the current text at line 406 ("Thermostat entity for controlling water heater temperature") is wrong for a switch heater — and filter the `EntitySelect` to the matching domains
- [x] 6.5 Hide the `temp_normal` / `temp_off` / `temp_boost` inputs for a heater with `control_type: 'switch'`, without deleting the stored values
- [x] 6.6 Hide the boost temperature control for a switch heater wherever boost is offered

## 7. Verification

- [x] 7.1 Confirm the Executor page needs no action-type change: it renders `res.type` generically via `type.replace(/_/g,' ')` (`frontend/src/pages/Executor.tsx:1207`) and only appends `°C` when `type.includes('temp')` (line 1252), which `water_switch` correctly does not match — verify by eye, then note it as checked
- [x] 7.2 Run `.venv/bin/pytest tests/` and confirm no regression
- [x] 7.3 Run the frontend test suite and `tsc` type check
- [x] 7.4 Load the current production config shape (`type: binary` + `input_number.vvbtemp`, no `control_type`) and confirm it still validates clean and still executes as a temperature heater
- [x] 7.5 Run `openspec validate binary-water-heater-control --strict`
