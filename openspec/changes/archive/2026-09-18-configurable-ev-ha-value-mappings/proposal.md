## Why

Darkstar currently assumes EV charging and plug detection use boolean Home Assistant states, and that phase selectors accept the literal values `1` and `3`. Chargers such as the go-e Gemini Flex expose these controls as selects and report named states, so users cannot reliably control or detect them despite having valid HA entities.

## What Changes

- Add optional per-charger mappings for the values that mean charging enabled and disabled.
- Allow binary EV charging control to target either a switch-like entity or a select entity; switch-like entities retain the current turn-on/turn-off behavior, while select entities receive the configured values.
- Add a configurable comma-separated list of plug-sensor states that count as connected, with whitespace-trimmed, case-insensitive matching.
- Add configurable 1-phase and 3-phase option values for phase-mode select entities.
- Use one shared plug-state interpretation across every consumer: planner reads, WebSocket updates, the EV dashboard API, and system status.
- Expose all mappings in EV charger settings, driven by the selected entity's domain and its real Home Assistant select options, and validate them against that domain.
- Preserve current behavior when the new fields are absent, so existing configurations require no migration.
- Keep current-controlled charging, planner behavior, and dynamic ampere setpoints unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `per-device-ev-scheduling`: Extend per-charger configuration and binary executor control to support configurable select values while retaining legacy switch behavior.
- `ev-charging-replan`: Interpret configurable connected-state lists consistently for initial HA reads, live WebSocket plug transitions, and every other plug-state consumer.
- `ev-phase-switching`: Send configurable 1-phase and 3-phase select options instead of hardcoded numeric strings.

## Impact

- Backend/executor EV charger configuration models, loading, validation, and HA action dispatch.
- All four plug-state consumers: `backend/core/ha_client.py`, `backend/ha_socket.py`, `backend/api/routers/ev.py`, `backend/api/routers/system.py`.
- `GET /api/ha/entities` gains an `options` field for `select`/`input_select` entities so settings can offer real option dropdowns.
- Settings UI types and EV charger editor fields, including domain-aware conditional rendering.
- Execution-history/action reporting for EV charge actions, whose `new_value` becomes the mapped target value.
- `config.default.yaml` documentation and focused backend/frontend tests.
- No dependency, database schema, planner, or schedule-format changes.
