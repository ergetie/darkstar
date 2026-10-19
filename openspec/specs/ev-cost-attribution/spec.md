# ev-cost-attribution Specification

## Purpose
Attribute recorded EV charging energy per slot to solar (bounded by the measured PV surplus) and grid (the remainder), to produce the EV's grid import cost and an informational solar-share figure.
## Requirements
### Requirement: EV energy is attributed to solar by measured PV surplus, grid is the remainder
For each recorded slot, the system SHALL split the slot's `ev_charging_kwh` into `ev_solar_kwh = min(ev_charging_kwh, pv_surplus_kwh)` and `ev_grid_kwh = ev_charging_kwh − ev_solar_kwh`, where `pv_surplus_kwh = max(0, pv_kwh − load_kwh − water_kwh)`. Both values SHALL be non-negative and SHALL sum to `ev_charging_kwh`.

#### Scenario: Null and zero PV inputs
- **WHEN** an input is null or `pv_kwh` is 0
- **THEN** null inputs are treated as 0
- **AND** `ev_solar_kwh` is 0 whenever `pv_kwh` is 0, regardless of `import_kwh`

#### Scenario: Battery charging not subtracted
- **WHEN** the PV surplus is computed
- **THEN** battery charging is not subtracted
- **AND** `ev_solar_kwh` is an upper bound on solar-sourced EV energy

#### Scenario: Night charging entirely from grid
- **WHEN** a slot has `ev_charging_kwh=1.5`, `pv_kwh=0` and `import_kwh=2.0`
- **THEN** `ev_grid_kwh` SHALL be 1.5 and `ev_solar_kwh` SHALL be 0

#### Scenario: Night slot where import is under-recorded
- **WHEN** a slot has `ev_charging_kwh=1.65`, `pv_kwh=0` and `import_kwh=1.04`
- **THEN** `ev_solar_kwh` SHALL be 0 and `ev_grid_kwh` SHALL be 1.65

#### Scenario: Midday charging partly from solar
- **WHEN** a slot has `ev_charging_kwh=1.5`, `pv_kwh=2.0`, `load_kwh=0.4` and `water_kwh=0`
- **THEN** `ev_solar_kwh` SHALL be 1.5 and `ev_grid_kwh` SHALL be 0

#### Scenario: Solar surplus smaller than EV energy
- **WHEN** a slot has `ev_charging_kwh=1.5`, `pv_kwh=1.0`, `load_kwh=0.4` and `water_kwh=0`
- **THEN** `ev_solar_kwh` SHALL be 0.6 and `ev_grid_kwh` SHALL be 0.9

#### Scenario: House load exceeds PV
- **WHEN** a slot has `ev_charging_kwh=1.0`, `pv_kwh=0.3`, `load_kwh=0.5` and `water_kwh=0`
- **THEN** `ev_solar_kwh` SHALL be 0 and `ev_grid_kwh` SHALL be 1.0

#### Scenario: No EV charging
- **WHEN** a slot has `ev_charging_kwh=0`
- **THEN** both attributed values SHALL be 0

### Requirement: EV cost is the grid import cost only
The EV cost of a slot SHALL be `min(ev_grid_kwh, import_kwh) × import_price_sek_kwh`, using the same price column as the existing import cost aggregate, so the period EV cost is a subset of `import_cost_sek`. Solar energy used by the EV SHALL NOT be given a monetary value. A null price SHALL count as 0, matching the existing aggregates.

#### Scenario: Mixed-source slot cost
- **WHEN** a slot has `ev_grid_kwh=0.9` and `import_kwh=1.2` at import price 2.00, and `ev_solar_kwh=0.6`
- **THEN** the slot's EV cost SHALL be 1.80 SEK

#### Scenario: Solar-only slot
- **WHEN** a slot has `ev_grid_kwh=0` and `ev_solar_kwh=2.0`
- **THEN** the slot's EV cost SHALL be 0 SEK

#### Scenario: Cost never exceeds the slot's import cost
- **WHEN** a slot has `ev_grid_kwh=1.65` and `import_kwh=1.04` at import price 2.00
- **THEN** the slot's EV cost SHALL be 2.08 SEK

### Requirement: Period EV solar share
For a period, the solar share SHALL be `Σ ev_solar_kwh / Σ ev_charging_kwh`, or null when `Σ ev_charging_kwh` is 0. It is informational only and does not affect the EV cost.

#### Scenario: Share over a day
- **WHEN** a day has 10 kWh of EV energy, 4 kWh of it attributed to solar
- **THEN** the solar share SHALL be 0.4

#### Scenario: No EV energy
- **WHEN** a period has no EV energy
- **THEN** the solar share SHALL be null
