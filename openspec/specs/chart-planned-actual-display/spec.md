## Purpose

Defines how the main schedule chart displays planned versus actual values for power, SoC and action series, including shared axis scaling, EV standby marks, the info panel and visual hierarchy.

## Requirements
### Requirement: Main chart displays planned values for all slots

ChartCard SHALL display planned/forecasted values for ALL time slots, both historical (before NOW) and future (after NOW), so users can see what was planned across the entire 48-hour window. Planned battery, export, water heating, EV and excess-PV actions SHALL be shown as marks on an action strip under the plot; planned SoC, PV and load SHALL be dashed lines.

#### Scenario: Historical slot shows planned charge value
- **WHEN** a slot is historical (before NOW marker) AND has both `battery_charge_kw` (planned) and `actual_charge_kw` values
- **THEN** the action strip SHALL mark charging for that slot based on the measured value
- **AND** the slot info panel SHALL show the measured charge with `battery_charge_kw` as the planned value beside it

#### Scenario: Future slot shows planned charge value
- **WHEN** a slot is future (after NOW marker) AND has `battery_charge_kw` value
- **THEN** the action strip SHALL mark charging for that slot
- **AND** no actual value is shown (no actual data exists yet)

#### Scenario: Slot without planned value
- **WHEN** a slot has no `battery_charge_kw` or `charge_kw` value
- **THEN** no charge mark SHALL be drawn for that slot

### Requirement: Main chart displays forecasted PV for all slots

ChartCard SHALL display PV forecast values in a thin dashed line with a soft gradient fill for ALL time slots. Actual PV generation SHALL be drawn as a solid line in the same colour for historical slots only.

#### Scenario: Historical slot shows PV forecast with actual line
- **WHEN** a slot is historical AND has both `pv_forecast_kwh` and `actual_pv_kwh` values
- **THEN** the dashed PV line SHALL display `pv_forecast_kwh` converted to kW
- **AND** the solid actual PV line SHALL display `actual_pv_kwh` converted to kW

#### Scenario: Future slot shows PV forecast only
- **WHEN** a slot is future AND has `pv_forecast_kwh` value
- **THEN** the dashed PV line SHALL display `pv_forecast_kwh` converted to kW
- **AND** no actual PV line is shown

### Requirement: Main chart displays forecasted load for all slots

ChartCard SHALL display load forecast values in a thin dashed line for ALL time slots. Actual load SHALL be drawn as a solid line in the same colour for historical slots only.

#### Scenario: Historical slot shows load forecast with actual line
- **WHEN** a slot is historical AND has both `load_forecast_kwh` and `actual_load_kwh` values
- **THEN** the dashed load line SHALL display `load_forecast_kwh` converted to kW
- **AND** the solid actual load line SHALL display `actual_load_kwh` converted to kW

### Requirement: All metrics follow consistent planned vs actual display pattern

ChartCard SHALL apply the same planned/actual logic across all energy metrics: before NOW the measured value leads (solid line or strip mark) with the plan as the dashed line or planned value beside it; after NOW only the plan is shown. A stray measurement after NOW SHALL NOT be drawn.

#### Scenario: Discharge metric follows pattern
- **WHEN** viewing discharge data
- **THEN** the strip SHALL mark planned discharge from `battery_discharge_kw`
- **AND** for historical slots a measured `actual_discharge_kw` SHALL take the place of the plan

#### Scenario: Water heating metric follows pattern
- **WHEN** viewing water heating data
- **THEN** the strip SHALL mark planned heating from `water_heating_kw`
- **AND** for historical slots a measured `actual_water_kw` SHALL take the place of the plan

#### Scenario: EV charging metric follows pattern
- **WHEN** viewing EV charging data
- **THEN** the strip SHALL mark planned charging from `ev_charging_kw`
- **AND** for historical slots a measured `actual_ev_charging_kw` SHALL take the place of the plan

