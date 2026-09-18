## Context

EV charger integrations expose equivalent operations through different Home Assistant domains and state vocabularies. Darkstar currently treats `switch_entity` as a switch with `on`/`off`, reads `plug_sensor` through generic boolean parsing, and writes phase modes as `"1"`/`"3"`. The go-e Gemini Flex instead uses select options such as `On`, `Off`, `Force_1`, and `Force_3`, while its car-state sensor reports several connected states such as `WaitCar`, `Charging`, and `Complete`.

This change crosses configuration loading, settings validation/UI, executor actions, initial HA state reads, and WebSocket event handling. The configuration must remain valid for existing users without migration.

Four independent code paths currently derive "is the EV plugged in" from `plug_sensor`:

| Path | Current parsing | Consumer |
| --- | --- | --- |
| `backend/core/ha_client.py` (~line 515) | `get_ha_bool` | planner / initial per-device read |
| `backend/ha_socket.py` (`ev_plug_*` mapping, ~lines 157, 513) | generic boolean | live WebSocket state, replan trigger |
| `backend/api/routers/ev.py` (~line 311) | `_safe_bool` | EV dashboard cards |
| `backend/api/routers/system.py` (~line 87) | `get_ha_bool` | system status strip |

If only the first two learned charger-specific vocabularies, a go-e reporting `WaitCar` would plan as connected while the dashboard and status strip showed disconnected. All four must route through the same helper.

## Goals / Non-Goals

**Goals:**

- Let each charger define the exact HA values Darkstar sends for charge enable/disable and 1/3-phase selection.
- Let each charger define multiple raw plug states that mean connected through one comma-separated setting.
- Use identical plug-state semantics for initial REST reads, live WebSocket updates, the EV dashboard API, system status, UI state, and replan decisions.
- Derive the settings UI from the selected entity's HA domain and real select options, so mappings are chosen from dropdowns rather than typed from memory.
- Preserve existing switch-based and numeric phase-mode behavior when mappings are omitted.
- Keep actions idempotent and make select-based stop commands explicit, including when the current select state is neither configured on nor configured off.

**Non-Goals:**

- An EV charger profile/catalog system or charger-specific code paths.
- Changes to planning, scheduling, dynamic-current control, or the meaning of `current_entity`.
- Using a charger's maximum-ampere limit as Darkstar's dynamic ampere setpoint.
- Commanding a charger-specific automatic phase mode; Darkstar's existing phase controller commands only one or three phases.
- Guessing which option means "on" — Home Assistant supplies the option list, the user chooses the meaning.
- Requiring Home Assistant to be reachable in order to open, edit, or save settings.

## Decisions

### Add optional value mappings to each charger

Extend the per-device EV configuration with string fields equivalent to:

- `charge_enabled_value`, default `on`
- `charge_disabled_value`, default `off`
- `plugged_in_states`, default `on,true,1,connected`
- `phase_1_value`, default `1`
- `phase_3_value`, default `3`

The loader will trim scalar values. Plug-state parsing will split on commas, trim every token, discard empty tokens, and compare case-insensitively. Outgoing select values retain the user's spelling and case because Home Assistant select options can be case-sensitive.

Keeping these fields on each charger supports mixed hardware without a profile abstraction. Defaults reproduce the established switch and phase behavior and the documented EV connected-state vocabulary.

Alternative considered: model mappings as nested profile objects. Rejected because it adds indirection and migration complexity without helping the requested generic integration.

### Retain `switch_entity` as the compatibility field

The existing `switch_entity` key will accept `switch`, `input_boolean`, `select`, or `input_select` entities. The settings label and guidance will describe it as the charging control entity, but the stored key remains unchanged to avoid configuration migration.

For switch-like domains, Darkstar continues to call the on/off service and treats `on`/`off` as authoritative. For select-like domains, it calls `select.select_option` with `charge_enabled_value` or `charge_disabled_value`. Current-state comparison uses the corresponding desired raw value so a third state such as `Neutral` does not cause a stop command to be skipped.

Alternative considered: add a second `select_entity` key. Rejected because it creates mutually exclusive fields and complicates validation and UI behavior.

### Centralize raw-state matching

Introduce one side-effect-free helper for normalizing the configured connected-state CSV and evaluating a raw HA state. All four plug-state paths in the Context table will call this helper with the charger-specific configuration instead of generic boolean helpers or duplicated hardcoded sets.

Because `backend/api/routers/system.py` aggregates chargers into a single `ev_plugged_in` flag, it resolves each charger against that charger's own configuration before aggregating; it must not apply one charger's vocabulary to another.

WebSocket replans will occur only when the derived connected boolean changes. Transitions between two configured connected states, such as `WaitCar` to `Charging`, update the raw state but do not produce another plug-in replan.

Alternative considered: extend the global HA boolean parser. Rejected because charger-specific values differ per device and changing a global helper could alter unrelated features.

### Keep phase control numeric internally and map only at the HA boundary

The phase state machine continues to reason in phase counts `1` and `3`. `ActionDispatcher.set_ev_phase_mode` gains the mapped option as an argument; the engine resolves the count to the charger's configured `phase_1_value` or `phase_3_value` before dispatch. Idempotence checks, shadow-mode output, read-back verification, and any commanded-mode caching in the engine all use the mapped value, so a charger reporting `Force_3` is never seen as differing from a commanded `3`.

The existing phase-mode entity remains a select. The `Auto` option exposed by some chargers is not sent because the current controller intentionally selects one or three phases; if the entity is currently `Auto`, the next warranted phase decision sends the configured forced option.

