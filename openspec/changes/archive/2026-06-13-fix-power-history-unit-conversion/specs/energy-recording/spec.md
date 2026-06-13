## ADDED Requirements

### Requirement: Unit Propagation in Power History Integration

The `get_energy_from_power_history` function SHALL propagate the `unit_of_measurement` from the first HA history state entry to all subsequent entries that lack attributes, and SHALL apply the resolved unit when converting each state's power value to kilowatts. The HA history API only includes attributes on the first entry in a response series — the function MUST NOT rely on every state entry having its own `unit_of_measurement`. Power values SHALL be converted to kW as: `"W"` divided by 1000, `"MW"` multiplied by 1000, and `"kW"` (or any other / absent unit) used as-is.

#### Scenario: HA history returns the unit only on the first entry

- **WHEN** the first state entry has `attributes: {"unit_of_measurement": "W"}` with value `3164` and the subsequent entries have `attributes: {}` with values `3124`, `3147`, and `0`
- **THEN** the function SHALL apply the `"W"` unit to ALL entries
- **AND** every value SHALL be divided by 1000 before integration (3.164 kW, 3.124 kW, 3.147 kW, 0 kW)
- **AND** the integrated slot energy SHALL be on the order of ~0.78 kWh, not ~780 kWh

#### Scenario: Subsequent entry reports watts without a unit

- **WHEN** the first state carries `unit_of_measurement: "W"` and a later state has no `unit_of_measurement`
- **THEN** the later state's value SHALL be treated as watts and divided by 1000
- **AND** the value SHALL NOT be treated as kilowatts

#### Scenario: No state entry has a unit attribute

- **WHEN** no state entry in the series carries a `unit_of_measurement`
- **THEN** the function SHALL treat all power values as already being in kW
- **AND** SHALL integrate them without dividing or multiplying

#### Scenario: Unit changes mid-series

- **WHEN** a later state entry introduces a different `unit_of_measurement` (e.g. sensor reconfigured from `"W"` to `"kW"`)
- **THEN** the function SHALL adopt the new unit from that entry onward
- **AND** SHALL keep applying the previous unit to the entries before the change

#### Scenario: Water-heater and EV-charger energy use the same path

- **WHEN** the recorder computes `water_kwh` for a water heater or `ev_charging_kwh` for an EV charger from a power sensor via `get_energy_from_power_history`
- **THEN** both SHALL benefit from the same first-state unit propagation
- **AND** a heater drawing ~3 kW for a full 15-minute slot SHALL record ~0.75 kWh rather than a spike that the validation guard zeroes