#### Scenario: Export metric follows pattern
- **WHEN** viewing export data
- **THEN** the strip SHALL mark planned export from `export_kwh`
- **AND** for historical slots a measured `actual_export_kw` SHALL take the place of the plan

#### Scenario: Measurement after NOW is ignored
- **WHEN** a measured value exists for a slot after the NOW slot
- **THEN** it is not drawn as an actual line

### Requirement: Planned values sourced from slot_plans database

The backend SHALL provide planned values from the `slot_plans` table for all historical slots via the `battery_charge_kw`, `battery_discharge_kw`, `water_heating_kw`, `ev_charging_kw`, and `soc_target_percent` fields in the schedule API response. Energy-to-power conversion SHALL use each row's real slot duration from `slot_plans.slot_end`. Rows without a valid `slot_end` SHALL be treated as 15-minute slots.

#### Scenario: Backend provides planned values for historical slots
- **WHEN** the schedule API returns historical slot data
- **THEN** the response SHALL include `battery_charge_kw` from `slot_plans.planned_charge_kwh`
- **AND** the response SHALL include `battery_discharge_kw` from `slot_plans.planned_discharge_kwh`
- **AND** the response SHALL include `water_heating_kw` from `slot_plans.planned_water_heating_kwh`
- **AND** the response SHALL include `ev_charging_kw` from `slot_plans.planned_ev_charging_kwh` when that value is not NULL

#### Scenario: Planned EV survives a replan
- **WHEN** a slot had planned EV charging, the slot has passed, and the planner has replanned (including after the EV goal is cleared)
- **THEN** the schedule API SHALL still return that slot's planned `ev_charging_kw`

#### Scenario: Rows from before the migration
- **WHEN** a historical slot's `planned_ev_charging_kwh` is NULL
- **THEN** the API SHALL NOT fabricate a planned EV value of zero from the database

#### Scenario: 60-minute slot
- **WHEN** a `slot_plans` row has `planned_ev_charging_kwh=11.0` and a `slot_end` one hour after `slot_start`
- **THEN** the API SHALL return `ev_charging_kw` 11.0

#### Scenario: Row without slot_end
- **WHEN** a `slot_plans` row has `planned_water_heating_kwh=0.5` and `slot_end` NULL
- **THEN** the API SHALL return `water_heating_kw` 2.0

### Requirement: slot_plans stores planned EV charging energy
The `slot_plans` table SHALL have a nullable `planned_ev_charging_kwh` column, added by an Alembic migration that runs on startup for every install. `store_plan` SHALL persist the aggregate planned EV energy for each slot it writes, converting from kW with the slot's real duration.

#### Scenario: Migration on an existing database
- **WHEN** an install with existing `slot_plans` rows starts with the new version
- **THEN** the column SHALL be added, existing rows SHALL have NULL, and no other data SHALL change

#### Scenario: Plan stored
- **WHEN** a plan with `ev_charging_kw=11.0` for a 15-minute slot is stored
- **THEN** that slot's `planned_ev_charging_kwh` SHALL be 2.75

#### Scenario: Plan stored with 30-minute slots
- **WHEN** a plan with `ev_charging_kw=11.0` and `water_heating_kw=3.0` for a 30-minute slot is stored
- **THEN** that slot's `planned_ev_charging_kwh` SHALL be 5.5 and `planned_water_heating_kwh` SHALL be 1.5

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

The main ChartCard SHALL render all power series, every power bar and the PV forecast line, against a single shared power axis maximum so an identical power value is drawn at an identical height regardless of series.

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

#### Scenario: Series covered by the shared axis
- **WHEN** the chart renders load, charge, discharge, export, water heating, water-heating boost, EV charging and excess-PV sink bars together with the PV forecast line
- **THEN** all of them use the one shared power axis maximum

#### Scenario: Shared maximum definition
- **WHEN** the shared power axis maximum is computed
- **THEN** it is `max(gridMaxKw, inverterMaxKw, solarKwp)`
- **AND** it is applied both when the chart is first created and when the scaling configuration changes at runtime

