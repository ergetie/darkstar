## MODIFIED Requirements

### Requirement: Per-device EV config structure
Each entry in `ev_chargers[]` SHALL support the following per-device fields: `switch_entity` (string, HA charging-control entity ID), `charge_enabled_value` (string, default `"on"`), `charge_disabled_value` (string, default `"off"`), `plugged_in_states` (comma-separated string, default `"on,true,1,connected"`), `phase_1_value` (string, default `"1"`), `phase_3_value` (string, default `"3"`), `replan_on_plugin` (boolean, default true), `replan_on_unplug` (boolean, default false), plus hardware facts (`sensor`, `soc_sensor`, `plug_sensor`, `battery_capacity_kwh`, `max_power_kw`, `type`, current/phase entities) and the optional HA goal entities (`ha_ready_by_entity`, `ha_target_soc_entity`). The new mapping fields SHALL be optional and their absence SHALL preserve existing switch-based and numeric phase-option behavior.

`switch_entity` SHALL accept Home Assistant `switch`, `input_boolean`, `select`, and `input_select` domains. For a select-like entity, `charge_enabled_value` and `charge_disabled_value` SHALL both be non-empty and SHALL differ from each other. When a custom `plugged_in_states` value is present, it SHALL contain at least one non-empty comma-separated token. When phase switching is enabled, `phase_1_value` and `phase_3_value` SHALL both be non-empty and SHALL differ from each other.

Config validation SHALL NOT require Home Assistant to be reachable, and SHALL NOT require a configured option value to be present in the entity's current Home Assistant option list.

**Goal fields do NOT live in config.** `target_soc_percent`, `ready_by`, `repeat`, `n_days`, `ready_by_date`, and `keep_on_after_target` SHALL NOT be read from `config.yaml`; goals are owned by `data/ev_multi_day_state.json` via the dashboard/API/HA sync (see `ev-schedule-api`). If any goal field (or the legacy `departure_time` / `penalty_levels`) is present in config, the loader SHALL log a deprecation warning naming the dashboard as the place to set goals, and SHALL ignore the value for scheduling. Malformed values in these ignored fields SHALL NOT crash config loading, and config validation (the settings save/validate path) SHALL NOT report errors or warnings for them — deprecated goal fields MUST never block a settings save, regardless of their value. Config migration strips these fields (see `config-migration`); the loader tolerance exists for configs that have not (yet) been migrated.

**No `charge_priority` field.** Surplus-PV routing is owned by the existing `excess_pv.priority[]` list (see `excess-pv-priority-dispatch`).

#### Scenario: Existing switch configuration keeps current behavior
- **WHEN** a binary charger has `switch_entity: "switch.ev_charger"` and none of the mapping fields
- **THEN** configuration loading SHALL use `on` and `off` charging values, `on,true,1,connected` plugged-in states, and `1` and `3` phase values
- **AND** no configuration migration SHALL be required

#### Scenario: Select-based charge control is valid
- **WHEN** a binary charger has `switch_entity: "select.go_echarger_force_state"`, `charge_enabled_value: "On"`, and `charge_disabled_value: "Off"`
- **THEN** config validation SHALL accept the charger

#### Scenario: Plugged-in states accept multiple values
- **WHEN** a charger has `plugged_in_states: "WaitCar, Charging, Complete"`
- **THEN** the setting SHALL represent three connected states after whitespace trimming

#### Scenario: Empty select mappings are rejected
- **WHEN** a select-based charging control has an empty `charge_enabled_value` or `charge_disabled_value`
- **THEN** config validation SHALL report an actionable error for that charger

#### Scenario: Identical select mappings are rejected
- **WHEN** a select-based charging control has `charge_enabled_value` equal to `charge_disabled_value`
- **THEN** config validation SHALL report an actionable error for that charger

#### Scenario: Settings save succeeds while Home Assistant is offline
- **WHEN** Home Assistant is unreachable and the user saves an EV charger with select mappings
- **THEN** validation SHALL evaluate the stored values without contacting Home Assistant
- **AND** the save SHALL succeed

#### Scenario: Config with goal fields is tolerated but ignored
- **WHEN** a charger config still contains `target_soc_percent: 90` or `departure_time: "07:00"`
- **THEN** the loader SHALL emit a deprecation warning pointing to the dashboard
- **AND** the value SHALL NOT influence scheduling (the state-file goal, or absence of one, governs)

#### Scenario: Malformed legacy goal value does not crash
- **WHEN** a charger config contains `target_soc_percent: "80%"`
- **THEN** config loading SHALL succeed with a warning (no ValueError propagation)

#### Scenario: Malformed legacy goal value does not block settings save
- **WHEN** the stored config contains `departure_time: 1200` on a charger entry (invalid HH:MM)
- **AND** the user saves any change from the settings page
- **THEN** config validation SHALL NOT report an error or warning for `departure_time`
- **AND** the save SHALL succeed

#### Scenario: Charger with no switch entity
- **WHEN** an enabled charger has `switch_entity: ""` or the field is absent
- **THEN** the executor SHALL skip switch control for that charger (planning-only mode)

