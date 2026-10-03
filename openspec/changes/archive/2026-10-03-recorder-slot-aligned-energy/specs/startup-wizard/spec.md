## MODIFIED Requirements

### Requirement: Core sensors step
The step SHALL collect `load_power`; `grid_power` or `grid_import_power`/`grid_export_power` per meter type; `battery_soc` and `battery_power` when battery; `pv_power` when solar; and an optional synthetic daily kWh saved to `input_sensors.synthetic_daily_load_kwh`. The step SHALL NOT collect cumulative energy counters or offer a choice between a counter and an estimate. Step completion SHALL depend only on the required power sensors, not on the synthetic value.

#### Scenario: Synthetic baseline saved
- **WHEN** the user enters 20 kWh/day in the optional estimated daily use field
- **THEN** `input_sensors.synthetic_daily_load_kwh` is saved as 20

#### Scenario: Step completes without synthetic value
- **WHEN** all required power sensors for the system are set and the synthetic field is empty
- **THEN** the step is complete

#### Scenario: No counter fields or suggestions
- **WHEN** the step is shown
- **THEN** no `total_*` field is displayed and no `total_*` role is requested from `/api/setup/suggestions`
