## ADDED Requirements

### Requirement: Mobile slot selection survives live updates
On mobile viewports, a slot selected on the `ChartCard` SHALL stay selected, with its band and values panel visible, until the user dismisses it by tapping outside the card or tapping the selected slot again. Live metric updates and other re-renders of the dashboard that do not change the schedule data SHALL NOT clear the selection or rebuild the chart data. When the schedule data does change and the selected index is still within the new data, the selection SHALL be kept and the panel SHALL show the updated values; if the index is no longer valid, the selection SHALL be cleared.

#### Scenario: Selection stays across live metric updates
- **GIVEN** a user on a mobile viewport has tapped a slot on the schedule chart
- **WHEN** several `live_metrics` events arrive over the following 30 seconds
- **THEN** the selection band and values panel remain visible for the same slot

#### Scenario: Selection kept on data refresh
- **GIVEN** a slot is selected and the new schedule data still contains that index
- **WHEN** the schedule data refreshes
- **THEN** the same slot stays selected and the panel shows the refreshed values

#### Scenario: Selection cleared when index is no longer valid
- **GIVEN** a slot is selected
- **WHEN** the schedule data refreshes with fewer slots than the selected index
- **THEN** the selection is cleared and the panel collapses

### Requirement: Chart hour labels fit the available width
The `ChartCard` x axis SHALL show hour text labels only as often as they fit the chart's current width without overlapping. When a label for every visible hour does not fit, the axis SHALL show text only for every third hour (00, 03, 06, ...), and only for every sixth or twelfth hour if every third still does not fit. A mark for every hour SHALL remain drawn in the chart. The decision SHALL depend on the available chart width and visible range, not on whether the viewport is classified as mobile. When every hour label fits, the axis SHALL keep a label for every hour.

#### Scenario: Narrow width labels every third hour
- **GIVEN** the chart shows today and tomorrow (48 hours) in a card about 350 px wide
- **WHEN** the x axis is drawn
- **THEN** hour text appears only at 00, 03, 06, 09, 12, 15, 18 and 21
- **AND** a dot mark is still drawn for every hour

#### Scenario: Wide width keeps current labelling
- **GIVEN** the chart shows 48 hours in a card about 1200 px wide
- **WHEN** the x axis is drawn
- **THEN** every hour has a text label, as before

#### Scenario: Narrow desktop window
- **GIVEN** a desktop browser window narrowed so the chart is too small for a label per hour
- **WHEN** the x axis is drawn
- **THEN** labels are thinned the same way as on a mobile viewport of the same width

#### Scenario: Labels never overlap
- **GIVEN** any chart width and zoom level that leaves at least 16 px per twelve hours
- **WHEN** the x axis is drawn
- **THEN** adjacent hour labels are at least 16 px apart