### Report the mapped target value in action results

`set_ev_charger_switch` currently sets `ActionResult.new_value` to the boolean `turn_on`. It will instead carry the mapped target string (`on`/`off` for switch-like control, the configured option for select control), matching what was actually sent and what verification compares against.

This is display-safe: the execution-history column is already `String` (`backend/learning/models.py:134`), and the Executor page already renders a boolean as `on`/`off` and a string verbatim (`frontend/src/pages/Executor.tsx:1246`). Switch-based chargers therefore render exactly as they do today, while select-based chargers gain an accurate value instead of a misleading `true`.

The `ev_charge_start` / `ev_charge_stop` action types and notification semantics are unchanged.

### Drive the settings UI from Home Assistant's own metadata

Typing `Force_1` by hand is the most likely way this feature fails in practice: a wrong case or a typo produces an HA service error at execution time, hours later. The settings UI will therefore derive its fields from the selected entity rather than asking the user to recall vendor values.

`GET /api/ha/entities` already returns one row per entity with its `domain`. It will additionally return `options: string[]` for `select` and `input_select` entities, read from the entity's `options` attribute in the same `/api/states` response it already parses. This adds no extra round trip and no new endpoint; settings already fetch this list once.

Given that, the EV charger editor behaves as follows:

- The domain comes from the entity ID prefix, which requires no HA call and cannot be wrong.
- **Switch-like control entity** (`switch`, `input_boolean`): the enabled/disabled value fields are hidden entirely. There is nothing to configure.
- **Select-like control entity** (`select`, `input_select`): the enabled and disabled fields render as dropdowns populated from that entity's `options`, so the user picks `On` and `Off` from the charger's real vocabulary.
- **Phase-mode entity**: `phase_1_value` and `phase_3_value` render as dropdowns over that entity's `options`, shown only when `phase_switching_enabled` is on.
- **Plugged-in states**: rendered as a multi-select over the plug sensor's `options` when the sensor exposes them, and as the comma-separated text field otherwise (plain `sensor` entities usually publish no option list). Either way the stored value is the same CSV string.

Degradation is explicit and total: when Home Assistant is unreachable, the entity list is empty, or an entity publishes no `options`, every affected field falls back to a free-text input pre-filled with the stored value. No stored value is ever cleared or rewritten because options could not be fetched, and a value not present in the fetched options is preserved and shown as the current selection rather than silently dropped — HA option lists can change while a charger is offline.

Save-time validation never contacts Home Assistant (see below), so settings remain fully editable offline. The dropdowns are a convenience layer over the same string fields, not a new source of truth.

Alternative considered: fetch options per entity via the existing `GET /api/ha/entity/{id}`. Rejected because it adds one request per field per render for data the bulk list can carry for free.

### Validate configuration without live vendor assumptions

Settings validation will:

- accept `switch`, `input_boolean`, `select`, and `input_select` domains for `switch_entity`;
- require non-empty `charge_enabled_value` and `charge_disabled_value` when the control entity is select-like, and require the two to differ;
- require at least one non-empty connected token when a custom `plugged_in_states` CSV is supplied;
- require non-empty, mutually different `phase_1_value` and `phase_3_value` when phase switching is enabled;
- require `phase_mode_entity` to be a `select` or `input_select` entity when phase switching is enabled, since dispatch always calls `select.select_option` (this closes an existing gap where only non-emptiness was checked).

It will not hardcode go-e option names, will not require the configured option to appear in HA's current option list, and will not require HA to be online during a settings save.

## Risks / Trade-offs

- [A mistyped select option causes an HA service error] → Offer HA's real options as dropdowns, preserve HA error reporting and action verification, validate non-empty distinct values, and show exact-value guidance in settings.
- [Four code paths interpret plug states differently] → Route all four consumers through the same helper and cover them with shared test cases.
- [HA offline makes settings unusable] → Dropdowns degrade to text inputs, stored values are never cleared, and validation never calls HA.
- [A stored option disappears from HA's option list] → Keep and display the stored value as the current selection rather than dropping it.
- [Connected-to-connected sensor transitions trigger repeated replans] → Compare previous and next derived booleans before invoking replan logic.
- [Aggregate status applies the wrong charger's vocabulary] → Resolve each charger against its own config before aggregating.
- [`new_value` type change breaks history display] → Verified the renderer already handles both shapes; switch-based output is byte-identical to today.
- [Changing the label while retaining `switch_entity` is internally inconsistent] → Keep the key solely for compatibility and use user-facing terminology that reflects all supported domains.
- [Defaults cannot represent every historical generic boolean synonym] → Use the established EV states (`on,true,1,connected`) and make the list editable per charger; unrelated generic boolean parsing remains unchanged.

## Migration Plan

1. Add loader defaults before changing any consumers so absent fields remain valid.
2. Add the shared plug-state helper and move all four consumers onto it.
3. Update action dispatch, phase mapping, and backend validation.
4. Extend `GET /api/ha/entities` with `options`.
5. Update settings UI and `config.default.yaml` examples.
6. Add compatibility and go-e-style tests covering every path.

Rollback is safe because no database or state-file migration is involved. Configurations that have saved new fields remain readable as extra YAML keys by the previous version, although the previous version will ignore their mappings.

## Open Questions

None. The agreed behavior is generic user-supplied mappings with backward-compatible defaults, presented through HA-derived dropdowns that degrade to text inputs.
