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
Below the breakdown the card SHALL show a chart of cost over the selected period, filling the remaining card height, using `GET /api/energy/cost-series`.

- For a single day (Today, Yesterday or a one-day custom range) the chart SHALL show hourly buckets on a fixed 00–24 axis, drawing only slots that have started, headed "Cost so far".
- For longer periods the chart SHALL show one bucket per day over the whole period, headed "Cost per day".
- The chart SHALL draw the running net cost as a line, green when the final net is earning (zero or below) and red when paying, with a dashed zero line, and faint import and export bars per bucket on their own scale.
- Hovering a bucket SHALL show its time (24-hour clock, or weekday and date for daily buckets), its import cost, export revenue and the running total, replacing the legend while hovering.
- While data loads the chart SHALL show a skeleton; when no recorded slots exist it SHALL say so.
- Entrance animations SHALL be disabled when the user prefers reduced motion.

#### Scenario: Today is hourly with a fixed axis
- **WHEN** Today is selected at 14:20
- **THEN** the chart spans 00 to 24, with the line and bars drawn only up to the current hour

#### Scenario: Longer period is daily
- **WHEN** "30d" is selected
- **THEN** the chart shows one bucket per day and the heading reads "Cost per day"

#### Scenario: Net line colour follows the result
- **WHEN** the final running net cost is below zero (earning)
- **THEN** the net line is green; when above zero (paying) it is red

#### Scenario: Hover readout
- **WHEN** the user hovers the 13:00 bucket
- **THEN** the chart shows "13:00", that hour's import cost and export revenue, and the running total

#### Scenario: No data
- **WHEN** the endpoint returns no points
- **THEN** the chart area reads "No recorded slots yet for this period"

#### Scenario: Reduced motion
- **WHEN** the user prefers reduced motion
- **THEN** the chart does not animate its line or bars in

### Requirement: Grid & Financial card compares the period with running without Darkstar
When the cost series response carries a `baseline`, the card SHALL show a line directly below the net-incl-wear line reading "Without Darkstar" with `baseline.net_cost_sek` and the saving `saving_incl_wear_sek`. The saving SHALL be shown as a positive figure in the good colour when it is zero or more, and as "Darkstar cost more" with the amount in a muted colour when it is negative. The line SHALL be hidden when `baseline` is `null` (no battery, no slots, or the series failed to load). The saving shown SHALL include the stored-energy value from the baseline. Hovering SHALL explain that the comparison is a plain self-use inverter with the same battery, that the saving includes battery wear, and that EV and water heating are counted at their real hours, so the saving is conservative. When `stored_energy_difference_kwh` and `stored_energy_value_sek` are present and the difference is not zero, the hover text SHALL also state the amount in plain language, in the form "Includes +11.7 kr for 4.6 kWh more energy left in the battery at the end of the period" (one decimal; "less" and a minus sign when the real battery holds less), and SHALL omit that sentence otherwise. The headline Net and every existing row SHALL NOT change. The line SHALL use design-system tokens.

#### Scenario: Saving shown
- **WHEN** the baseline net is −26.4 kr and the saving is 7.7 kr
- **THEN** the card shows "Without Darkstar" with the baseline net and a saving of 7.7 kr in the good colour

#### Scenario: Negative saving
- **WHEN** the saving is −2.1 kr
- **THEN** the card shows that Darkstar cost 2.1 kr more, in a muted colour

#### Scenario: Hover explains energy left in the battery
- **WHEN** the stored-energy difference is 4.6 kWh and its value 11.7 kr
- **THEN** the hover text contains "Includes +11.7 kr for 4.6 kWh more energy left in the battery at the end of the period"

#### Scenario: Hover explains less energy left
- **WHEN** the stored-energy difference is −1.2 kWh and its value −3.2 kr
- **THEN** the hover text contains "Includes -3.2 kr for 1.2 kWh less energy left in the battery at the end of the period"

#### Scenario: No stored-energy sentence when unknown
- **WHEN** the stored-energy fields are `null`
- **THEN** the hover text has no "Includes" sentence

#### Scenario: Hidden without a baseline
- **WHEN** `baseline` is `null`
- **THEN** the line is not rendered

#### Scenario: Headline unchanged
- **WHEN** the baseline line is shown
- **THEN** the headline Net still equals `net_cost_sek`

### Requirement: Cost chart draws the without-Darkstar line
When the points carry `baseline_cumulative_net_cost_sek`, the cost chart SHALL draw it as a dashed muted line over the same buckets as the real net line, with a legend entry "no Darkstar". The chart heading ("Cost so far" / "Cost per day") SHALL stay on one line, the legend SHALL sit on its own row below the heading and wrap between entries, never inside one, and the hover readout SHALL replace the legend in that row. Vertical scaling SHALL include the baseline values so neither line is clipped, with zero still inside the range. The hover readout SHALL additionally show the baseline running total. The baseline line SHALL NOT be drawn when the points have no baseline field, and the chart SHALL then look and scale as before. Its entrance animation SHALL be disabled under reduced motion like the other chart elements.

#### Scenario: Both lines drawn on one scale
- **WHEN** the real final net is −18.7 kr and the baseline final net is −26.4 kr
- **THEN** both lines are drawn on one scale with the dashed baseline line distinguishable from the net line

#### Scenario: Baseline extends the range
- **WHEN** the baseline running total is higher than the real running total at some hour
- **THEN** the vertical range covers the baseline's maximum

#### Scenario: Hover shows both totals
- **WHEN** the user hovers a bucket
- **THEN** the readout shows the real running total and the baseline running total

#### Scenario: Heading and legend at card width
- **WHEN** the chart is shown at a card width of about 320-360 px with the "no Darkstar" legend entry
- **THEN** the heading is on one line and each legend entry is on one line, with the legend on a row below the heading

#### Scenario: No baseline
- **WHEN** the points have no baseline field
- **THEN** only the net line is drawn and the legend has no "no Darkstar" entry
