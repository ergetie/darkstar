## ADDED Requirements

### Requirement: Mobile chart slot selection panel
On mobile viewports (below Tailwind `md` / < 768 px), `ChartCard` SHALL disable the Chart.js floating overlay tooltip and replace it with a tap-driven slot selection model. Tapping a slot SHALL select it, drawing a full-height vertical selection band with an amber accent line at that slot. When a slot is selected, the card SHALL expand downward to reveal an inset panel below the chart timeline showing that slot's values: a time heading and each visible series' formatted value, including the spot + tax/fees price breakdown using the same formatting as the prior tooltip. Desktop hover-tooltip behavior SHALL remain unchanged.

#### Scenario: Mobile tap selects slot and shows panel
- **WHEN** a user on a mobile viewport (< 768 px) taps a slot on the schedule chart
- **THEN** a vertical selection band appears at that slot and an inset values panel is revealed below the chart timeline showing the slot's time and series values

#### Scenario: Mobile tap outside card clears selection
- **WHEN** a user on a mobile viewport taps outside the `ChartCard` while a slot is selected
- **THEN** the selection band disappears, the inset panel collapses, and the card returns to its normal height

#### Scenario: Mobile floating overlay tooltip is not used
- **WHEN** a user on a mobile viewport (< 768 px) interacts with the schedule chart
- **THEN** no Chart.js floating overlay tooltip is shown at any time

#### Scenario: Desktop behavior is unchanged
- **WHEN** a user on a desktop viewport (≥ 768 px) hovers over the schedule chart
- **THEN** the existing Chart.js floating tooltip is shown and no selection band or inset panel is rendered

#### Scenario: Selection clears on data refresh
- **WHEN** chart data refreshes while a slot is selected on mobile
- **THEN** the selection is cleared, the band disappears, and the panel collapses
