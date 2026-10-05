## ADDED Requirements

### Requirement: Single charger fills the EV tab with actions at the bottom
When exactly one charger is shown in the EV tab, its card SHALL fill the available height of the Energy Resources cell and its action buttons (Clear and Configure Goal) SHALL be pinned to the bottom. On desktop, the charger list SHALL fill the cell without increasing the height of the dashboard row, and SHALL scroll inside the cell when several chargers do not fit.

#### Scenario: One charger
- **WHEN** one charger is shown
- **THEN** its card fills the cell and the action buttons sit at the bottom

#### Scenario: Several chargers
- **WHEN** several chargers do not fit in the cell on desktop
- **THEN** the list scrolls inside the cell and the dashboard row height is unchanged

### Requirement: EV card colours use theme tokens
Status badges, the HA-driven badge, the keep-enabled indicator and the surplus-PV hints on the EV card SHALL use design-system colour tokens (good, warn, water) rather than fixed palette colours, so they are readable in both light and dark themes. Text on gold (accent) buttons and the active tab of the Energy Resources card SHALL be dark in both themes.

#### Scenario: Hints readable in light mode
- **WHEN** the theme is light and the surplus-PV hint is shown
- **THEN** its text and border use the theme's warning or good colour and are readable on the light background

#### Scenario: Dark text on gold buttons
- **WHEN** the "Configure Goal" button is shown
- **THEN** its label uses the on-accent (dark) text colour
