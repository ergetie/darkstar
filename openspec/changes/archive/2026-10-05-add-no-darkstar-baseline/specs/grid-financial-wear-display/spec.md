## ADDED Requirements

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
