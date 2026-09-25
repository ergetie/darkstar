## MODIFIED Requirements

### Requirement: Per-device EV config structure
Each entry in `ev_chargers[]` SHALL support the following per-device fields: `switch_entity` (string, HA charging-control entity ID), `charge_enabled_value` (string, default `"on"`), `charge_disabled_value` (string, default `"off"`), `plugged_in_states` (comma-separated string, default `"on,true,1,connected"`), `phase_1_value` (string, default `"1"`), `phase_3_value` (string, default `"3"`), `replan_on_plugin` (boolean, default true), `replan_on_unplug` (boolean, default false), plus hardware facts (`sensor`, `soc_sensor`, `plug_sensor`, `battery_capacity_kwh`, `type`, current/phase entities) and the optional HA goal entities (`ha_ready_by_entity`, `ha_target_soc_entity`). The new mapping fields SHALL be optional and their absence SHALL preserve existing switch-based and numeric phase-option behavior.

**Charger power fields:**
- `type: current` chargers SHALL specify power only through `min_current_a`, `max_current_a` and `phases`. Their power limits are derived (see `ev-charging-power`).
- `type: binary` chargers SHALL specify `rated_power_kw` (> 0).
- `max_power_kw` and `nominal_power_kw` SHALL NOT be read for EV chargers. Config migration converts them (see `ev-charging-power`).

`switch_entity` SHALL accept Home Assistant `switch`, `input_boolean`, `select`, and `input_select` domains. For a select-like entity, `charge_enabled_value` and `charge_disabled_value` SHALL both be non-empty and SHALL differ from each other. When a custom `plugged_in_states` value is present, it SHALL contain at least one non-empty comma-separated token. When phase switching is enabled, `phase_1_value` and `phase_3_value` SHALL both be non-empty and SHALL differ from each other.

Config validation SHALL NOT require Home Assistant to be reachable, and SHALL NOT require a configured option value to be present in the entity's current Home Assistant option list.

**Goal fields do NOT live in config.** `target_soc_percent`, `ready_by`, `repeat`, `n_days`, `ready_by_date`, and `keep_on_after_target` SHALL NOT be read from `config.yaml`; goals are owned by `data/ev_multi_day_state.json` via the dashboard/API/HA sync (see `ev-schedule-api`). If any goal field (or the legacy `departure_time` / `penalty_levels`) is present in config, the loader SHALL log a deprecation warning naming the dashboard as the place to set goals, and SHALL ignore the value for scheduling. Malformed values in these ignored fields SHALL NOT crash config loading, and config validation (the settings save/validate path) SHALL NOT report errors or warnings for them — deprecated goal fields MUST never block a settings save, regardless of their value. Config migration strips these fields (see `config-migration`); the loader tolerance exists for configs that have not (yet) been migrated.

**No `charge_priority` field.** Surplus-PV routing is owned by the existing `excess_pv.priority[]` list (see `excess-pv-priority-dispatch`).

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


#### Scenario: Current charger without kW field is valid
- **WHEN** a current charger has `min_current_a: 6`, `max_current_a: 10`, `phases: [1,2,3]`, and no `max_power_kw`
- **THEN** config validation SHALL accept the charger and its limits SHALL be derived

### Requirement: EV charger with invalid power is registered as disabled
The load registration service SHALL register as visible-but-disabled any EV charger whose derived maximum power (see `ev-charging-power`) is ≤ 0 or cannot be derived. This covers:
- a `type: current` charger missing `max_current_a` or `phases`, or with `max_current_a` ≤ 0;
- a `type: binary` charger with missing or ≤ 0 `rated_power_kw`.

The charger SHALL appear in the load registry with a `disabled_reason` of `"missing_power_kw"` so it remains visible in the UI and health surfaces. The planner's adapter SHALL exclude such chargers when building `KeplerConfig.ev_chargers`, and the solver SHALL NOT create decision variables for them.

A `HealthIssue` with `category="ev"`, `severity="critical"`, and `code="EV_MISSING_POWER"` SHALL be emitted for each such charger. The issue's `entity_id` SHALL be the charger ID. `details` SHALL include the charger ID, the charger type, and the offending field values. The guidance SHALL name the fields to set: amps and phases for current chargers, `rated_power_kw` for binary chargers.

#### Scenario: Current charger missing max_current_a registers as disabled
- **GIVEN** an enabled current charger with no `max_current_a`
- **WHEN** the load service loads configuration
- **THEN** the charger is registered with `disabled_reason="missing_power_kw"`
- **AND** a `HealthIssue` is emitted with category `ev`, severity `critical`, code `EV_MISSING_POWER`, and `entity_id` set to the charger ID

#### Scenario: Binary charger with zero rated power registers as disabled
- **GIVEN** an enabled binary charger with `rated_power_kw: 0`
- **WHEN** the load service loads configuration
- **THEN** the charger is registered with `disabled_reason="missing_power_kw"`
- **AND** the planner's adapter excludes the charger from `KeplerConfig.ev_chargers`
- **AND** the solver does not create decision variables for the charger

#### Scenario: Valid derived power registers normally
- **GIVEN** a current charger with `max_current_a: 10` and 3 phases
- **WHEN** the load service loads configuration
- **THEN** the charger is registered without a `disabled_reason`
- **AND** no `EV_MISSING_POWER` HealthIssue is emitted for that charger

#### Scenario: Disabled-state charger is visible in UI
- **WHEN** the frontend fetches the load registry
- **THEN** a charger with `disabled_reason="missing_power_kw"` is included in the response
- **AND** the response field `disabled_reason` is set to `"missing_power_kw"` for that entry

#### Scenario: Fixing config re-enables charger without restart
- **GIVEN** a charger was registered with `disabled_reason="missing_power_kw"`
- **WHEN** the user sets valid amps and phases (or `rated_power_kw`) and the config is reloaded
- **THEN** the charger is re-registered without a `disabled_reason`
- **AND** the corresponding `EV_MISSING_POWER` HealthIssue is cleared
- **AND** the next planner run includes the charger in `KeplerConfig.ev_chargers`
