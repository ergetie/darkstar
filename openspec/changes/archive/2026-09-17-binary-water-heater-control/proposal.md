## Why

Water heater control is temperature-only: the executor always writes a target temperature via `set_input_number`, whose domain guard accepts only `number.` / `input_number.` entities. Users whose hot water tank is a plain relay (`switch.vvb`) therefore cannot control it at all. Today such a user configures a switch entity, saves without a hard error, and only discovers at execution time that nothing is ever written.

Note that the existing `water_heaters[].type` field does **not** express this. It describes the *load model* — `"binary"` vs `"modulating"`, consumed by `backend/loads/service.py` — and it defaults to `"binary"` for every heater, including temperature-controlled ones. The current production config has `type: binary` alongside `target_entity: input_number.vvbtemp`. Control type therefore needs its own field.

## What Changes

- Water heaters gain a real switch (ON/OFF) control mode alongside the existing temperature mode, selected by a new `water_heaters[].control_type` field with values `"temperature"` (default) and `"switch"`.
- The existing `type` field is left alone. It keeps meaning the load model, and is not read as a control type anywhere.
- The control type reaches the executor. `WaterHeaterDeviceConfig` currently carries only `id`, `name`, `target_entity`, `power_kw`, so it gains the new field.
- The executor's per-device water loop branches on control type: temperature heaters keep writing a setpoint; switch heaters are switched ON when the planned temperature exceeds `temp_off` and OFF otherwise. The planner is unchanged — it keeps deciding in temperatures, and the executor translates.
- Manual water boost becomes per-device and is repaired. Boost is currently a single global flag that writes to the legacy single-heater entity, so on any entity-array config it writes nothing at all — for temperature heaters as much as binary ones. The boost API, the engine's boost state, and the override that carries boost into the tick all become per-heater, and the user can choose which heater to boost.
- Manual water boost becomes control-type-aware. A switch heater has no boost temperature to reach, so boost means "ON for the boost duration"; the temperature controls in the boost UI are not offered for it.
- Config validation becomes control-type-aware and blocking: `control_type: temperature` requires a `number.` / `input_number.` control entity, `control_type: switch` requires a `switch.` / `input_boolean.` one, and a mismatch is an error at save time rather than a silent runtime no-op.
- The water heater settings editor exposes the control type and labels the control entity field according to it.
- No breaking change: `control_type` is new and defaults to `"temperature"`, so every existing config — all of which are temperature-controlled — behaves exactly as today with no migration.

## Capabilities

### New Capabilities
- `binary-water-heater-control`: ON/OFF control of water heaters whose HA entity is a switch rather than a temperature setpoint — the `control_type` field, the temperature-to-ON/OFF translation rule, control-type-aware validation at config save, and boost semantics for a switch heater.
- `per-device-water-boost`: manual boost targeted at a chosen water heater — per-heater boost state, per-heater dispatch through the existing per-device control loop, and device selection in the API and UI.

### Modified Capabilities
- `water-heater-execution`: the per-device executor loop and the boost requirement currently assume every heater is driven by a temperature setpoint. Both gain a binary branch, and the "follows EV charger control pattern" requirement extends to cover the switch write path.

## Impact

- `executor/config.py` — `WaterHeaterDeviceConfig` gains the control type; the loader that builds it from `water_heaters[]` must carry the field through.
- `executor/engine.py` — the per-device water heater loop (`_tick`) branches per heater; `set_water_boost` / `clear_water_boost` become per-heater and type-aware; the boost override populates per-device temperatures instead of only the legacy scalar.
- `executor/controller.py` — the override path currently sets only the scalar `water_temp`, leaving `water_temps` empty; it must carry per-heater boost targets.
- `backend/api/routers/water.py` — the boost request gains a heater selection; `WaterBoostRequest` currently carries only `duration_minutes`.
- `executor/actions.py` — a binary water heater write path, reusing the existing on/off writer rather than adding a second one.
- `backend/api/routers/config.py` — type-aware validation of the water heater control entity at save time.
- `frontend/src/pages/settings/components/EntityArrayEditor.tsx` — control type field and entity-field labelling.
- `backend/loads/base.py`, `backend/loads/service.py` — unchanged. The load-model `type` field keeps its current meaning and consumers.
- No migration needed: absent `control_type` means temperature control, which is the current behavior for every existing config.
- Existing specs `water-heater-execution` and `per-device-water-scheduling` describe the temperature path; only the former changes, since planning stays in temperatures.
