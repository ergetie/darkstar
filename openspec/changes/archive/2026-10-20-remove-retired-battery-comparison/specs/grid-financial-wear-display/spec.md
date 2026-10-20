## MODIFIED Requirements

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
