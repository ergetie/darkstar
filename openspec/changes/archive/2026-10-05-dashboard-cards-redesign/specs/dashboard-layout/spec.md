## MODIFIED Requirements

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