### Requirement: Keep-on slots render as an EV standby band

The main schedule chart SHALL render slots whose `ev_keep_on` dict contains any true flag, and whose planned `ev_charging_kw` is 0, as an "EV standby" mark on the action strip, visually fainter than EV charging marks and encoding no power value.

#### Scenario: Keep-on slot renders standby mark, no charging mark
- **WHEN** a schedule slot has `ev_keep_on = {"ev1": true}` and `ev_charging_kw` = 0
- **THEN** the chart SHALL render the EV standby mark for that slot
- **AND** no EV charging mark SHALL be drawn for that slot

#### Scenario: Standby mark carries explanation
- **WHEN** the user hovers or taps a keep-on slot
- **THEN** the info panel SHALL show "EV switch held on" for that slot
- **AND** an "EV Standby" entry SHALL be present in the Overlays menu

#### Scenario: Planned charging takes precedence over the standby mark
- **WHEN** a slot has both planned EV power (`ev_charging_kw > 0`) and a keep-on flag
- **THEN** the normal EV charging mark SHALL be rendered for that slot

#### Scenario: Schedules without keep-on data render unchanged
- **WHEN** a schedule slot has no `ev_keep_on` field
- **THEN** the chart SHALL render no standby mark

#### Scenario: Standby mark controls and explanation
- **WHEN** an EV standby mark is rendered
- **THEN** it has its own entry in the Overlays menu
- **AND** the slot info panel explains the semantics for such a slot ("EV switch held on")

#### Scenario: Genuine planned EV power
- **WHEN** a slot has genuinely planned EV power
- **THEN** it renders as a normal EV charging mark regardless of keep-on flags

### Requirement: slot_plans stores each slot's end
The `slot_plans` table SHALL have a nullable `slot_end` column, added by an idempotent Alembic migration that runs on startup. `store_plan` SHALL write each slot's end, taken from the plan's `end_time`, in the same local ISO format as `slot_start`, and SHALL update it on upsert. A plan row whose end is missing or not after its start SHALL be stored with `slot_end` NULL, converted as a 15-minute slot, and logged as a warning.

#### Scenario: Migration on an existing database
- **WHEN** an install with existing `slot_plans` rows starts with the new version
- **THEN** `slot_end` SHALL be added, existing rows SHALL have NULL, and no other data SHALL change

#### Scenario: End stored
- **WHEN** a plan slot starting 10:00 and ending 10:15 is stored
- **THEN** that row's `slot_end` SHALL be 10:15 local time with offset

#### Scenario: Invalid end
- **WHEN** a plan row has `end_time` equal to its `start_time`
- **THEN** `slot_end` SHALL be NULL, planned kWh SHALL use a 15-minute duration, and a warning SHALL be logged

### Requirement: Observed history uses the real slot duration
The schedule API SHALL convert observed water energy (`slot_observations.water_kwh`) to `actual_water_kw` using each observation's duration from `slot_observations.slot_end`. Rows without a valid `slot_end` SHALL be treated as 15-minute slots.

#### Scenario: 30-minute observation
- **WHEN** an observation has `water_kwh=1.5` and a `slot_end` 30 minutes after `slot_start`
- **THEN** the API SHALL return `actual_water_kw` 3.0

### Requirement: Schedule chart has a clear visual hierarchy

The Schedule Overview chart SHALL draw price as a soft filled area, battery SoC as the strongest line, PV and load as thin lines, and actions as marks on a strip under the plot, with a legend stating that solid is actual and dashed is plan.

#### Scenario: Legend explains line styles
- **WHEN** the chart renders
- **THEN** the legend shows "actual" with a solid swatch and "plan" with a dashed swatch

#### Scenario: Plot uses the full width
- **WHEN** the chart renders on any viewport
- **THEN** no scale labels are drawn beside the plot and the plot spans the card width

#### Scenario: NOW marker
- **WHEN** the visible range contains the current slot
- **THEN** a solid line marks the present with a NOW label, and earlier slots are tinted

