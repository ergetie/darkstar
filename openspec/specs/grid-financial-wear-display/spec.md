# Grid Financial Wear Display

## Purpose

UI presentation of actual electricity cost, estimated battery wear and matched-coverage DS versus grid-only bill comparisons in the Grid & Financial summary card.

## Requirements

### Requirement: Grid & Financial card shows net including battery wear
The Grid & Financial card SHALL display a secondary line beneath the headline Net figure showing the net cost including battery wear, sourced from the endpoint's `net_cost_incl_wear_sek`. This secondary line SHALL be visually distinct (it "pops out") from the surrounding breakdown text so the user can read it at a glance. The headline Net figure SHALL continue to show `net_cost_sek` (real grid cash flow) and SHALL NOT change.

#### Scenario: Wear-inclusive secondary line convention
- **WHEN** the secondary wear-inclusive line is displayed
- **THEN** it SHALL follow the same sign and color convention as the headline (savings vs. cost), applied to the wear-inclusive value

#### Scenario: Secondary net-incl-wear line is shown
- **WHEN** the card renders with period data available
- **THEN** the headline shows the pure-grid Net (`net_cost_sek`)
- **AND** a distinct secondary line below shows the net including battery wear (`net_cost_incl_wear_sek`)

#### Scenario: Headline Net is unchanged by this feature
- **WHEN** battery wear is non-zero for the period
- **THEN** the headline Net value matches `net_cost_sek` exactly (wear is not folded into it)

### Requirement: Grid & Financial card shows a Battery Wear breakdown row
The financial breakdown section of the card SHALL include a "Battery Wear" row showing `battery_wear_cost_sek` for the period, presented as a cost alongside the existing breakdown rows (Grid Import, Export Rev, Battery Charge).

#### Scenario: Battery Wear row appears in the breakdown
- **WHEN** the breakdown section renders for a period with battery throughput
- **THEN** a "Battery Wear" row shows the `battery_wear_cost_sek` value
- **AND** it is presented consistently with the other breakdown rows

#### Scenario: Zero wear renders cleanly
- **WHEN** the period has no battery throughput
- **THEN** the "Battery Wear" row shows `0.00`

### Requirement: Grid & Financial card shows an EV sub-row under Grid Import
When an EV charger is configured (`system.has_ev_charger`), the card's breakdown section SHALL always include an indented "↳ of which EV" sub-row directly under "Grid Import", even when the period has no EV energy. It SHALL show `ev_cost_sek` (the EV's grid import cost only) as a cost, the total EV kWh, and the solar share as a percentage. When no EV charger is configured, the sub-row SHALL be hidden unless the period has recorded EV energy.

#### Scenario: EV sub-row hover explanations
- **WHEN** the user hovers the EV sub-row or its solar share
- **THEN** the sub-row SHALL explain that the figure is the grid import cost of EV charging, part of Grid Import and not added to Net, and that solar energy is not given a price
- **AND** the solar share SHALL explain that it is the share of EV energy that came from solar and is for information only

#### Scenario: EV sub-row is a component of Grid Import
- **WHEN** the EV sub-row is rendered
- **THEN** it SHALL be presented as a component of Grid Import: the headline Net and the other rows SHALL NOT change
- **AND** it SHALL use design-system tokens

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
The financial breakdown of the Grid & Financial card SHALL show one row per figure in a single column, with the label on the left and the amount on the right, in this order: Grid Import (with its EV sub-row), Export Rev, Battery Charge, Battery Wear. Amounts SHALL use tabular numerals and SHALL NOT wrap. The card SHALL span both bento rows in column 1 of the dashboard.

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
Below the breakdown the card SHALL show one chart from `/api/energy/cost-series` filling the remaining card height, with no Actual/Comparison switch. A single-day chart SHALL use hourly buckets and heading "Actual cost so far"; longer periods SHALL use daily buckets and heading "Actual cost per day". All x positions SHALL use elapsed UTC time within `grid_only_comparison.time_axis.start`/`end`, spanning the full requested local period.

#### Scenario: Chart time axis is elapsed UTC time
- **WHEN** the cost chart axis is drawn
- **THEN** single-day axes SHALL represent 24 elapsed hours normally, 23 on spring-forward days and 25 on fall-back days
- **AND** daily buckets SHALL use their actual installation-local midnight boundaries, rather than assuming every day is 86,400 seconds
- **AND** labels and readouts SHALL use `time_axis.timezone` independently of the browser timezone
- **AND** nonexistent local hours SHALL be omitted; repeated local hours SHALL have distinct x positions and UTC-offset labels
- **AND** these time-axis rules SHALL also apply to the Actual-only fallback

