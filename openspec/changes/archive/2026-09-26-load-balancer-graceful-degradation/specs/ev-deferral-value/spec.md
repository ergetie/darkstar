## MODIFIED Requirements

### Requirement: Deferral risk margin is user-configurable and ramps toward the deadline
The deferral risk margin SHALL be a user-set base that grows linearly as the goal's deadline approaches:
- `ev_planning.deferral_risk_margin_percent` (base) SHALL default to 12 and SHALL accept values from 0 to 100.
- `ev_planning.deferral_risk_margin_max_percent` SHALL default to 50 and SHALL accept values from the base up to 200.
- `ev_planning.deferral_risk_ramp_hours` SHALL default to 48 and SHALL accept values from 1 to 168.
- On every planner run, for each charger with a goal, with `h` = hours from now to the deadline, the planner SHALL compute `effective_margin = base + (max − base) × clamp(1 − h / ramp_hours, 0, 1)`.
- The planner SHALL persist `effective_margin_percent` per charger alongside `deferral_price_source`.
- All three settings SHALL be editable in the EV settings tab, with help text explaining that a higher margin charges earlier and relies less on price forecasts, and that the margin rises from the base to the maximum over the ramp window before the deadline.
- The EV settings tab's "Goal Planning" section SHALL show an info box directly under its title that explains in plain language how Darkstar decides between charging now and waiting for cheaper forecast prices (published prices are optimised directly; later hours are priced at the published or forecast price plus the risk margin), what the risk margin and its ramp do, and what the shortfall penalty means.
- The info box SHALL start collapsed, showing only its title and a one-line summary; an accessible expand/collapse control SHALL reveal the full explanation.

#### Scenario: Default margin far from the deadline
- **WHEN** the settings are absent from config and the deadline is 72 h away
- **THEN** the effective margin SHALL be 12%

#### Scenario: Margin ramps as the deadline approaches
- **GIVEN** default settings
- **WHEN** the deadline is 24 h away
- **THEN** the effective margin SHALL be 31%
- **AND** when a later re-plan runs with the deadline 6 h away, the effective margin SHALL be 45.25%

#### Scenario: Ramp disabled
- **GIVEN** `deferral_risk_margin_max_percent` equals `deferral_risk_margin_percent`
- **WHEN** the deadline is 2 h away
- **THEN** the effective margin SHALL equal the base

#### Scenario: Out-of-range value rejected
- **WHEN** the user saves a base of 150, or a maximum below the base
- **THEN** config validation SHALL reject the value with an actionable error naming the key

#### Scenario: Goal Planning explains itself
- **WHEN** the user opens the EV settings tab
- **THEN** the "Goal Planning" section SHALL show an info box under its title covering charge-now-versus-wait, the risk margin and ramp, and the shortfall penalty
- **AND** the box SHALL initially show only a one-line summary, with the full text revealed by an expand control
