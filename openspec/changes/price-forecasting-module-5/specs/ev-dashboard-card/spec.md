## ADDED Requirements

### Requirement: EV controls live in a persisted tab inside the Energy Resources card
The Energy Resources card SHALL include a "Metrics | EV" tab switch when `has_ev_charger` is true. The "Metrics" tab SHALL show the existing resource metrics (including the at-a-glance EV summary line); the "EV" tab SHALL show the per-charger goal controls. The active tab SHALL be persisted in `localStorage` (reusing the ChartCard overlay-persistence pattern: a versioned key, migration, and a new-user default of `"metrics"`).

#### Scenario: EV tab only when a charger exists
- **WHEN** `has_ev_charger` is false
- **THEN** no EV tab SHALL be shown and the card SHALL render the metrics as today

#### Scenario: Active tab remembered across reloads
- **WHEN** the user selects the "EV" tab and reloads the page
- **THEN** the card SHALL reopen on the "EV" tab

#### Scenario: Metrics tab keeps the EV summary
- **WHEN** the "Metrics" tab is active
- **THEN** the at-a-glance EV line (plug state + today's kWh) SHALL still be visible

### Requirement: EV tab shows goal controls per charger (no modes)
For each configured charger, the EV tab SHALL render: a target SoC % slider (default 80), a ready-by time input, a repeat selector (Every day / Weekdays / Weekends / Every N days / Specific date), a date input shown only for "Specific date", a keep-charger-on-after-target checkbox, and an EV-before-battery priority checkbox. There SHALL be no "daily vs multi-day" mode dropdown. Changing any control SHALL call the schedule write API.

#### Scenario: Set a daily goal
- **WHEN** the user sets target 80%, ready-by 07:00, repeat "Every day"
- **THEN** the frontend SHALL call `POST /api/ev/chargers/{id}/schedule` with those values

#### Scenario: Specific-date goal
- **WHEN** the user selects repeat "Specific date"
- **THEN** a date input SHALL appear and SHALL be sent as `ready_by_date` with `repeat: none`

#### Scenario: Toggles
- **WHEN** the user toggles keep-charger-on or EV-before-battery priority
- **THEN** the frontend SHALL send `keep_on_after_target` / `charge_priority` on the next write

#### Scenario: Multiple chargers
- **WHEN** more than one charger is configured
- **THEN** the EV tab SHALL render an independent control block per charger

### Requirement: EV tab shows read-only progress and status
The EV tab SHALL display, per charger, a progress bar (`delivered_kwh / required_kwh`), today's quota when present, a status badge (`on_track` / `behind` / `complete` / `idle`), and the day-by-day `quota_schedule` when present.

#### Scenario: On-track goal
- **WHEN** the charger is progressing toward its target within the deadline
- **THEN** the badge SHALL read "On track" and the progress bar SHALL reflect delivered vs required

#### Scenario: Behind
- **WHEN** the ready-by has passed (or is unreachable) with energy still required
- **THEN** the badge SHALL read "Behind" and SHALL show the remaining kWh

#### Scenario: No spreading
- **WHEN** there is no multi-day quota schedule
- **THEN** the day-by-day schedule SHALL be hidden

### Requirement: EV tab indicates HA-driven values and missing HA entities
When a goal field is currently driven by Home Assistant (`source: "ha"`), the EV tab SHALL indicate that. When a goal is active but no HA entities are configured, the tab SHALL show a non-blocking tip about connecting HA helpers.

#### Scenario: HA-driven indicator
- **WHEN** a charger's goal `source` is `"ha"`
- **THEN** the tab SHALL show that the value comes from Home Assistant

#### Scenario: Tip when no HA entities
- **WHEN** a goal is active and the charger has no `ha_ready_by_entity` / `ha_target_soc_entity`
- **THEN** the tab SHALL show a subtle tip to connect HA helpers for automation/voice control
