## ADDED Requirements

### Requirement: EV node SoC comes from per-charger data
The power-flow EV node SHALL derive SoC and plug state from the per-charger `ev_chargers` live data, not from a flat `ev_soc` field.

#### Scenario: Single charger with SoC
- **GIVEN** one charger, plugged in, with SoC 49%
- **WHEN** the power-flow card renders
- **THEN** the EV node SHALL show 49% without opening the popup

### Requirement: EV node shows connection and charging state
For a single configured charger the EV node SHALL show: a lightning icon and `SoC → target%` when charging (charger power above 0.1 kW), a plug icon and `SoC%` when plugged in but not charging, and an unplug icon with "away" in muted colour when not plugged in. The target SHALL be the active manual charge target if one exists, otherwise the charger's goal target; when neither exists only the SoC SHALL be shown. When SoC is unknown, "--%" SHALL be shown in place of the number.

#### Scenario: Charging with manual target
- **GIVEN** a manual charge to 80%, SoC 49%, charger drawing 7.2 kW
- **WHEN** the node renders
- **THEN** it SHALL show a lightning icon and "49% → 80%"

#### Scenario: Plugged and idle
- **GIVEN** plugged in, SoC 49%, 0 kW
- **WHEN** the node renders
- **THEN** it SHALL show a plug icon and "49%"

#### Scenario: Unplugged
- **GIVEN** the charger reports not plugged in
- **WHEN** the node renders
- **THEN** it SHALL show an unplug icon and "away" in muted colour

### Requirement: Multi-charger EV node aggregates
With more than one configured charger the EV node SHALL show summed power, the charging icon if any charger is charging (else plug if any is plugged in, else unplug), and the count of connected cars; per-car SoC and target SHALL remain in the popup.

#### Scenario: Two chargers, one charging
- **GIVEN** two chargers, one charging and one unplugged
- **WHEN** the node renders
- **THEN** it SHALL show a lightning icon and "1 connected"
