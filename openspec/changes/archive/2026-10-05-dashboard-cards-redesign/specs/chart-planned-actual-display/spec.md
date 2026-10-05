## MODIFIED Requirements

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

### Requirement: Keep-on slots render as an EV standby band

The main schedule chart SHALL render slots whose `ev_keep_on` dict contains any true flag — and whose planned `ev_charging_kw` is 0 — as an "EV standby" mark on the action strip, visually fainter than the EV charging marks. The mark SHALL NOT encode any power value (keep-on plans no energy). It SHALL have its own entry in the Overlays menu, and the slot info panel SHALL explain the semantics for such a slot ("EV switch held on"). Slots with genuinely planned EV power SHALL continue to render as normal EV charging marks regardless of keep-on flags.

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

## ADDED Requirements

### Requirement: Schedule chart has a clear visual hierarchy
The Schedule Overview chart SHALL draw price as a soft filled area, battery SoC as the strongest line, and PV and load as thin lines. Actions SHALL be marks on a strip under the plot. A legend SHALL state that a solid line is actual and a dashed line is plan. The plot SHALL span the full card width with no side scale labels. A "NOW" line with a small NOW label SHALL separate past from future, with the past faintly tinted. Hovering SHALL draw a guide on the slot shown in the info panel. A glow effect SHALL be used only in dark mode.

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

### Requirement: Schedule chart info panel replaces the floating tooltip
The chart SHALL show a fixed info panel above the plot instead of a floating tooltip. It SHALL show the slot under the pointer (desktop), the tapped slot (mobile), or the current slot when none is pinned, with a phase badge (Now, Past, Plan or Estimated), the slot time as a 24-hour range (never AM/PM) and the planned action text. By default the panel SHALL be one compact line with the slot's price, SoC, PV and load. A "Details" toggle SHALL expand it into grouped values (price with its spot and fee split when known, battery, solar and load, and actions), where a measured past value leads and the plan is shown beside it. The Details choice SHALL be remembered in `localStorage` and the chart SHALL work when storage is unavailable. At phone width the compact line SHALL wrap rather than overflow.

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
