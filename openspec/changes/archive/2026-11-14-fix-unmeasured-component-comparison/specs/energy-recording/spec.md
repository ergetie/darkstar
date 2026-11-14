## ADDED Requirements

### Requirement: Unavailable device sensors are recorded as unknown, never as fake zero
For every device component (EV per charger, water heater per heater, and any other device component), the recorder SHALL treat a sensor with neither integrated history nor a live snapshot as unavailable. The per-device source SHALL be `unavailable` and the aggregate component method SHALL be `unknown` in `quality_flags.recording.components`. The numeric column SHALL keep 0 as placeholder with no schema change. A live snapshot that really exists SHALL remain method `snapshot`.

#### Scenario: EV history and snapshot both missing
- **WHEN** the EV sensor has no usable history and no live snapshot for a slot
- **THEN** the `ev` component method is `unknown`, the charger source is `unavailable`, and `ev_charging_kwh` is the 0 placeholder
- **AND** the `load` component is not tagged `mixed` because of it

#### Scenario: EV snapshot exists
- **WHEN** the EV sensor has no history but a live snapshot of 3 kW exists
- **THEN** the `ev` component method is `snapshot` and the energy is 0.75 kWh

#### Scenario: One of two chargers unavailable
- **WHEN** charger A is measured and charger B is unavailable
- **THEN** the aggregate `ev` method is `unknown` and charger A keeps its per-charger energy

#### Scenario: Water behaviour unchanged
- **WHEN** a water heater sensor is unavailable
- **THEN** the recorded result is the same as before this change
