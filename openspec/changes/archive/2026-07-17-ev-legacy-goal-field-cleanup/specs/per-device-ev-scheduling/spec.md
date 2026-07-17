# Delta: per-device-ev-scheduling

## MODIFIED Requirements

### Requirement: Per-device EV config structure
Each entry in `ev_chargers[]` SHALL support the following per-device fields: `switch_entity` (string, HA entity ID), `replan_on_plugin` (boolean, default true), `replan_on_unplug` (boolean, default false), plus hardware facts (`sensor`, `soc_sensor`, `plug_sensor`, `battery_capacity_kwh`, `max_power_kw`, `type`, current/phase entities) and the optional HA goal entities (`ha_ready_by_entity`, `ha_target_soc_entity`).

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
