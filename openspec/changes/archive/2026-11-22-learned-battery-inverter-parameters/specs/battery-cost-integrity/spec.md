## MODIFIED Requirements

### Requirement: Battery cycle cost is owned solely by configuration

The battery cycle cost (`battery_economics.battery_cycle_cost_kwh`) SHALL be modifiable only by the user through configuration. No learning component (the removed Reflex engine or the learned-parameter service) SHALL read it for tuning, propose changes to it, store a learned replacement for it, or write it to `config.yaml`.

#### Scenario: Reflex run leaves cycle cost untouched
- **WHEN** a full learning run executes (regardless of realized arbitrage profit over the lookback window)
- **THEN** no proposed or applied change targets `battery_economics.battery_cycle_cost_kwh`
- **AND** the value in `config.yaml` is identical before and after the run

#### Scenario: ROI analyzer is no longer part of the run
- **WHEN** the learning service orchestrates its estimators
- **THEN** no realized-arbitrage ROI estimator is invoked

#### Scenario: Cycle cost only changes when the user edits config
- **WHEN** the user edits `battery_economics.battery_cycle_cost_kwh` in configuration
- **THEN** the new value is the value used everywhere downstream
- **AND** no automated process subsequently overwrites it

#### Scenario: Parameter absent from Reflex tuning maps
- **WHEN** the set of learned parameter keys is inspected
- **THEN** no key refers to `battery_economics.battery_cycle_cost_kwh`

#### Scenario: ROI analyzer removed and capacity analyzer unaffected
- **WHEN** the learning service runs
- **THEN** the realized-arbitrage ROI analyzer (`analyze_roi`) does not exist
- **AND** battery capacity is never changed by learning; capacity changes only raise a warning
