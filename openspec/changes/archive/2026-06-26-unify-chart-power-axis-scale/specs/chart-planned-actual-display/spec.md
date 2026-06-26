## ADDED Requirements

### Requirement: All main-chart power series share one power axis scale

The main ChartCard SHALL render all power series — every power bar (load, charge, discharge, export, water heating, water-heating boost, EV charging, excess-PV sink) AND the PV forecast line — against a single shared power axis maximum, so that an identical power value is drawn at an identical height regardless of which series it belongs to.

The shared power axis maximum SHALL be `max(gridMaxKw, inverterMaxKw, solarKwp)` and SHALL be applied consistently both when the chart is first created and when the scaling configuration changes at runtime.

#### Scenario: Bar and PV line at equal power render at equal height
- **WHEN** a power bar and the PV forecast line both represent the same power value (e.g. 4 kW) in the same chart
- **THEN** both SHALL be drawn at the same height, because both axes use the same maximum

#### Scenario: PV peak above grid/inverter limit does not clip
- **WHEN** the PV forecast for a slot exceeds `max(gridMaxKw, inverterMaxKw)` but is at or below `solarKwp`
- **THEN** the PV forecast line SHALL remain fully visible within the chart area, because the shared maximum includes `solarKwp`

#### Scenario: Shared maximum tracks the largest capacity
- **WHEN** the scaling configuration provides `gridMaxKw`, `inverterMaxKw`, and `solarKwp`
- **THEN** the power axes for bars and the PV line SHALL all use a maximum equal to the largest of those three values

#### Scenario: Runtime scaling change keeps all power axes in sync
- **WHEN** the scaling configuration changes after the chart has loaded real data
- **THEN** the bar axes and the PV line axis SHALL all be updated to the same recomputed `max(gridMaxKw, inverterMaxKw, solarKwp)` value
