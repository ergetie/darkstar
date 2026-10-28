## REMOVED Requirements

### Requirement: Boost-cancellation notification is delivered
**Reason**: Boost is no longer cancelled based on battery SoC, so the cancellation and its notification no longer exist.
**Migration**: None. Users cancel a boost only explicitly via the UI/API.

## ADDED Requirements

### Requirement: Manual water boost is never cancelled or refused based on battery SoC

While a manual water boost is active, the executor SHALL apply the boost (FORCE_HEAT override) on every tick regardless of battery SoC, including at or below `battery.min_soc_percent`. The executor SHALL NOT clear the boost, log a cancellation, or send a cancellation notification because of SoC.

#### Scenario: Boost at low SoC stays active

- **WHEN** a manual water boost is active and battery SoC (5%) is below `min_soc_percent` (10%)
- **THEN** the boost remains active after the tick
- **AND** the executor produces a FORCE_HEAT override with the boost temperature
- **AND** no cancellation notification is sent

### Requirement: Manual water boost runs idle with the plan slot soc_target

The boost override SHALL run in the `idle` mode intent so battery discharge is blocked, and its `soc_target` SHALL equal the current plan slot's `soc_target`, the value EV isolation and hold slots use in idle. Only when no plan slot exists SHALL it be the live SoC, at least `battery.min_soc_percent`.

#### Scenario: Boost never discharges the battery

- **WHEN** a manual water boost override is applied at any SoC
- **THEN** the mode intent is `idle` with zero discharge value and no discharge write
- **AND** the override `soc_target` equals the current plan slot's `soc_target`

#### Scenario: Boost without a plan slot

- **WHEN** a manual water boost is active and no plan slot exists
- **THEN** the override `soc_target` equals the live SoC rounded, but not below `min_soc_percent`

#### Scenario: Boost with min-SoC guard latched

- **WHEN** the min-SoC discharge guard is latched and a manual boost is active
- **THEN** the boost is still applied and the battery stays blocked from discharging