### Requirement: Per-device executor control loop
The executor SHALL iterate over all enabled chargers with a control entity configured (`switch_entity` for `type: binary`, `current_entity` for `type: current`). For each binary charger, the executor SHALL independently decide whether charging is enabled based on that charger's entry in the schedule's `ev_chargers` dict. A `switch` or `input_boolean` control entity SHALL use its existing turn-on/turn-off service. A `select` or `input_select` control entity SHALL use `select.select_option` with the charger's configured `charge_enabled_value` or `charge_disabled_value`. For each current-type charger, the executor SHALL compute an ampere setpoint from that charger's planned kW (subject to load-balancer capping when enabled) and write it to the `current_entity`.

Idempotence SHALL compare the current HA state with the exact desired mapped state. For select-based control, a state that matches neither configured value SHALL NOT be assumed off: Darkstar SHALL send the configured enabled or disabled value required by the current plan. Action verification, shadow-mode reporting, execution history, and notifications SHALL report the mapped target value while preserving existing start/stop action semantics.

The action result's new value SHALL carry the mapped target value that was sent (`on`/`off` for switch-like control, the configured option for select-like control) rather than a raw boolean. The `ev_charge_start` and `ev_charge_stop` action types SHALL be unchanged.

#### Scenario: Two chargers controlled independently
- **WHEN** the schedule has charger A at 11 kW and charger B at 0 kW in the current slot
- **THEN** the executor SHALL enable charger A through its configured control mechanism
- **AND** the executor SHALL disable (or leave disabled) charger B through its configured control mechanism

#### Scenario: Select charger is enabled with its mapped value
- **WHEN** a scheduled binary charger uses a select entity with `charge_enabled_value: "On"`
- **AND** the select currently has state `Off`
- **THEN** the executor SHALL call `select.select_option` with option `On`
- **AND** the recorded new value SHALL be `On`

#### Scenario: Select charger is explicitly disabled from a neutral state
- **WHEN** an unscheduled binary charger uses a select entity with `charge_disabled_value: "Off"`
- **AND** the select currently has a third state `Neutral`
- **THEN** the executor SHALL call `select.select_option` with option `Off`

#### Scenario: Matching mapped state is skipped
- **WHEN** the desired charging state maps to the select's current state
- **THEN** the executor SHALL skip the redundant HA service call

#### Scenario: Switch charger reports its mapped value
- **WHEN** a switch-based binary charger is turned on
- **THEN** the recorded new value SHALL be `on`
- **AND** the execution-history rendering SHALL be unchanged from the previous boolean behavior

#### Scenario: Charger not in schedule is left off
- **WHEN** a charger has a control entity but no entry in the current slot's `ev_chargers` dict
- **THEN** the executor SHALL leave that charger in its current state (default: off)

#### Scenario: Binary and current chargers coexist
- **WHEN** one enabled charger is `type: binary` and another is `type: current`, both scheduled
- **THEN** each SHALL be actuated via its own mechanism in the same tick

## ADDED Requirements

### Requirement: EV mapping fields are configured from Home Assistant entity metadata
The EV charger settings editor SHALL derive its mapping fields from the selected Home Assistant entity rather than requiring the user to recall vendor-specific values. The entity's domain SHALL be derived from its entity ID prefix. `GET /api/ha/entities` SHALL return an `options` list for `select` and `input_select` entities, sourced from the entity's `options` attribute in the Home Assistant states payload, without introducing an additional request per field.

The editor SHALL hide the charge enabled/disabled value fields entirely when the charging-control entity is switch-like, and SHALL render them as option dropdowns when it is select-like. `phase_1_value` and `phase_3_value` SHALL render as option dropdowns over the phase-mode entity's options, and only when `phase_switching_enabled` is true. `plugged_in_states` SHALL render as a multi-select over the plug sensor's options when the sensor exposes them, and SHALL store the same comma-separated string in either presentation.

When Home Assistant is unreachable, the entity list is empty, or the selected entity exposes no options, every affected field SHALL fall back to a free-text input pre-filled with the stored value. No stored value SHALL be cleared or rewritten because options could not be fetched, and a stored value absent from the fetched option list SHALL be preserved and displayed as the current selection.

#### Scenario: Switch-like control entity hides value fields
- **WHEN** the charging-control entity is `switch.ev_charger`
- **THEN** the charge enabled/disabled value fields SHALL NOT be rendered

#### Scenario: Select-like control entity offers real options
- **WHEN** the charging-control entity is `select.go_echarger_force_state` and Home Assistant reports options `Neutral`, `Off`, `On`
- **THEN** the charge enabled and disabled fields SHALL render as dropdowns containing those three options

#### Scenario: Phase option dropdowns follow the phase-mode entity
- **WHEN** `phase_switching_enabled` is true and the phase-mode entity reports options `Auto`, `Force_1`, `Force_3`
- **THEN** `phase_1_value` and `phase_3_value` SHALL render as dropdowns containing those options

#### Scenario: Offline Home Assistant degrades to text input
- **WHEN** the Home Assistant entity list cannot be fetched
- **AND** the charger has `charge_enabled_value: "On"` stored
- **THEN** the field SHALL render as a text input containing `On`
- **AND** the stored value SHALL remain unchanged unless the user edits it

#### Scenario: Stored value missing from the option list is preserved
- **WHEN** `charge_enabled_value` is `On` and the fetched option list does not contain `On`
- **THEN** the stored value SHALL be displayed as the current selection
- **AND** it SHALL NOT be cleared or replaced by a fetched option
