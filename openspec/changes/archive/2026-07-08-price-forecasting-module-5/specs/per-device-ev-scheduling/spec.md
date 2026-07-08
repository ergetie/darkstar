## ADDED Requirements

### Requirement: Per-device EV config supports optional HA goal entities
Each entry in `ev_chargers[]` SHALL support two optional fields: `ha_ready_by_entity` (string, HA `input_datetime` entity ID) and `ha_target_soc_entity` (string, HA `input_number` entity ID). When configured, the backend SHALL sync the charger's ready-by time and target SoC bidirectionally with those entities, and HA values SHALL take priority over the dashboard value when set. (The core goal fields — `target_soc_percent`, `ready_by`, `repeat`, `keep_on_after_target` — are defined by the `per-device-ev-scheduling` change in Module 4. **No `charge_priority`** — surplus ordering is owned by `excess_pv.priority[]`.)

#### Scenario: Charger with HA goal entities configured
- **WHEN** a charger has `ha_ready_by_entity: "input_datetime.ev_ready_by"` and `ha_target_soc_entity: "input_number.ev_target_soc"`
- **THEN** the config loader SHALL store both entity IDs
- **AND** the backend SHALL subscribe to state changes for both

#### Scenario: Charger without HA goal entities
- **WHEN** a charger has neither field (or they are empty/null)
- **THEN** no HA subscription SHALL be created for the goal
- **AND** the charger SHALL operate using the dashboard-managed goal only

#### Scenario: HA value overrides the dashboard value
- **WHEN** both an HA goal entity and a dashboard-set value exist for the same field
- **THEN** the HA value SHALL take precedence (mirroring the vacation-mode override)
