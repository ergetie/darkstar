# ev-cost-attribution Specification

## Purpose
Attribute recorded EV charging energy per slot to grid first and then solar, to produce the EV's grid import cost and an informational solar-share figure.
## Requirements
### Requirement: EV energy is attributed to grid first, then solar, per slot
For each recorded slot, the system SHALL split the slot's `ev_charging_kwh` into:
- `ev_grid_kwh = min(ev_charging_kwh, import_kwh)`
- `ev_solar_kwh = ev_charging_kwh − ev_grid_kwh`

Both values SHALL be non-negative. Null inputs SHALL be treated as 0.

#### Scenario: Night charging entirely from grid
- **WHEN** a slot has `ev_charging_kwh=1.5` and `import_kwh=2.0`
- **THEN** `ev_grid_kwh` SHALL be 1.5 and `ev_solar_kwh` SHALL be 0

#### Scenario: Midday charging partly from solar
- **WHEN** a slot has `ev_charging_kwh=1.5` and `import_kwh=0.4`
- **THEN** `ev_grid_kwh` SHALL be 0.4 and `ev_solar_kwh` SHALL be 1.1

#### Scenario: No EV charging
- **WHEN** a slot has `ev_charging_kwh=0`
- **THEN** both attributed values SHALL be 0

### Requirement: EV cost is the grid import cost only
The EV cost of a slot SHALL be `ev_grid_kwh × import_price_sek_kwh`, using the same price column as the existing import cost aggregate, so the period EV cost is a subset of `import_cost_sek`. Solar energy used by the EV SHALL NOT be given a monetary value. A null price SHALL count as 0, matching the existing aggregates.

#### Scenario: Mixed-source slot cost
- **WHEN** a slot has `ev_grid_kwh=0.4` at import price 2.00 and `ev_solar_kwh=1.1` at export price 0.50
- **THEN** the slot's EV cost SHALL be 0.80 SEK

#### Scenario: Solar-only slot
- **WHEN** a slot has `ev_grid_kwh=0` and `ev_solar_kwh=2.0`
- **THEN** the slot's EV cost SHALL be 0 SEK

### Requirement: Period EV solar share
For a period, the solar share SHALL be `Σ ev_solar_kwh / Σ ev_charging_kwh`, or null when `Σ ev_charging_kwh` is 0. It is informational only and does not affect the EV cost.

#### Scenario: Share over a day
- **WHEN** a day has 10 kWh of EV energy, 4 kWh of it attributed to solar
- **THEN** the solar share SHALL be 0.4

#### Scenario: No EV energy
- **WHEN** a period has no EV energy
- **THEN** the solar share SHALL be null
