# ev-schedule-api Specification

## Purpose
TBD - created by archiving change price-forecasting-module-5. Update Purpose after archive.
## Requirements
### Requirement: Write endpoint sets a charger's charging goal
The API SHALL expose `POST /api/ev/chargers/{id}/schedule` accepting a JSON body with `target_soc_percent` (int 0–100, or null to clear), `ready_by` (`HH:MM`), `repeat` (`daily`|`weekdays`|`weekends`|`every_n_days`|`none`), optional `ready_by_date` (ISO date, required when `repeat: none`), and optional `keep_on_after_target` (bool). **No `charge_priority` parameter** — surplus ordering is owned by `excess_pv.priority[]`, not per-charger. The endpoint SHALL validate inputs and persist the goal to `data/ev_multi_day_state.json`.

#### Scenario: Set a daily goal
- **WHEN** `POST /api/ev/chargers/ev_charger_1/schedule` is called with `{ "target_soc_percent": 80, "ready_by": "07:00", "repeat": "daily" }`
- **THEN** the endpoint SHALL persist that goal (with `source: "api"`) for `ev_charger_1`
- **AND** SHALL return the updated charger state with HTTP 200

#### Scenario: Set a one-off goal for a specific date
- **WHEN** the body has `repeat: "none"`, `ready_by_date: "2026-06-12"`, `ready_by: "07:00"`, `target_soc_percent: 100`
- **THEN** the goal SHALL be persisted with that date

#### Scenario: Clear the goal
- **WHEN** the body has `target_soc_percent: null`
- **THEN** the endpoint SHALL clear the active goal for that charger (the charger reverts to soaking surplus PV only)

#### Scenario: Invalid charger ID
- **WHEN** `{id}` does not match a configured charger
- **THEN** the endpoint SHALL return HTTP 404 "Charger not found"

#### Scenario: Target out of range
- **WHEN** `target_soc_percent: 150`
- **THEN** the endpoint SHALL return HTTP 422 "target_soc_percent must be between 0 and 100"

#### Scenario: Repeat none without a date
- **WHEN** `repeat: "none"` and `ready_by_date` is absent
- **THEN** the endpoint SHALL return HTTP 422 "ready_by_date is required when repeat is none"

### Requirement: Write endpoint triggers HA sync when configured
When a charger has `ha_ready_by_entity` and/or `ha_target_soc_entity` configured, the write endpoint SHALL push the corresponding values to those HA entities after persisting to the state file. HA sync failures SHALL NOT cause the endpoint to fail.

#### Scenario: Goal written to HA entities
- **WHEN** a goal is set for a charger with `ha_ready_by_entity` and `ha_target_soc_entity` configured
- **THEN** the endpoint SHALL call `input_datetime.set_datetime` with the resolved ready-by datetime
- **AND** SHALL call `input_number.set_value` with the target SoC percentage
- **AND** the HTTP response SHALL not be delayed by the HA calls

#### Scenario: HA entity write fails
- **WHEN** the HA entities are unreachable
- **THEN** the state file SHALL still be updated and the endpoint SHALL return HTTP 200
- **AND** the failure SHALL be logged as a warning

### Requirement: State file is source of truth for the user-set goal
`data/ev_multi_day_state.json` SHALL be the primary source of truth for the user-set goal. The pipeline SHALL read the goal from the state file and fall back to `config.yaml` goal fields only when the state file has no goal for a charger.

#### Scenario: State file overrides config
- **WHEN** config has `target_soc_percent: 70` and the state file has `target_soc_percent: 90` for the same charger
- **THEN** the pipeline SHALL use the state file value 90

#### Scenario: State file missing or corrupt
- **WHEN** the state file does not exist or cannot be parsed
- **THEN** the pipeline SHALL fall back to config goal fields
- **AND** the API SHALL recreate the state file on next write

### Requirement: Write endpoint returns the updated charger state
After persisting, the endpoint SHALL return the affected charger's state in the same shape as one entry from `GET /api/ev/chargers`.

#### Scenario: Response includes goal and progress
- **WHEN** a goal is set successfully
- **THEN** the response SHALL include `id`, the goal fields, the resolved `deadline`, and progress fields (which MAY be null until the next planner run)
