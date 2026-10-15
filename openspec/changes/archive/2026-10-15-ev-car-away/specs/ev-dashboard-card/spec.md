## MODIFIED Requirements

### Requirement: Card indicates planned charging awaiting plug-in
When the server reports `assumed_plugged: true` for an unplugged charger with an active goal, the card SHALL show that charging is planned and awaiting plug-in, including the first planned charging time, and that the planned charging does not affect the house battery while the car is away.

#### Scenario: Unplugged car with a goal
- **WHEN** the charger is unplugged and the plan schedules goal charging from 22:00
- **THEN** the card SHALL show "Planned from 22:00 — plug in the car" (or equivalent wording)
- **AND** SHALL state that the house battery is not affected while the car is away

### Requirement: Single charger fills the EV tab with actions at the bottom
When exactly one charger is shown in the EV tab, its card SHALL fill the available height of the Energy Resources cell and its action buttons (Clear and Configure Goal) SHALL be pinned to the bottom. On desktop, the charger list SHALL fill the cell without increasing the height of the dashboard row, and SHALL scroll inside the cell when several chargers do not fit. A charger card's action buttons SHALL always be visible without scrolling; when the card's content does not fit, the content between the header and the buttons SHALL scroll inside the card and SHALL never be clipped unreachably.

#### Scenario: One charger
- **WHEN** one charger is shown
- **THEN** its card fills the cell and the action buttons sit at the bottom

#### Scenario: Several chargers
- **WHEN** several chargers do not fit in the cell on desktop
- **THEN** the list scrolls inside the cell and the dashboard row height is unchanged

#### Scenario: Single charger with content taller than the cell
- **WHEN** one charger is shown on desktop and its content is taller than the cell
- **THEN** the Clear Goal and Configure Goal buttons SHALL be fully visible at the bottom of the card
- **AND** the content above them SHALL scroll inside the card
- **AND** the dashboard row height SHALL be unchanged

#### Scenario: Editing a goal in a short cell
- **WHEN** the goal form is open and taller than the cell
- **THEN** the Save and Cancel buttons SHALL be fully visible and the form fields SHALL scroll
