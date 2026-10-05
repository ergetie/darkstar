## ADDED Requirements

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
