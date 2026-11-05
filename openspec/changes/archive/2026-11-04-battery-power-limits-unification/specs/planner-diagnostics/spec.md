## MODIFIED Requirements

### Requirement: Battery config preflight reads correct field names
The battery config preflight check (`check_battery_config()`) SHALL validate the battery charge and discharge limits of the active control unit as resolved in kW (Watts: `battery.max_charge_w` / `battery.max_discharge_w` divided by 1000; Amps: `battery.max_charge_a` / `battery.max_discharge_a` times nominal voltage divided by 1000). It SHALL NOT validate the inactive unit's fields and SHALL NOT reference `battery.max_charge_power_kw` or `battery.max_discharge_power_kw`. On failure the error details SHALL name the active field (for example `battery.max_charge_a`), the resolved kW value and the control unit.

#### Scenario: Valid battery config passes preflight
- **WHEN** the control unit is Watts, `battery.capacity_kwh = 29`, `max_charge_w = 5000`, `max_discharge_w = 5000`, `min_soc_percent = 12`, `max_soc_percent = 100`
- **THEN** `check_battery_config()` raises no error

#### Scenario: Valid Amps config passes with hidden Watts at zero
- **WHEN** the control unit is Amps, `max_charge_a = 100`, `max_discharge_a = 100`, `nominal_voltage_v = 48`, and `max_charge_w = 0`
- **THEN** `check_battery_config()` raises no error

#### Scenario: Zero watts triggers invalid config error
- **WHEN** the control unit is Watts and `battery.max_charge_w = 0`
- **THEN** `check_battery_config()` raises `CONFIG_INVALID` with field `battery.max_charge_w`

#### Scenario: Missing watts field defaults to zero and triggers error
- **WHEN** the control unit is Watts and `battery.max_charge_w` is absent
- **THEN** the field resolves to 0 and `check_battery_config()` raises `CONFIG_INVALID`

#### Scenario: Missing Amps field triggers error naming the Amps field
- **WHEN** the control unit is Amps and `battery.max_discharge_a` is absent
- **THEN** `check_battery_config()` raises `CONFIG_INVALID` with field `battery.max_discharge_a`

#### Scenario: Battery preflight checks
- **WHEN** `check_battery_config()` runs
- **THEN** it SHALL check `capacity_kwh > 0`, the resolved charge kW > 0, the resolved discharge kW > 0, and `min_soc_percent < max_soc_percent`
