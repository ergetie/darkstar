# Grid Financial Wear Display

## Purpose

UI display of battery wear cost in the Grid & Financial summary card, showing the true total cost of energy including battery degradation.
## Requirements
### Requirement: Grid & Financial card shows net including battery wear
The Grid & Financial card SHALL display a secondary line beneath the headline Net figure showing the net cost including battery wear, sourced from the endpoint's `net_cost_incl_wear_sek`. This secondary line SHALL be visually distinct (it "pops out") from the surrounding breakdown text so the user can read it at a glance. The headline Net figure SHALL continue to show `net_cost_sek` (real grid cash flow) and SHALL NOT change.

The secondary line SHALL follow the same sign and color convention as the headline (savings vs. cost), applied to the wear-inclusive value.

#### Scenario: Secondary net-incl-wear line is shown
- **WHEN** the card renders with period data available
- **THEN** the headline shows the pure-grid Net (`net_cost_sek`)
- **AND** a distinct secondary line below shows the net including battery wear (`net_cost_incl_wear_sek`)

#### Scenario: Headline Net is unchanged by this feature
- **WHEN** battery wear is non-zero for the period
- **THEN** the headline Net value matches `net_cost_sek` exactly (wear is not folded into it)

### Requirement: Grid & Financial card shows a Battery Wear breakdown row
The financial breakdown section of the card SHALL include a "Battery Wear" row showing `battery_wear_cost_sek` for the period, presented as a cost alongside the existing breakdown rows (Grid Import, Export Rev, Battery Charge, Self-Use Saved).

#### Scenario: Battery Wear row appears in the breakdown
- **WHEN** the breakdown section renders for a period with battery throughput
- **THEN** a "Battery Wear" row shows the `battery_wear_cost_sek` value
- **AND** it is presented consistently with the other breakdown rows

#### Scenario: Zero wear renders cleanly
- **WHEN** the period has no battery throughput
- **THEN** the "Battery Wear" row shows `0.00`

### Requirement: Grid & Financial card shows an EV sub-row under Grid Import
When an EV charger is configured (`system.has_ev_charger`), the card's breakdown section SHALL always include an indented "↳ of which EV" sub-row directly under "Grid Import", even when the period has no EV energy. It SHALL show `ev_cost_sek` (the EV's grid import cost only) as a cost, the total EV kWh, and the solar share as a percentage. When no EV charger is configured, the sub-row SHALL be hidden unless the period has recorded EV energy.

The sub-row SHALL explain, on hover, that the figure is the grid import cost of EV charging, part of Grid Import and not added to Net, and that solar energy is not given a price. The solar share SHALL explain, on hover, that it is the share of EV energy that came from solar and is for information only.

The sub-row SHALL be presented as a component of Grid Import: the headline Net and the other rows SHALL NOT change. It SHALL use design-system tokens.

#### Scenario: EV row with solar share
- **WHEN** the period returns `ev_cost_sek=18.4`, `ev_charging_kwh=12.0`, `ev_solar_share=0.4`
- **THEN** the breakdown SHALL show a "↳ of which EV" sub-row under Grid Import with −18.4 kr, 12.0 kWh and "40% solar"

#### Scenario: Charger configured, no EV energy
- **GIVEN** an EV charger is configured
- **WHEN** `ev_charging_kwh` is 0 for the period
- **THEN** the EV sub-row SHALL show "0 kr" and "0 kWh" without a solar share

#### Scenario: No charger configured
- **GIVEN** no EV charger is configured
- **WHEN** `ev_charging_kwh` is 0 for the period
- **THEN** the EV sub-row SHALL be hidden

#### Scenario: Solar share explained
- **WHEN** the row shows a solar share
- **THEN** hovering it SHALL explain that it is the share of EV energy from solar, for information only

#### Scenario: Headline unchanged
- **WHEN** EV cost is non-zero
- **THEN** the headline Net SHALL still equal `net_cost_sek`

