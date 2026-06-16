# Battery Cost Integrity

## Purpose

Ensures battery cycle cost remains a user-owned configuration parameter, not subject to automated tuning by the Reflex learning engine.

## Requirements

### Requirement: Battery cycle cost is owned solely by configuration
The battery cycle cost (`battery_economics.battery_cycle_cost_kwh`) SHALL be modifiable only by the user through configuration. The Reflex learning engine SHALL NOT read this parameter for the purpose of tuning, SHALL NOT propose changes to it, and SHALL NOT write it to `config.yaml`. The parameter SHALL NOT appear in Reflex's `BOUNDS` or `MAX_DAILY_CHANGE` maps.

The realized-arbitrage ROI analyzer (`analyze_roi`) SHALL be removed from Reflex. Battery capacity fade SHALL continue to be handled independently by the existing capacity analyzer, which targets `battery.capacity_kwh` and is unaffected by this change.

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
