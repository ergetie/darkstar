# Battery Cost Integrity

## Purpose

Ensures battery cycle cost remains a user-owned configuration parameter, not subject to automated tuning by the Reflex learning engine.

## Requirements

### Requirement: Battery cycle cost is owned solely by configuration

The battery cycle cost (`battery_economics.battery_cycle_cost_kwh`) SHALL be modifiable only by the user through configuration. The Reflex learning engine SHALL NOT read it for tuning, propose changes to it, or write it to `config.yaml`.

#### Scenario: Reflex run leaves cycle cost untouched
- **WHEN** a full Reflex run executes (regardless of realized arbitrage profit over the lookback window)
- **THEN** no proposed or applied change targets `battery_economics.battery_cycle_cost_kwh`
- **AND** the value in `config.yaml` is identical before and after the run

#### Scenario: ROI analyzer is no longer part of the run
- **WHEN** Reflex orchestrates its analyzers
- **THEN** the ROI analyzer is not invoked
- **AND** the remaining analyzers (safety, confidence, capacity) run unchanged

#### Scenario: Cycle cost only changes when the user edits config
- **WHEN** the user edits `battery_economics.battery_cycle_cost_kwh` in configuration
- **THEN** the new value is the value used everywhere downstream
- **AND** no automated process subsequently overwrites it

#### Scenario: Parameter absent from Reflex tuning maps
- **WHEN** Reflex's `BOUNDS` and `MAX_DAILY_CHANGE` maps are inspected
- **THEN** `battery_economics.battery_cycle_cost_kwh` does not appear in either

#### Scenario: ROI analyzer removed and capacity analyzer unaffected
- **WHEN** Reflex runs its analyzers
- **THEN** the realized-arbitrage ROI analyzer (`analyze_roi`) no longer exists
- **AND** battery capacity fade is still handled independently by the existing capacity analyzer, which targets `battery.capacity_kwh` and is unaffected by this change