### Requirement: Grid & Financial card breakdown uses one row per figure
The financial breakdown of the Grid & Financial card SHALL show one row per figure in a single column, with the label on the left and the amount on the right, in this order: Grid Import (with its EV sub-row), Export Rev, Battery Charge, Self-Use Saved, Battery Wear. Amounts SHALL use tabular numerals and SHALL NOT wrap. The card SHALL span both bento rows in column 1 of the dashboard.

#### Scenario: Rows are single column
- **WHEN** the breakdown renders for a period
- **THEN** each figure is its own full-width row, label left and amount right

### Requirement: Grid & Financial card has a one-line period control
The period control SHALL be a single-line segmented control with the options Today, Yesterday, 7d, 30d and Custom, filling the card width without wrapping. The selected option SHALL be visibly highlighted. The existing behaviour of each period (and of the custom date range with its validation) SHALL be unchanged.

#### Scenario: All options on one line
- **WHEN** the card renders at any supported width
- **THEN** the five options are on one line

#### Scenario: Selecting a period reloads the card
- **WHEN** the user selects "7d"
- **THEN** the breakdown and the cost chart show the last 7 days including today

### Requirement: Grid & Financial card shows a cost chart for the period
Below the breakdown the card SHALL show one chart over the selected period using GET /api/energy/cost-series, filling the remaining card height. There SHALL be no Actual/Comparison tabs or view switch.

The chart SHALL retain metered hourly buckets on a fixed 00–24 axis for a single day, drawing started slots and headed "Actual cost so far". Longer periods SHALL retain daily buckets and the heading "Actual cost per day". It SHALL show the running metered net line (the Actual line, solid), green when earning (zero or below), red when paying, with a dashed zero line and faint import/export bars. When battery_comparison has amounts (status available or estimated), it SHALL also show a dotted "Without Darkstar" line on the same kr basis and vertical scale, equal per matching bucket to `cumulative_net_cost_sek + (self_use_cumulative_comparison_cost_sek − darkstar_cumulative_comparison_cost_sek)`. The vertical scale SHALL include both lines and zero. Buckets inside excluded stretches of the comparison SHALL carry the last known difference forward, and the dotted line SHALL stop at the last comparison point. The area between the Actual and dotted lines SHALL be shaded with a low-opacity design-system tone, good where Darkstar costs less and bad where it costs more, split at crossings, spanning the same range as the dotted line and carrying no label or legend entry. The legend SHALL list Actual (solid) and, when drawn, Without Darkstar (dotted). Hover or tap SHALL show the bucket's 24-hour time or date, import cost, export revenue and running total in the legend row, plus the without-Darkstar value when the line exists. Loading SHALL show a skeleton; an empty response SHALL say "No recorded slots yet for this period". Reduced motion SHALL disable entrance animations. Legacy baseline_cumulative_net_cost_sek SHALL NOT drive any UI line. Unavailable and no-battery states SHALL show only the Actual line.

#### Scenario: Today is hourly with a fixed actual axis
- **WHEN** Today is selected at 14:20
- **THEN** the chart spans 00 to 24 and only started metered slots are drawn

#### Scenario: Longer period is daily
- **WHEN** 30d is selected
- **THEN** daily buckets are shown with the heading "Actual cost per day"

#### Scenario: One chart with a dotted without-Darkstar line
- **WHEN** an estimated or available comparison has points
- **THEN** a single chart shows the solid Actual line with import/export bars and a dotted "Without Darkstar" line on the same kr scale
- **AND** no Actual/Comparison tabs are shown

#### Scenario: Without-Darkstar line crosses an excluded stretch
- **WHEN** some buckets have no comparison point
- **THEN** the dotted line carries the last known difference forward across them and stops at the last comparison point

#### Scenario: Saving is shaded between the lines
- **WHEN** the dotted line lies above the Actual line over some buckets and below it over others
- **THEN** the area between them is shaded good where the dotted line is higher and bad where it is lower, split at the crossing
- **AND** the shading has no label and no legend entry

#### Scenario: Net line colour follows the actual result
- **WHEN** the final actual net is below zero
- **THEN** the actual line is green; above zero it is red

