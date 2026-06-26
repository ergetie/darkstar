## Purpose

TBD: Define the purpose of chart planned vs actual display capability.

## Requirements

### Requirement: Main chart displays planned values for all slots

ChartCard SHALL display planned/forecasted values in the main chart elements (bars and solid lines) for ALL time slots, both historical (before NOW) and future (after NOW). This enables users to see what was planned across the entire 48-hour window.

#### Scenario: Historical slot shows planned charge value
- **WHEN** a slot is historical (before NOW marker) AND has both `battery_charge_kw` (planned) and `actual_charge_kw` values
- **THEN** the main charge bar SHALL display `battery_charge_kw` (planned value)
- **AND** the dotted "Actual Charge" overlay line SHALL display `actual_charge_kw`

#### Scenario: Future slot shows planned charge value
- **WHEN** a slot is future (after NOW marker) AND has `battery_charge_kw` value
- **THEN** the main charge bar SHALL display `battery_charge_kw`
- **AND** no actual overlay is shown (no actual data exists yet)

#### Scenario: Slot without planned value
- **WHEN** a slot has no `battery_charge_kw` or `charge_kw` value
- **THEN** the main charge bar SHALL show nothing (null)
- **AND** the slot is visually empty in the chart

### Requirement: Main chart displays forecasted PV for all slots

ChartCard SHALL display PV forecast values in the solid yellow line for ALL time slots. Actual PV generation is shown only in the dotted overlay for historical slots.

#### Scenario: Historical slot shows PV forecast with actual overlay
- **WHEN** a slot is historical AND has both `pv_forecast_kwh` and `actual_pv_kwh` values
- **THEN** the solid PV line SHALL display `pv_forecast_kwh` converted to kW
- **AND** the dotted "Actual PV" overlay line SHALL display `actual_pv_kwh` converted to kW

#### Scenario: Future slot shows PV forecast only
- **WHEN** a slot is future AND has `pv_forecast_kwh` value
- **THEN** the solid PV line SHALL display `pv_forecast_kwh` converted to kW
- **AND** no actual PV overlay is shown

### Requirement: Main chart displays forecasted load for all slots

ChartCard SHALL display load forecast values in the solid blue line for ALL time slots. Actual load is shown only in the dotted overlay for historical slots.

#### Scenario: Historical slot shows load forecast with actual overlay
- **WHEN** a slot is historical AND has both `load_forecast_kwh` and `actual_load_kwh` values
- **THEN** the solid Load line SHALL display `load_forecast_kwh` converted to kW
- **AND** the dotted "Actual Load" overlay line SHALL display `actual_load_kwh` converted to kW

### Requirement: All metrics follow consistent planned vs actual display pattern

ChartCard SHALL apply the same planned/actual display logic consistently across all energy metrics.

#### Scenario: Discharge metric follows pattern
- **WHEN** viewing discharge data
- **THEN** main bars SHALL show `battery_discharge_kw` (planned)
- **AND** dotted overlay SHALL show `actual_discharge_kw` for historical slots

#### Scenario: Water heating metric follows pattern
- **WHEN** viewing water heating data
- **THEN** main bars SHALL show `water_heating_kw` (planned)
- **AND** dotted overlay SHALL show `actual_water_kw` for historical slots

#### Scenario: EV charging metric follows pattern
- **WHEN** viewing EV charging data
- **THEN** main bars SHALL show `ev_charging_kw` (planned)
- **AND** dotted overlay SHALL show `actual_ev_charging_kw` for historical slots

#### Scenario: Export metric follows pattern
- **WHEN** viewing export data
- **THEN** main bars SHALL show `export_kwh` (planned)
- **AND** dotted overlay SHALL show `actual_export_kw` for historical slots

### Requirement: Planned values sourced from slot_plans database

The backend SHALL provide planned values from the `slot_plans` table for all historical slots via the `battery_charge_kw`, `battery_discharge_kw`, `water_heating_kw`, and `soc_target_percent` fields in the schedule API response.

#### Scenario: Backend provides planned values for historical slots
- **WHEN** the schedule API returns historical slot data
- **THEN** the response SHALL include `battery_charge_kw` from `slot_plans.planned_charge_kwh`
- **AND** the response SHALL include `battery_discharge_kw` from `slot_plans.planned_discharge_kwh`
- **AND** the response SHALL include `water_heating_kw` from `slot_plans.planned_water_heating_kwh`

### Requirement: Chart lines use consistent smooth rendering style

ChartCard SHALL render all chart lines with a consistent smooth style using Chart.js tension parameter. Lines SHALL NOT use stepped rendering for power/energy values that represent continuous measurements.

#### Scenario: Actual PV line renders smoothly
- **WHEN** the Actual PV overlay line is displayed
- **THEN** the line SHALL use `tension: 0.4` for smooth Bezier curve rendering
- **AND** the line SHALL NOT use `stepped` property

#### Scenario: PV Forecast line renders smoothly
- **WHEN** the PV Forecast line is displayed
- **THEN** the line SHALL use `tension: 0.4` for smooth Bezier curve rendering
- **AND** the visual style SHALL match the Actual PV line

#### Scenario: Other power lines follow consistent style
- **WHEN** any power or energy line is rendered in the chart
- **THEN** the line SHALL use smooth rendering (`tension: 0.4`) unless a stepped display is semantically appropriate

### Requirement: Water heating boost bars visually differ from normal heating

The ChartCard SHALL render water heating boost bars with a lighter blue tint and enhanced glow effect, visually distinguishing them from normal water heating bars.

#### Scenario: Boost water bar renders with lighter tint
- **WHEN** a slot has water heating in boost mode
- **THEN** the water heating bar SHALL use `rgba(120, 200, 240, 0.30)` for background color
- **AND** the bar SHALL use `#78C8F0` for border color
- **AND** the bar shape (width, border radius) SHALL be identical to normal water heating bars

#### Scenario: Boost water bar renders with super glow
- **WHEN** a slot has water heating in boost mode
- **THEN** the bar SHALL render with `shadowBlur: 60` and `shadowColor` opacity at 0.6
- **AND** the glow SHALL be more prominent than the default water heating glow

#### Scenario: Normal water bar renders with existing style
- **WHEN** a slot has water heating in normal mode (not boost)
- **THEN** the water heating bar SHALL use the existing color scheme (`rgba(78, 168, 222, 0.25)`)
- **AND** the bar SHALL render with the existing default glow

### Requirement: Custom entity sink bar displayed in chart

The ChartCard SHALL render a new bar dataset for the custom entity sink, visible in slots where the entity is toggled on.

#### Scenario: Custom entity bar displayed during excess PV slot
- **WHEN** the schedule has a custom entity active in slot 14
- **THEN** a bar SHALL appear at slot 14 using color `rgba(255, 159, 64, 0.30)` / `#FF9F40`
- **AND** the bar SHALL have the same super glow as boost bars (`shadowBlur: 60`, opacity 0.6)
- **AND** the bar SHALL be toggleable from the Overlays menu

#### Scenario: Custom entity bar hidden toggleable from overlays
- **WHEN** the user opens the chart Overlays menu
- **THEN** an "Excess PV Sink" toggle SHALL appear
- **AND** toggling it off SHALL hide the custom entity sink bars
- **AND** toggling it on SHALL show them again

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
