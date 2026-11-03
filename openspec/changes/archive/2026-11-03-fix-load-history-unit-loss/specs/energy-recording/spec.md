## ADDED Requirements

### Requirement: Power History Unit Integrity
When parsing Home Assistant history for a power sensor, the system SHALL learn the unit of measurement from any state that carries it, including `unavailable`/`unknown` states, and apply it to all numeric states of the series that lack one. If no state in the series carries a unit, the system SHALL use the entity's current unit of measurement, for every consumer of power history.

#### Scenario: Series starts with a non-numeric state carrying the unit
- **WHEN** a history chunk for a W sensor starts with an `unavailable` state carrying `unit_of_measurement: W`, followed by unitless numeric states
- **THEN** the numeric states SHALL be interpreted as W and integrated to the correct kWh

#### Scenario: No unit in the series
- **WHEN** no state of a series carries a unit and the entity's current state reports `W`
- **THEN** the series SHALL be interpreted as W

#### Scenario: Unit unknown everywhere
- **WHEN** neither the series nor the current entity state provides a unit
- **THEN** the series SHALL be interpreted as kW and a warning naming the entity SHALL be logged once

#### Scenario: Slot energy after an outage
- **WHEN** the recorder integrates a 15-minute slot whose history starts with an `unavailable` state of a W sensor
- **THEN** the slot energy SHALL be computed in kWh from W, not inflated 1000x

#### Scenario: Normal series unchanged
- **WHEN** the first state of a series is numeric and carries its unit
- **THEN** parsing and integration SHALL give the same result as before

### Requirement: Unknown Power Unit Warning
If neither the history series nor the entity's current state provides a unit, the system SHALL assume kW and log a warning naming the entity, at most once per entity per process.

#### Scenario: Warning not repeated
- **WHEN** the same unitless entity is parsed repeatedly
- **THEN** the warning SHALL be logged only once

### Requirement: Explicit History Request Semantics
The history request SHALL express its intent in terms HA actually honours: all state changes are requested (`significant_changes_only` sent as "0"), and the reduced-payload response form is used deliberately rather than by accident.

#### Scenario: Request parameters
- **WHEN** power history is requested
- **THEN** `significant_changes_only` SHALL be "0" and no boolean `False` SHALL be sent for either flag