#### Scenario: DS and Grid-only lines
- **WHEN** `grid_only_comparison` contains valid amounts, bucket points and covered segments
- **THEN** the chart SHALL draw a solid **DS** line directly from segment boundary `cumulative_ds_cost_sek` and a dotted **Grid-only** line directly from segment boundary `cumulative_grid_only_cost_sek`
- **AND** faint import/export bars and bucket readouts SHALL use comparison bucket points covering the same eligible completed slots
- **AND** neither line SHALL use self-use simulation, stored-energy adjustments, legacy fields, or differently covered top-level actual points
- **AND** their shared vertical scale SHALL contain both lines and zero
- **AND** the DS line SHALL be green at zero/below and red above zero, with the existing dashed zero reference

#### Scenario: Shading between comparable covered stretches
- **WHEN** the DS and Grid-only lines are drawn over comparable covered stretches
- **THEN** the area between them SHALL use low-opacity design-system good/bad tones according to which bill is lower, split at crossings within each covered segment, with no shading legend entry

#### Scenario: Segments are not connected across excluded slots
- **WHEN** the chart contains excluded slots
- **THEN** each segment SHALL be drawn independently
- **AND** lines and shading SHALL NOT connect across excluded slots, including gaps inside partially covered hourly/daily buckets, or fabricate excluded contributions
- **AND** cumulative totals SHALL carry into the next segment without drawing across the gap
- **AND** the last drawn point SHALL equal its comparison summary within rounding

#### Scenario: Hover readout and Actual-only fallback
- **WHEN** the user hovers or taps a bucket
- **THEN** the readout SHALL expose the bucket's installation-local 24-hour time/date, eligible import/export costs, DS running cost and Grid-only running cost; repeated-hour readouts SHALL include the UTC offset
- **AND** without amount-bearing comparison data, the chart SHALL retain its top-level metered Actual-only fallback, bars and accounting

#### Scenario: Chart loading, empty and motion states
- **WHEN** the chart is loading, has no metered data, has reduced motion enabled, or the battery is absent
- **THEN** loading SHALL show a skeleton
- **AND** empty metered data SHALL display "No recorded slots yet for this period"
- **AND** reduced motion SHALL disable entrance animations
- **AND** existing responsive layout and design tokens SHALL be used
- **AND** battery absence SHALL NOT suppress an otherwise usable Grid-only line

#### Scenario: Today excludes an unfinished slot from comparison lines
- **WHEN** Today is selected at 14:20 and valid comparison data exists
- **THEN** the chart spans the full local day with its actual elapsed duration and both DS and Grid-only price only the same completed eligible slots
- **AND** the actual headline retains its existing accounting

#### Scenario: Longer period is daily
- **WHEN** 30d is selected
- **THEN** daily comparison buckets are shown with "Actual cost per day"

#### Scenario: Direct grid-only line
- **WHEN** comparison amounts and points exist
- **THEN** one chart shows solid DS, dotted Grid-only and eligible import/export bars
- **AND** no view switch exists

#### Scenario: Excluded stretch
- **WHEN** completed buckets contain no usable comparison slots
- **THEN** no costs are invented for those buckets and both lines and shading break across the gap

#### Scenario: Excluded slot inside a covered bucket
- **WHEN** an hourly or daily bucket has eligible slots before and after an excluded slot
- **THEN** its bar and readout contain only eligible costs
- **AND** segment geometry breaks both lines and shading at the exact excluded interval
- **AND** the later segment resumes at the cumulative totals from earlier eligible slots

#### Scenario: Fall-back hour positions
- **WHEN** the installation-local day contains both 02:00 +02:00 and 02:00 +01:00
- **THEN** the axis spans 25 elapsed hours and the repeated hours have distinct chronological x positions and offset-qualified labels/readouts

#### Scenario: Spring-forward hour positions
- **WHEN** the installation-local day skips 02:00 during spring-forward
- **THEN** the axis spans 23 elapsed hours without a fabricated 02:00 bucket or a false excluded-slot gap

#### Scenario: Browser timezone differs
- **WHEN** the browser timezone differs from the installation timezone
- **THEN** chart positions, labels, dates and readouts still describe the installation-local period for comparison and Actual-only charts

#### Scenario: Comparison crosses
- **WHEN** DS is cheaper in one covered stretch and dearer in another
- **THEN** shading changes good/bad at crossings with no shading label or legend entry

#### Scenario: Readout
- **WHEN** a covered bucket is hovered or tapped
- **THEN** the readout shows its time/date, eligible import/export costs and both running bill totals

