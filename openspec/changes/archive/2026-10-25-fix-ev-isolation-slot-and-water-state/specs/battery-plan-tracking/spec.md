## ADDED Requirements

### Requirement: EV source isolation always blocks battery discharge
While EV source isolation is active, the controller SHALL select `idle` (unless a charge or export branch applies) for every trigger and at any SoC relative to `soc_target`, and SHALL recognise the isolated slot even with no planned EV kW and no keep-on. Isolation keeps precedence over the hold margin; inverter profile idle actions are unchanged.

#### Scenario: Manual EV charge above the SoC target
- **GIVEN** an active manual EV charge, a slot with `ev_charging_kw` 0 and no keep-on, and live SoC above `soc_target`
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle`, not `self_consumption`

#### Scenario: Actual unplanned charging above the SoC target
- **GIVEN** measured EV power above 0.1 kW and no planned EV charging, and live SoC above `soc_target`
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle`

#### Scenario: Surplus-eligible slot above the SoC target
- **GIVEN** a slot with surplus-eligible EV kW and `ev_charging_kw` 0, and live SoC above `soc_target`
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle`

#### Scenario: Planned grid charge is not overridden
- **GIVEN** isolation is active and the slot plans grid charging below its target
- **WHEN** the executor evaluates the slot
- **THEN** the charge branch SHALL still apply

#### Scenario: Composes with the minimum-SoC discharge guard
- **GIVEN** isolation is active and the min-SoC guard latch is engaged
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle` and the isolation reason SHALL be kept; the guard SHALL NOT alter an already-idle isolated slot, and its latch SHALL keep updating from live SoC