#### Scenario: Glow only in dark mode
- **WHEN** the theme is light
- **THEN** no line glow is drawn

#### Scenario: Plot layout and NOW line
- **WHEN** the chart is rendered
- **THEN** the plot spans the full card width with no side scale labels
- **AND** a "NOW" line with a small NOW label separates past from future, with the past faintly tinted

#### Scenario: Hover guide and glow
- **WHEN** the user hovers a slot
- **THEN** a guide is drawn on the slot shown in the info panel
- **AND** a glow effect is used only in dark mode

### Requirement: Schedule chart info panel replaces the floating tooltip

The chart SHALL show a fixed info panel above the plot instead of a floating tooltip, showing the slot under the pointer (desktop), the tapped slot (mobile), or the current slot when none is pinned. By default the panel SHALL be one compact line with the slot's price, SoC, PV and load.

#### Scenario: Compact by default
- **WHEN** a new user opens the dashboard
- **THEN** the panel shows one line with badge, time and the slot's key values

#### Scenario: Details expanded and remembered
- **WHEN** the user turns Details on and reloads the page
- **THEN** the panel opens with grouped values

#### Scenario: Past slot shows measured value with plan
- **WHEN** the panel shows a slot before NOW with a measured value
- **THEN** the measured value is shown with the planned value beside it

#### Scenario: Time shown on 24-hour clock
- **WHEN** the panel shows a slot starting at 14:15 with 15-minute slots
- **THEN** the time reads "14:15–14:30"

#### Scenario: Header content
- **WHEN** the panel is shown
- **THEN** it has a phase badge (Now, Past, Plan or Estimated), the slot time as a 24-hour range (never AM/PM) and the planned action text

#### Scenario: Details toggle
- **WHEN** the user toggles "Details"
- **THEN** the panel expands into grouped values: price with its spot and fee split when known, battery, solar and load, and actions
- **AND** a measured past value leads with the plan shown beside it
- **AND** the choice is remembered in `localStorage`, and the chart works when storage is unavailable

#### Scenario: Phone width
- **WHEN** the viewport is phone width
- **THEN** the compact line wraps rather than overflows

### Requirement: Schedule chart marks estimated prices
Slots whose `price_source` is `"forecast"` SHALL be treated as having estimated prices. The chart SHALL draw their price area hatched and lighter, tint a band over those slots with an "ESTIMATED PRICES" label, show an "est. price" entry in the legend, and show an "Estimated" badge in the info panel for such slots that are not in the past. When no slot is estimated, none of these SHALL appear.

#### Scenario: Slots beyond the published horizon
- **WHEN** tomorrow's prices are not published and tomorrow's slots have `price_source` "forecast"
- **THEN** tomorrow's price area is hatched, labelled "ESTIMATED PRICES", and the legend shows "est. price"

#### Scenario: Estimated badge
- **WHEN** the user hovers a future slot with `price_source` "forecast"
- **THEN** the panel badge reads "Estimated"

#### Scenario: All prices published
- **WHEN** every slot has `price_source` "nordpool"
- **THEN** no hatch, band, label or legend entry is shown

### Requirement: Schedule chart colours follow the theme
Chart colours (lines, grid, tint, glow, marks) SHALL come from design-system tokens resolved when drawing, so the chart reads in both light and dark themes. When the theme is switched, the chart SHALL repaint with the new colours without reloading.

#### Scenario: Theme switch repaints the chart
- **WHEN** the user switches between light and dark theme
- **THEN** the chart is redrawn with the new theme's colours

### Requirement: Overlay preferences are reset once for the new chart
Because the Overlays menu now controls strip marks and lines rather than bars, the stored overlay preferences SHALL carry a new storage version, and users with preferences saved under an older version SHALL have them reset to the defaults once.

#### Scenario: Old saved overlay choices
- **WHEN** a user with overlay preferences saved under the previous version opens the dashboard
- **THEN** the overlays are reset to the defaults and saved under the new version
