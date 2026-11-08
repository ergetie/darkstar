# Spec Delta

## ADDED Requirements

### Requirement: Cost chart marks excluded spans with their reason
For every entry of `grid_only_comparison.excluded_spans` the cost chart SHALL draw a muted band over the span, using design-system tokens only and not conveying the exclusion by colour alone. DS and Grid-only lines and shading SHALL be unchanged and SHALL NOT be connected across a span.

#### Scenario: Band over an excluded span
- **GIVEN** covered segments 00:00-08:15 and 12:15-now with 08:15-12:15 excluded
- **WHEN** the chart is drawn
- **THEN** a muted band marks 08:15-12:15 with a non-colour cue such as a hatch or edge line
- **AND** the DS line ends at 08:15 and resumes at 12:15 at the earlier accumulated total

#### Scenario: Range text uses an en dash
- **WHEN** the readout names an excluded span's time range
- **THEN** the range is written `08:15–12:15` with U+2013 and no spaces, like other ranges in the UI

#### Scenario: Older backend without spans
- **WHEN** the response has no `excluded_spans`
- **THEN** the chart renders as before without bands and without error

#### Scenario: Hover or focus inside a band
- **WHEN** a bucket overlapping an excluded span is hovered or focused
- **THEN** the readout names the reason in plain words, with the span's time range

### Requirement: Coverage text explains why slots were not compared
Where the card shows "N excluded", it SHALL add a short human-readable reason note per reason group, largest first, such as "2 h not compared: EV charger not measured". Reason codes SHALL map to fixed plain-language phrases and never be shown raw. With more than two groups the note SHALL list the two largest and a count of the rest.

#### Scenario: Single reason
- **WHEN** 8 slots are excluded for `unknown_component` on `ev`
- **THEN** the card shows "2 h not compared: EV charger not measured"

#### Scenario: Several reasons
- **WHEN** slots are excluded for four different reasons
- **THEN** the two largest are named and the rest are summarised as "and 2 more reasons"

#### Scenario: No exclusions or older backend
- **WHEN** nothing is excluded or the response has no reason data
- **THEN** no reason note is shown and the existing coverage text is unchanged

### Requirement: Cost chart axis labels never overlap
The cost chart SHALL lay out its x-axis labels against the measured chart width so that no two labels overlap at any width, including on days with a repeated local hour. A label that would overlap another in its row SHALL move to the other row, or be omitted when neither row is free; the axis start, axis end and repeated-hour labels have priority over the others.

#### Scenario: Fall-back day on a narrow card
- **GIVEN** a 25 hour day with repeated `02:00` labels and a chart about 290 px wide
- **WHEN** the axis is drawn
- **THEN** the `02+2`, `02+1`, `00:00` and `05:00` labels do not overlap, and the repeated-hour labels and the axis start are shown

#### Scenario: Wide chart keeps every label
- **WHEN** the chart is wide enough for all labels
- **THEN** every label is shown

### Requirement: Cost chart bucket readout works on touch, mouse and keyboard
The cost chart bucket readout SHALL open on the first touch tap of a bucket, close when the same bucket is tapped again, and switch when another bucket is tapped. With a mouse the readout SHALL show on hover and a click SHALL NOT close it. With the keyboard, focus SHALL show it, blur SHALL hide it, and Enter or Space SHALL NOT close it.

#### Scenario: First touch tap opens
- **WHEN** a touch browser fires pointerenter, pointerdown, mouseenter, focus, pointerup and click for one tap on a bucket
- **THEN** that bucket's readout is shown

#### Scenario: Second touch tap closes, another bucket switches
- **WHEN** the shown bucket is tapped again
- **THEN** the readout closes
- **WHEN** a different bucket is tapped instead
- **THEN** the readout shows that bucket

#### Scenario: Mouse and keyboard
- **WHEN** a mouse hovers and clicks a bucket
- **THEN** the readout stays open until the pointer leaves the chart
- **WHEN** a bucket is focused by keyboard and Enter or Space is pressed
- **THEN** the readout stays open until blur
