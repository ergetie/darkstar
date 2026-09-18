## 1. Configuration Model and State Mapping

- [x] 1.1 Extend `EVChargerDeviceConfig` and its loader with trimmed `charge_enabled_value`, `charge_disabled_value`, `plugged_in_states`, `phase_1_value`, and `phase_3_value` fields using the specified backward-compatible defaults.
- [x] 1.2 Add a side-effect-free EV plug-state parser that splits configured CSV values, trims and case-normalizes tokens, discards empty tokens, and evaluates raw HA states.
- [x] 1.3 Move the planner/initial per-device HA read (`backend/core/ha_client.py`) onto the charger-specific parser, fetching the raw plug state instead of the generic boolean helper.
- [x] 1.4 Move the EV dashboard API (`backend/api/routers/ev.py`, `_safe_bool` on `plug_sensor`) onto the same parser so dashboard cards agree with the planner.
- [x] 1.5 Move system status (`backend/api/routers/system.py`, `get_ha_bool` on `plug_sensor`) onto the same parser, resolving each charger against its own configuration before aggregating into `ev_plugged_in`.

## 2. Home Assistant Control and Live State

- [x] 2.1 Refactor binary EV charge dispatch so `switch` and `input_boolean` entities retain turn-on/turn-off services while `select` and `input_select` entities receive the configured enabled/disabled option via `select.select_option`.
- [x] 2.2 Update executor idempotence, shadow-mode output, verification, history, and notifications to use the mapped desired charge state, including explicitly sending the disabled option from third states such as `Neutral`, and set `ActionResult.new_value` to the mapped target string while keeping the `ev_charge_start`/`ev_charge_stop` action types unchanged.
- [x] 2.3 Pass each charger's configured phase option values through `set_ev_phase_mode` and use the mapped option consistently for HA writes, idempotence, shadow mode, verification, and any commanded-mode caching in the engine, while retaining numeric phase counts in the controller.
- [x] 2.4 Update WebSocket EV plug handling (`backend/ha_socket.py`) to use the shared charger-specific parser for live and aggregate state and trigger plug/unplug replans only when the derived connected boolean changes.

## 3. Settings, Entity Metadata, and Shipped Configuration

- [x] 3.1 Update backend settings validation to accept `select`/`input_select` charging-control entities, require non-empty and mutually different select charge mappings, validate custom connected-state CSV input, require non-empty and mutually different phase mappings when phase switching is enabled, and require `phase_mode_entity` to be a select-like entity when phase switching is enabled — without contacting Home Assistant.
- [x] 3.2 Extend `GET /api/ha/entities` to return `options: string[]` for `select` and `input_select` entities from the existing `/api/states` payload, and add the field to the frontend `HaEntity` type and `api.haEntities` typing.
- [x] 3.3 Extend the frontend `EVChargerEntity` type and `createDefaultEVCharger` with the new mapping fields, persisting explicit values when edited and rendering documented defaults when absent.
- [x] 3.4 Make the EV charger editor domain-aware: hide the enabled/disabled value fields for switch-like control entities, and render them as dropdowns over the selected entity's `options` for select-like control entities.
- [x] 3.5 Render `phase_1_value` and `phase_3_value` as dropdowns over the phase-mode entity's `options`, shown only when `phase_switching_enabled` is on.
- [x] 3.6 Render `plugged_in_states` as a multi-select over the plug sensor's `options` when available and a comma-separated text field otherwise, storing the same CSV string either way.
- [x] 3.7 Implement the offline/degraded fallback for 3.4–3.6: fall back to free-text inputs pre-filled with the stored value when HA is unreachable, the entity list is empty, or the entity publishes no `options`; never clear a stored value, and preserve and display a stored value that is absent from the fetched options.
- [x] 3.8 Rename the user-facing switch field label/guidance to “Charging Control Entity” without changing the stored `switch_entity` key.
- [x] 3.9 Add the new optional fields and backward-compatible defaults to `config.default.yaml`, including a go-e-style example in comments without introducing vendor-specific runtime behavior.

## 4. Automated Verification

- [x] 4.1 Add executor configuration tests covering omitted-field defaults, whitespace trimming, select mappings, and custom phase mappings.
- [x] 4.2 Add action/executor tests for legacy switch service calls, select enable/disable calls, redundant-call skipping, `Neutral` to `Off`, mapped verification, shadow mode, HA write failures, and the mapped `new_value` payload for both switch-like and select-like control.
- [x] 4.3 Add phase-switching tests proving `Force_1`/`Force_3` mappings are sent, that idempotence and verification compare against the mapped value, and that legacy `1`/`3` defaults remain unchanged.
- [x] 4.4 Add plug-state tests for CSV normalization, case-insensitive matching, and unlisted states, asserting that all four consumers (planner read, WebSocket, EV dashboard API, system status) derive the same boolean from the same raw state, that per-charger vocabularies do not leak across chargers in the aggregate, and that connected-to-connected transitions trigger no replan.
- [x] 4.5 Add config-validation tests for supported entity domains, invalid empty or identical mappings, and select-domain enforcement on `phase_mode_entity`.
- [x] 4.6 Add frontend tests for the entity-metadata UI: switch-like control hides the value fields, select-like control renders options as dropdowns, phase and plug fields populate from `options`, missing/empty `options` degrades to text input with the stored value intact, and a stored value absent from the option list is preserved and displayed.
- [x] 4.7 Run the focused backend and frontend test suites for EV config, actions, replanning, validation, HA entity listing, and settings, then run `./scripts/lint.sh` and resolve all failures.
