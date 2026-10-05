# Dashboard Layout

## Purpose

TBD - Defines the layout structure for the main dashboard page including the three-row layout, bento grid configuration, and removal of the lab page.
## Requirements
### Requirement: Dashboard uses a three-row layout
The dashboard at `/` SHALL consist of three vertical sections in order: (1) schedule chart row using `ChartCard`, (2) unified command bar row using `CommandBar`, (3) bento grid row. The layout SHALL be responsive and collapse to a single column on small screens.

#### Scenario: Desktop layout renders all three rows
- **WHEN** a user loads the dashboard on a large screen (lg breakpoint)
- **THEN** the page displays ChartCard at the top, CommandBar below it, and the bento grid below that

#### Scenario: Mobile layout collapses to single column
- **WHEN** a user loads the dashboard on a small screen
- **THEN** all sections stack vertically in a single column in the same top-to-bottom order

---

### Requirement: Bento grid uses three columns with Battery & Strategy spanning two rows
The bento grid SHALL use three columns on large screens. The cell layout SHALL be:
- Column 1, Rows 1–2: `GridDomain` (from CommandDomains), spanning both rows (`lg:row-span-2`)
- Column 2, Row 1: `PowerFlowCard`
- Column 2, Row 2: `ResourcesDomain` (from CommandDomains)
- Column 3, Rows 1–2: `BatteryStrategyCard` (`lg:row-span-2`)

The dashboard SHALL NOT include a Smart Advisor card.

#### Scenario: GridDomain and BatteryStrategyCard span two rows on large screens
- **WHEN** a user views the dashboard on a large screen
- **THEN** GridDomain occupies the full height of the bento grid in column 1 and BatteryStrategyCard the full height in column 3

#### Scenario: Bento cells collapse to single column on mobile
- **WHEN** a user views the dashboard on a small screen
- **THEN** the four bento cards stack vertically: GridDomain, PowerFlowCard, BatteryStrategyCard, ResourcesDomain

#### Scenario: No Smart Advisor on the dashboard
- **WHEN** a user views the dashboard
- **THEN** no Smart Advisor card is shown and no advice request is made by the page

### Requirement: DashboardLab page is removed
The `/dashboard-lab` route, its sidebar navigation link, and its source file (`DashboardLab.tsx`) SHALL be removed from the application.

#### Scenario: Lab route is inaccessible
- **WHEN** a user navigates to `/dashboard-lab`
- **THEN** the application does not render the lab page (404 or redirect)

#### Scenario: Sidebar has no Lab link
- **WHEN** the user views the sidebar navigation
- **THEN** there is no Lab (flask) icon or `/dashboard-lab` link

---

### Requirement: Mobile chart slot selection panel
`ChartCard` SHALL show a slot info panel above the chart plot at all viewport sizes, in place of any floating tooltip. The panel SHALL show the slot under the pointer on desktop, the tapped slot on mobile viewports (below Tailwind `md` / < 768 px), and the current slot when no slot is pinned. On mobile, tapping a slot SHALL select it, drawing a guide line at that slot and marking the panel as pinned; tapping the selected slot again SHALL clear the selection. The panel SHALL NOT change the card height when a slot is selected. The panel's contents are specified in the `chart-planned-actual-display` capability.

#### Scenario: Mobile tap selects slot and pins the panel
- **WHEN** a user on a mobile viewport (< 768 px) taps a slot on the schedule chart
- **THEN** a guide line appears at that slot and the info panel shows that slot's time and values as pinned

#### Scenario: Mobile tap outside card clears selection
- **WHEN** a user on a mobile viewport taps outside the `ChartCard` while a slot is selected
- **THEN** the guide line disappears and the panel returns to showing the current slot

#### Scenario: No floating tooltip at any size
- **WHEN** a user interacts with the schedule chart on any viewport
- **THEN** no Chart.js floating tooltip is shown

#### Scenario: Desktop hover drives the panel
- **WHEN** a user on a desktop viewport (≥ 768 px) hovers over the plot
- **THEN** a guide line follows the pointer to the hovered slot and the panel shows that slot; when the pointer leaves the plot, the panel returns to the current slot

#### Scenario: Selection clears when the selected slot no longer exists
- **WHEN** chart data refreshes while a slot is selected on mobile and the selected index is beyond the new data
- **THEN** the selection is cleared and the panel shows the current slot

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
