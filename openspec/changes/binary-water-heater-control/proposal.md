## Why

Water heater control is temperature-only: the executor always writes a target temperature via `set_input_number`, whose domain guard accepts only `number.` / `input_number.` entities. Users whose hot water tank is a plain relay (`switch.vvb`) therefore cannot control it at all, even though `water_heaters[].type` already offers a `"binary"` value that the planner and load model understand. Today such a user configures a switch entity, saves without a hard error, and only discovers at execution time that nothing is ever written.

## What Changes

- Water heaters gain a real binary (ON/OFF) control mode alongside the existing temperature mode. A heater declared `type: "binary"` is driven by turning its `switch.` / `input_boolean.` entity on and off.
- The heater's control type reaches the executor. `WaterHeaterDeviceConfig` currently carries only `id`, `name`, `target_entity`, `power_kw`, so the configured `type` is silently dropped before the executor sees it.
- The executor's per-device water loop branches on control type: temperature heaters keep writing a setpoint; binary heaters are switched ON when the planned temperature exceeds `temp_off` and OFF otherwise. The planner is unchanged — it keeps deciding in temperatures, and the executor translates.
- Manual water boost becomes per-device and is repaired. Boost is currently a single global flag that writes to the legacy single-heater entity, so on any entity-array config it writes nothing at all — for temperature heaters as much as binary ones. The boost API, the engine's boost state, and the override that carries boost into the tick all become per-heater, and the user can choose which heater to boost.
- Manual water boost becomes type-aware. A binary heater has no boost temperature to reach, so boost means "ON for the boost duration"; the temperature controls in the boost UI are not offered for a binary heater.
- Config validation becomes type-aware and blocking: a temperature heater requires a `number.` / `input_number.` control entity, a binary heater requires a `switch.` / `input_boolean.` one, and a mismatch is an error at save time rather than a silent runtime no-op.
- The water heater settings editor exposes the control type and labels the control entity field according to it.
- No breaking change: heaters with no explicit `type` continue to default to temperature control and behave exactly as today.

## Capabilities

### New Capabilities
- `binary-water-heater-control`: ON/OFF control of water heaters whose HA entity is a switch rather than a temperature setpoint — control-type configuration, the temperature-to-ON/OFF translation rule, type-aware validation at config save, and boost semantics for a binary heater.
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
- No migration needed: absent `type` means temperature control, which is the current behavior.
- Existing specs `water-heater-execution` and `per-device-water-scheduling` describe the temperature path; only the former changes, since planning stays in temperatures.
