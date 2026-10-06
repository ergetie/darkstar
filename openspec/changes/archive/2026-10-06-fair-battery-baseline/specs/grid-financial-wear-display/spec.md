## MODIFIED Requirements

### Requirement: Grid & Financial card shows a cost chart for the period
Below the breakdown the card SHALL show a chart over the selected period using `GET /api/energy/cost-series`, filling the remaining card height. Actual and validated Comparison SHALL be distinct selectable views when an estimate is available; unavailable and no-battery states SHALL retain only Actual.

The Actual view SHALL retain metered hourly buckets on a fixed 00–24 axis for a single day, drawing started slots and headed "Actual cost so far". Longer periods SHALL retain daily buckets and the heading "Actual cost per day". It SHALL show the running metered net line, green when earning (zero or below), red when paying, with a dashed zero line and faint import/export bars. Hover SHALL show the bucket's 24-hour time or date, import cost, export revenue and running total in the legend row. Loading SHALL show a skeleton; an empty response SHALL say "No recorded slots yet for this period". Reduced motion SHALL disable entrance animations.

The Comparison view SHALL display the two validated cumulative economic costs including wear and stored-energy valuation, headed "Estimated comparison cost", with time labels matching the completed comparison interval. It SHALL exclude metered bars and legacy baseline lines. Both comparison values SHALL share one vertical scale including zero. Bucket readouts SHALL expose both costs and the bucket time; mobile users SHALL be able to tap a bucket.

#### Scenario: Today is hourly with a fixed actual axis
- **WHEN** Today is selected at 14:20 in Actual view
- **THEN** the chart spans 00 to 24 and only started metered slots are drawn

#### Scenario: Longer period is daily
- **WHEN** 30d is selected in Actual view
- **THEN** daily buckets are shown with the heading "Actual cost per day"

#### Scenario: Available comparison uses its completed interval
- **WHEN** a comparison completed through 03:45 is selected
- **THEN** its final points and time labels end at 03:45
- **AND** no metered cash-flow bars appear

#### Scenario: Net line colour follows the actual result
- **WHEN** the final actual net is below zero
- **THEN** the actual line is green; above zero it is red

#### Scenario: No data and reduced motion
- **WHEN** no metered points exist
- **THEN** the chart displays its empty-state message
- **AND** when reduced motion is preferred, its entrance animations are disabled

### Requirement: Grid & Financial card compares the period with running without Darkstar
The card SHALL use only available validated `battery_comparison` data to display "Estimated battery savings", with Darkstar and plain self-use totals on the same economic basis. Negative savings SHALL instead be labeled "Estimated additional battery cost". The latest completed time and accessible cost adjustments SHALL explain shared recorded EV/water timings, house/water-only self-use discharge with remaining PV allowed to serve EV demand, excluded load-scheduling savings, shared calibrated losses, wear, stored-energy valuation at the common period reference price and the limitations of 15-minute totals. It SHALL NOT claim full or necessarily conservative Darkstar savings.

Unavailable estimates SHALL show one plain-language reason with no comparison amount or legacy fallback. No-battery installations SHALL hide the comparison controls. Actual headline net, wear-inclusive secondary net, Battery Wear and EV breakdown rows SHALL retain their existing accounting and design tokens.

#### Scenario: Positive saving reconciles
- **WHEN** validated self-use comparison cost is 40 kr and Darkstar comparison cost is 30 kr
- **THEN** the card displays estimated battery savings of 10 kr
- **AND** the actual headline still equals the metered `net_cost_sek`

#### Scenario: Negative saving
- **WHEN** estimated saving is -2.1 kr
- **THEN** the card describes estimated additional battery cost of 2.1 kr

#### Scenario: Stored energy is explained
- **WHEN** the adjustment details are opened
- **THEN** grid cost, wear, stored-energy value and the common valuation price are visible
- **AND** comparison cost is explained as grid plus wear minus stored-energy value

#### Scenario: Unavailable estimate never uses legacy amounts
- **WHEN** validation fails and legacy baseline savings exist
- **THEN** only the unavailable reason and actual information are shown

### Requirement: Cost chart draws the without-Darkstar line
The chart SHALL replace the legacy without-Darkstar overlay with paired Darkstar and plain self-use lines exclusively in the validated Comparison view. Legacy `baseline_cumulative_net_cost_sek` SHALL NOT determine any UI line, saving or vertical scale. The paired lines SHALL be distinguishable and share one scale. Their final values SHALL equal their summary comparison totals, and their final difference SHALL equal the displayed saving within rounding. The heading SHALL stay on one line with the legend on a separate row, wrapping between entries. Comparison readouts SHALL replace that legend row and show both cumulative costs. Reduced motion SHALL disable entrance animations.

#### Scenario: Both economic lines on one scale
- **WHEN** Darkstar comparison cost ends at 30 kr and self-use at 40 kr
- **THEN** both lines appear on one scale and their endpoint gap is 10 kr

#### Scenario: Hover and tap show both totals
- **WHEN** a comparison bucket is hovered or tapped
- **THEN** the readout shows its time and both economic costs

#### Scenario: Heading and legend at card width
- **WHEN** the chart is rendered at about 320–360 px
- **THEN** its heading remains on one line and legend entries wrap only between entries

#### Scenario: No validated comparison
- **WHEN** comparison data is unavailable or no battery is configured
- **THEN** only Actual is shown, regardless of legacy baseline fields