#### Scenario: No comparison amounts
- **WHEN** comparison is no_data or unavailable
- **THEN** only the existing top-level Actual metered line and bars are shown

#### Scenario: Solar-only chart
- **WHEN** there is no battery and valid grid-only comparison points exist
- **THEN** both DS and Grid-only lines are drawn

#### Scenario: Empty data and reduced motion
- **WHEN** no metered points exist
- **THEN** the existing empty-state message is displayed
- **AND** reduced-motion preference disables chart entrance animation

#### Scenario: Net line colour follows the actual result
- **WHEN** the Actual-only fallback is shown and the final actual net is below zero
- **THEN** the actual line is green; above zero it is red

### Requirement: Grid & Financial card summarises the saving in one line with a details panel
The card SHALL show exactly one compact signed monetary comparison beneath the actual net figures, labelled **DS vs grid-only**. It SHALL use `grid_only_comparison.saving_sek`: positive values show `+X.XX kr` with the good token, negative values show `-X.XX kr` with the bad token and zero uses a neutral token. It SHALL NOT use "Darkstar saved you", "Darkstar cost you extra", Estimate/Verified chips, self-use figures or a remaining-battery-energy adjustment.

#### Scenario: Comparison details panel behavior
- **WHEN** the user activates the accessible info control
- **THEN** it SHALL toggle an opaque details panel that closes on outside tap or Escape

#### Scenario: Comparison details panel content
- **WHEN** the details panel is open
- **THEN** the explanation SHALL read "Same recorded consumption bought entirely from the grid at each slot's price, compared with actual import costs minus export income, including estimated battery wear."
- **AND** the panel SHALL identify the whole-installation comparison, show grid-only electricity and zero wear, DS electricity and DS wear, the wear-inclusive DS total, completed-through installation-local `YYYY-MM-DD HH:mm`, and covered/total completed slot counts with exclusions
- **AND** it SHALL contain no loss calibration, assumed SoC mapping, monetary battery inventory, future-price or nested adjustment details

#### Scenario: Partial coverage suffix
- **WHEN** coverage of the period is partial
- **THEN** the comparison SHALL retain a muted "· N% of the period" suffix with the covered share floored and capped at 99

#### Scenario: No-data results and unchanged accounting rows
- **WHEN** the comparison result is no-data or unavailable
- **THEN** it SHALL show one concise plain-language reason with no monetary comparison or legacy fallback
- **AND** the comparison SHALL be shown without a battery when relevant inputs are usable
- **AND** actual headline electricity cost, the separate wear-inclusive figure, Grid Import, EV sub-row, Export Rev, informational Battery Charge and Battery Wear rows SHALL retain their accounting and design-system presentation
- **AND** Battery Charge SHALL be clearly identified as informational because its cost is already included in Grid Import, and SHALL never be deducted again

#### Scenario: Positive difference including wear
- **WHEN** grid-only cost is 40 kr, DS electricity cost is 28 kr and DS wear is 2 kr
- **THEN** the line shows "DS vs grid-only +10.00 kr" using the good token and no verification chip

#### Scenario: Negative difference
- **WHEN** grid-only cost is 30 kr and DS cost is 32.1 kr
- **THEN** the line shows "DS vs grid-only -2.10 kr" using the bad token

#### Scenario: Equal comparison costs
- **WHEN** the grid-only bill and wear-inclusive DS comparison cost are equal
- **THEN** the comparison shows zero with neutral styling

#### Scenario: Partial coverage
- **WHEN** coverage is 95 of 96 slots
- **THEN** the line shows "· 98% of the period" and details show 95 covered and 1 excluded

#### Scenario: Simple details
- **WHEN** the info control is tapped
- **THEN** the panel explains the grid-only bill baseline and shows both costs, through-time and coverage
- **AND** outside tap or Escape closes it

#### Scenario: Unavailable inputs
- **WHEN** no usable comparison amount exists
- **THEN** a plain-language reason is shown without a signed amount or legacy fallback

#### Scenario: Separate wear remains separate
- **WHEN** recorded battery throughput increases without changing demand or measured imports/exports
- **THEN** the separate wear-inclusive figure and DS wear-inclusive comparison update
- **AND** the grid-only baseline and DS electricity amount stay unchanged

#### Scenario: Battery Charge remains informational
- **WHEN** battery charging cost is shown in the breakdown
- **THEN** its tooltip says it is already included in Grid Import and is not deducted again
- **AND** the Self-Use Saved row and tooltip are absent
