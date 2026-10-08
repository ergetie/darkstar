## MODIFIED Requirements

### Requirement: Grid & Financial card shows a cost chart for the period
Below the breakdown the card SHALL show one chart from `/api/energy/cost-series` filling the remaining card height, with no Actual/Comparison switch. A single-day chart SHALL use hourly buckets and heading "Actual cost so far"; longer periods SHALL use daily buckets and heading "Actual cost per day". All x positions SHALL use elapsed UTC time within `grid_only_comparison.time_axis.start`/`end`, spanning the full requested local period. Single-day axes SHALL represent 24 elapsed hours normally, 23 on spring-forward days and 25 on fall-back days. Daily buckets SHALL use their actual installation-local midnight boundaries, rather than assuming every day is 86,400 seconds. Labels and readouts SHALL use `time_axis.timezone` independently of the browser timezone. Nonexistent local hours SHALL be omitted; repeated local hours SHALL have distinct x positions and UTC-offset labels. These time-axis rules SHALL also apply to the Actual-only fallback.

When `grid_only_comparison` contains valid amounts, bucket points and covered segments, the chart SHALL draw a solid **DS** line directly from segment boundary `cumulative_ds_cost_sek` and a dotted **Grid-only** line directly from segment boundary `cumulative_grid_only_cost_sek`. Faint import/export bars and bucket readouts SHALL use comparison bucket points covering the same eligible completed slots. Neither line SHALL use self-use simulation, stored-energy adjustments, legacy fields, or differently covered top-level actual points. Their shared vertical scale SHALL contain both lines and zero. The DS line SHALL be green at zero/below and red above zero, with the existing dashed zero reference.

The area between comparable covered stretches SHALL use low-opacity design-system good/bad tones according to which bill is lower, split at crossings within each covered segment, with no shading legend entry. Each segment SHALL be drawn independently. Lines and shading SHALL NOT connect across excluded slots, including gaps inside partially covered hourly/daily buckets, or fabricate excluded contributions. Cumulative totals SHALL carry into the next segment without drawing across the gap. The last drawn point SHALL equal its comparison summary within rounding. Hover/tap SHALL expose the bucket's installation-local 24-hour time/date, eligible import/export costs, DS running cost and Grid-only running cost; repeated-hour readouts SHALL include the UTC offset. Without amount-bearing comparison data, the chart SHALL retain its top-level metered Actual-only fallback, bars and accounting.

Loading SHALL show a skeleton; empty metered data SHALL display "No recorded slots yet for this period". Reduced motion SHALL disable entrance animations. Existing responsive layout and design tokens SHALL be used. Battery absence SHALL NOT suppress an otherwise usable Grid-only line.

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
- **AND** no Without Darkstar legend or view switch exists

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

### Requirement: Grid & Financial card summarises the saving in one line with a details panel
The card SHALL show exactly one compact signed monetary comparison beneath the actual net figures, labelled **DS vs grid-only**. It SHALL use `grid_only_comparison.saving_sek`: positive values show `+X.XX kr` with the good token, negative values show `-X.XX kr` with the bad token and zero uses a neutral token. It SHALL NOT use "Darkstar saved you", "Darkstar cost you extra", Estimate/Verified chips, self-use figures or a remaining-battery-energy adjustment.

The existing accessible info control SHALL toggle an opaque details panel that closes on outside tap or Escape. The explanation SHALL read "Same recorded consumption bought entirely from the grid at each slot's price, compared with actual import costs minus export income, including estimated battery wear." The panel SHALL identify the whole-installation comparison, show grid-only electricity and zero wear, DS electricity and DS wear, the wear-inclusive DS total, completed-through installation-local `YYYY-MM-DD HH:mm`, and covered/total completed slot counts with exclusions. It SHALL contain no loss calibration, assumed SoC mapping, monetary battery inventory, future-price or nested adjustment details. Partial coverage SHALL retain a muted "· N% of the period" suffix with the covered share floored and capped at 99.

No-data/unavailable results SHALL show one concise plain-language reason with no monetary comparison or legacy fallback. The comparison SHALL be shown without a battery when relevant inputs are usable. Actual headline electricity cost, the separate wear-inclusive figure, Grid Import, EV sub-row, Export Rev, informational Battery Charge and Battery Wear rows SHALL retain their accounting and design-system presentation. Battery Charge SHALL be clearly identified as informational because its cost is already included in Grid Import, and SHALL never be deducted again.

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
