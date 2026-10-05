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