#### Scenario: Readout includes the without-Darkstar value
- **WHEN** a bucket is hovered or tapped while the dotted line exists
- **THEN** the readout shows its time, running actual total and the without-Darkstar value

#### Scenario: No data and reduced motion
- **WHEN** no metered points exist
- **THEN** the chart displays its empty-state message
- **AND** when reduced motion is preferred, its entrance animations are disabled

#### Scenario: No comparison amounts
- **WHEN** comparison data is unavailable or no battery is configured
- **THEN** only the Actual line is shown, regardless of legacy baseline fields

### Requirement: Grid & Financial card summarises the saving in one line with a details panel
The card SHALL use amount-bearing battery_comparison data to show ONE compact line beneath the net figures: "Darkstar saved you X kr" when saving is non-negative, or "Darkstar cost you extra X kr" when negative, with X the absolute saving. The line SHALL carry an "Estimate" chip for the configured-loss basis or a "Verified" chip for a calibrated result, with an info control that toggles a pop-out panel; the panel SHALL be opaque and SHALL close on an outside tap or Escape. The two raw comparison costs SHALL NOT be shown inline. When coverage is partial (excluded_slots > 0) the line SHALL show a muted suffix "· N% of the period", with N the covered share floored and capped at 99.

All explanatory text SHALL live in the panel: that the comparison is against a plain self-use inverter with the same battery and the same EV/water timing, that EV/water scheduling savings are excluded, the "Completed through" time as local "YYYY-MM-DD HH:mm", short sentences on the calibration state (configured losses used; not enough reliable history; calibration checks not passed; verified) and on legacy readings with assumed sources, the coverage numbers (covered of total completed 15-minute slots, and how many were left out), and a nested "Cost adjustments and assumptions" fold-down. The fold-down SHALL state that comparison cost = grid + wear − stored energy value and show the common energy price and, per side (Darkstar and self-use), grid / wear / stored-energy value. The card SHALL NOT claim full or necessarily conservative Darkstar savings, and a configured-loss estimate SHALL NOT be presented as verified.

If the selected period has no usable comparison, the card SHALL show one plain-language unavailable reason with no comparison amount or legacy fallback. No-battery installations SHALL hide the comparison line. The "Self-Use Saved" breakdown row SHALL have a tooltip explaining that it is house use covered by solar/battery instead of the grid, valued at the import price. Actual headline net, wear-inclusive secondary net, Battery Wear and EV breakdown rows SHALL retain their existing accounting and design tokens.

#### Scenario: Positive saving
- **WHEN** configured-loss self-use comparison cost is 40 kr and Darkstar comparison cost is 30 kr
- **THEN** the card shows "Darkstar saved you 10.00 kr" with an "Estimate" chip
- **AND** the actual headline still equals the metered net_cost_sek

#### Scenario: Negative saving
- **WHEN** comparison saving is -2.1 kr
- **THEN** the card shows "Darkstar cost you extra 2.10 kr" with the chip for the active basis

#### Scenario: Verified chip
- **WHEN** the comparison has status available with a calibrated basis
- **THEN** the chip reads "Verified"

#### Scenario: Partial coverage suffix
- **WHEN** coverage is 95 of 96 slots
- **THEN** the line shows "· 98% of the period" and the panel states 95 of 96 slots with 1 left out

#### Scenario: Details panel
- **WHEN** the info control is tapped
- **THEN** an opaque panel explains the plain self-use comparison, the excluded load-scheduling savings, the completed-through time and coverage
- **AND** an outside tap or Escape closes it

#### Scenario: Stored energy is explained
- **WHEN** the "Cost adjustments and assumptions" fold-down is opened
- **THEN** the common price and each side's grid cost, wear and stored-energy value are visible
- **AND** comparison cost is explained as grid plus wear minus stored-energy value

#### Scenario: Unavailable comparison never uses legacy amounts
- **WHEN** no comparison amount is usable and legacy baseline savings exist
- **THEN** only the unavailable reason and actual information are shown
