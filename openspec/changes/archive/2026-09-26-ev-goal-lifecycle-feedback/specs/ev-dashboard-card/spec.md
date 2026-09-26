## MODIFIED Requirements

### Requirement: Card state truthfully mirrors server state
The EV charging card SHALL derive its view/edit mode and displayed values from the current server-provided charger props on every render — never from a one-shot initialization. Specifically: when the server reports no goal, the card SHALL show the no-goal editing state (never a phantom goal built from local defaults); after a save, the card SHALL show the submitted values and SHALL NOT transiently revert to pre-save values while the refetch is in flight; fields cleared server-side SHALL reset locally rather than leaking into the next edit session; a failed charger fetch SHALL surface an error that is cleared on the next successful fetch; and concurrent fetches SHALL be guarded so a stale response never overwrites a newer one. While the server reports `plan_pending: true` for a charger, the card SHALL show a "Re-planning…" indicator and SHALL NOT display plan-derived values from the previous plan (delivered/remaining, status badge, `planned_by_day` chips); the goal values themselves SHALL remain visible. When a planner failure is reported while a plan was pending, the card SHALL show that the re-plan failed and MAY show the previous plan's values marked as stale.

#### Scenario: Goal cleared elsewhere
- **WHEN** the goal is cleared from another browser or via HA and the card refreshes
- **THEN** the card SHALL show the "no goal" state (not a default 80%/07:00 goal with a progress bar)

#### Scenario: No revert flash after save
- **WHEN** the user saves target 90% and the refetch takes 2 seconds
- **THEN** the card SHALL display 90% throughout (no flash back to the previous value)

#### Scenario: Error state recovers
- **WHEN** one chargers fetch fails and a later fetch succeeds
- **THEN** the error message SHALL be replaced by the fetched content

#### Scenario: Re-planning after a save
- **WHEN** the user saves a new goal and the server reports `plan_pending: true`
- **THEN** the card SHALL show "Re-planning…" with the new goal values
- **AND** SHALL NOT show the previous plan's status badge, remaining need or `planned_by_day` chips

#### Scenario: New plan arrives
- **WHEN** `schedule_updated` is received and the refetch reports `plan_pending: false`
- **THEN** the card SHALL show the new plan's values and status

#### Scenario: Re-plan fails
- **WHEN** a `planner_error` is received while the card shows "Re-planning…"
- **THEN** the card SHALL show that the re-plan failed instead of the pending indicator

## ADDED Requirements

### Requirement: Card indicates planned charging awaiting plug-in
When the server reports `assumed_plugged: true` for an unplugged charger with an active goal, the card SHALL show that charging is planned and awaiting plug-in, including the first planned charging time.

#### Scenario: Unplugged car with a goal
- **WHEN** the charger is unplugged and the plan schedules goal charging from 22:00
- **THEN** the card SHALL show "Planned from 22:00 — plug in the car" (or equivalent wording)
