# ev-dashboard-card Specification

## Purpose
Define the EV controls on the dashboard Energy Resources card: the persisted Metrics/EV tab, per-charger goal controls, progress and status display, and at-risk and prerequisite hints, so users can set and monitor EV charging goals.
## Requirements
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
For each configured charger, the EV tab SHALL render: a target SoC % slider (default 80), a ready-by time input, a repeat selector (Every day / Weekdays / Weekends / Every N days / Specific date), a date input shown only for "Specific date", and a keep-charger-on-after-target checkbox. **No "EV-before-battery priority" checkbox** — surplus ordering is owned by the shipped `excess_pv.priority[]` list (home battery implicitly first via `soc_threshold_percent`).

#### Scenario: Set a daily goal
- **WHEN** the user sets target 80%, ready-by 07:00, repeat "Every day"
- **THEN** the frontend SHALL call `POST /api/ev/chargers/{id}/schedule` with those values

#### Scenario: Specific-date goal
- **WHEN** the user selects repeat "Specific date"
- **THEN** a date input SHALL appear and SHALL be sent as `ready_by_date` with `repeat: none`

#### Scenario: Keep-on-after-target toggle
- **WHEN** the user toggles keep-charger-on-after-target
- **THEN** the frontend SHALL send `keep_on_after_target` on the next write

#### Scenario: Multiple chargers
- **WHEN** more than one charger is configured
- **THEN** the EV tab SHALL render an independent control block per charger

#### Scenario: No mode dropdown and controls write the schedule
- **WHEN** the EV tab renders a charger's controls
- **THEN** there SHALL be no "daily vs multi-day" mode dropdown
- **AND** changing any control SHALL call the schedule write API

### Requirement: EV tab shows read-only progress and status
The EV tab SHALL display, per charger, a progress bar, a Delivered Today value, a status badge and a planned per-day estimate, as specified in the scenarios below.

#### Scenario: On-track goal
- **WHEN** the charger is progressing toward its target within the deadline
- **THEN** the badge SHALL read "On track" and the progress bar SHALL reflect SoC relative to target

#### Scenario: Delivered exceeds remaining need
- **WHEN** Delivered Today is 22 kWh but SoC is 50% with an 80% target
- **THEN** the progress SHALL be below 100% and consistent with the remaining need

#### Scenario: Goal complete
- **WHEN** SoC is at or above target
- **THEN** the badge SHALL read "Complete" and progress SHALL be 100%, without showing a "Target 0.0 kWh (0% of goal)" label

#### Scenario: Behind
- **WHEN** the ready-by has passed (or is unreachable) with energy still required
- **THEN** the badge SHALL read "Behind" and SHALL show the remaining kWh

#### Scenario: Mixed known and estimated days
- **WHEN** `planned_by_day` has today `known` 0 kWh, tomorrow `known` 8 kWh, and D+2 `estimated` 14 kWh
- **THEN** three chips SHALL render; the first two solid and the third de-emphasised with "est."

#### Scenario: No goal or no plan
- **WHEN** `planned_by_day` is empty or absent
- **THEN** the per-day section SHALL be hidden

#### Scenario: Progress bar computation
- **WHEN** the EV tab shows a charger's progress
- **THEN** the progress bar and percent SHALL be computed as current SoC divided by the target SoC (clamped 0-100%) for chargers with a SoC sensor, and as delivered kWh divided by required kWh (clamped 0-100%) for chargers without one
- **AND** the bar SHALL never show 100% from missing data

#### Scenario: Delivered Today and status badge
- **WHEN** the EV tab shows a charger's status
- **THEN** it SHALL show "Delivered Today" as an informational kWh value that does not drive the progress bar for chargers with SoC
- **AND** it SHALL show a status badge (`on_track` / `behind` / `complete` / `idle` / `paused_by_load_balancer`)

#### Scenario: Planned per-day chips
- **WHEN** the EV tab shows the planned per-day estimate from `planned_by_day`
- **THEN** it SHALL render one chip per day from today through the deadline day, showing the planned kWh
- **AND** chips with `basis: "known"` SHALL render solid
- **AND** chips with `basis: "estimated"` SHALL render visually de-emphasised with an "est." label and a tooltip explaining that the value is based on forecast prices
- **AND** today's chip SHALL be highlighted
- **AND** the section title SHALL read "Planned per day", not "Upcoming Daily Quotas"

### Requirement: EV tab indicates HA-driven values and missing HA entities
When a goal field is currently driven by Home Assistant (`source: "ha"`), the EV tab SHALL indicate that. When a goal is active but no HA entities are configured, the tab SHALL show a non-blocking tip about connecting HA helpers.

#### Scenario: HA-driven indicator
- **WHEN** a charger's goal `source` is `"ha"`
- **THEN** the tab SHALL show that the value comes from Home Assistant

#### Scenario: Tip when no HA entities
- **WHEN** a goal is active and the charger has no `ha_ready_by_entity` / `ha_target_soc_entity`
- **THEN** the tab SHALL show a subtle tip to connect HA helpers for automation/voice control

### Requirement: EV tab surfaces the Excess-PV priority-list prerequisite (surplus absorption off)
Surplus-PV absorption requires the charger to be listed as an `ev` entry in `excess_pv.priority[]` (configured under Settings → Advanced → "Excess PV Dispatch"). For a current-type charger not found in that list, the EV tab SHALL show a non-blocking hint "Surplus absorption off — add this charger to Excess PV priority" with a jump-link to that Advanced editor.

#### Scenario: Current-type charger missing from priority list
- **WHEN** a configured current-type charger is not referenced by any entry in `excess_pv.priority[]`
- **THEN** the EV tab SHALL show the "Surplus absorption off" hint with a jump-link to the Advanced "Excess PV Dispatch" editor

#### Scenario: Jump-link works under HA Ingress
- **WHEN** the app is served under an HA Ingress path prefix and the user clicks the jump-link
- **THEN** navigation SHALL stay within the app (client-side route including the basename), not a full-page load to an absolute `/settings` URL

#### Scenario: Binary charger shown an informational limit
- **WHEN** a configured charger has `type: binary`
- **THEN** the EV tab SHALL display an informational note that binary chargers cannot absorb surplus (a current-type charger is required) and SHALL NOT show the "add to Excess PV priority" jump-link

#### Scenario: Current-type charger already in priority list
- **WHEN** a configured current-type charger is referenced by an `ev` entry in `excess_pv.priority[]`
- **THEN** the EV tab SHALL show no surplus hint (absorption is on)

#### Scenario: Jump-link uses client-side routing
- **WHEN** the EV tab shows the jump-link to the Advanced editor
- **THEN** the jump-link SHALL use client-side routing (React Router `Link`, honoring the router basename) so it works under HA Ingress
- **AND** raw anchors that trigger full-page navigation are a defect

#### Scenario: Binary charger surplus note
- **WHEN** the EV tab shows a binary charger (which can never absorb surplus)
- **THEN** it SHALL instead show an informational note that binary chargers cannot absorb surplus and that a current-type charger is required for free-PV charging

### Requirement: Paused-by-load-balancer status wording
When the fuse balancer is currently throttling or shedding the EV (per-phase cap reached), the EV tab's status badge SHALL read "Paused by load balancer" rather than "behind on target", so the user understands the goal isn't failing — the fuse, a physical constraint, is the authority.

#### Scenario: Balancer actively throttling the EV
- **WHEN** the load balancer reports state `throttling` for this charger
- **THEN** the badge SHALL show "Paused by load balancer" (blue)
- **AND** the underlying goal progress SHALL continue to be tracked but not surfaced as "behind"

#### Scenario: Stale-sensor fail-safe active
- **WHEN** the load balancer reports state `stale_fallback` for this charger
- **THEN** the badge SHALL indicate the balancer has paused charging (not "On track")

#### Scenario: Headroom recovers
- **WHEN** the balancer resumes the EV (headroom healthy)
- **THEN** the badge SHALL revert to the underlying `on_track` / `behind` / `complete` / `idle` status

#### Scenario: Badge keyed on actual balancer states
- **WHEN** the badge reflects the load balancer's state
- **THEN** it SHALL key on the balancer's actual per-EV states (`throttling`, `paused`, and `stale_fallback`), not on non-existent state names
- **AND** `stale_fallback` (charging halted by the stale-sensor fail-safe) SHALL be surfaced as a paused-style badge, never as "on track"

#### Scenario: Badge reverts when headroom returns
- **WHEN** headroom returns
- **THEN** the badge SHALL revert to the underlying goal status (`on_track` / `behind` / `complete` / `idle`)

### Requirement: Card state truthfully mirrors server state
The EV charging card SHALL derive its view/edit mode and displayed values from the current server-provided charger props on every render — never from a one-shot initialization.

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

#### Scenario: Card state derived from server props
- **WHEN** the EV charging card renders
- **THEN** when the server reports no goal, the card SHALL show the no-goal editing state (never a phantom goal built from local defaults)
- **AND** after a save, the card SHALL show the submitted values and SHALL NOT transiently revert to pre-save values while the refetch is in flight
- **AND** fields cleared server-side SHALL reset locally rather than leaking into the next edit session

#### Scenario: Fetch errors and concurrent fetches
- **WHEN** the card fetches charger data
- **THEN** a failed charger fetch SHALL surface an error that is cleared on the next successful fetch
- **AND** concurrent fetches SHALL be guarded so a stale response never overwrites a newer one

#### Scenario: Re-planning indicator while plan is pending
- **WHEN** the server reports `plan_pending: true` for a charger
- **THEN** the card SHALL show a "Re-planning…" indicator
- **AND** it SHALL NOT display plan-derived values from the previous plan (delivered/remaining, status badge, `planned_by_day` chips)
- **AND** the goal values themselves SHALL remain visible

#### Scenario: Planner failure while plan was pending
- **WHEN** a planner failure is reported while a plan was pending
- **THEN** the card SHALL show that the re-plan failed
- **AND** it MAY show the previous plan's values marked as stale

### Requirement: All date logic uses the user's local calendar
Date defaults, "today" comparisons, and weekday labels in the EV card SHALL be computed in the browser's local timezone (and quota-schedule keys interpreted as planner-local dates). UTC-based helpers (`toISOString().slice(0,10)`, `new Date("YYYY-MM-DD")` for display) SHALL NOT be used for calendar logic.

#### Scenario: Default date near midnight
- **WHEN** a user in Europe/Stockholm opens the specific-date picker at 00:30 local time
- **THEN** the default "tomorrow" SHALL be the next local calendar day (not today)

#### Scenario: Today's quota chip highlighted
- **WHEN** the quota schedule contains an entry for the current local date
- **THEN** that entry SHALL be highlighted as today, including between local midnight and UTC midnight

### Requirement: Card indicates planned charging awaiting plug-in
When the server reports `assumed_plugged: true` for an unplugged charger with an active goal, the card SHALL show that charging is planned and awaiting plug-in, including the first planned charging time, and that the planned charging does not affect the house battery while the car is away.

#### Scenario: Unplugged car with a goal
- **WHEN** the charger is unplugged and the plan schedules goal charging from 22:00
- **THEN** the card SHALL show "Planned from 22:00 — plug in the car" (or equivalent wording)
- **AND** SHALL state that the house battery is not affected while the car is away

### Requirement: Single charger fills the EV tab with actions at the bottom
When exactly one charger is shown in the EV tab, its card SHALL fill the available height of the Energy Resources cell and its action buttons (Clear and Configure Goal) SHALL be pinned to the bottom.

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

#### Scenario: Charger list sizing on desktop
- **WHEN** the EV tab is displayed on desktop
- **THEN** the charger list SHALL fill the cell without increasing the height of the dashboard row
- **AND** it SHALL scroll inside the cell when several chargers do not fit

#### Scenario: Action buttons always visible
- **WHEN** a charger card's content does not fit
- **THEN** the action buttons SHALL always be visible without scrolling
- **AND** the content between the header and the buttons SHALL scroll inside the card and SHALL never be clipped unreachably

### Requirement: EV card colours use theme tokens
Status badges, the HA-driven badge, the keep-enabled indicator and the surplus-PV hints on the EV card SHALL use design-system colour tokens (good, warn, water) rather than fixed palette colours, so they are readable in both light and dark themes. Text on gold (accent) buttons and the active tab of the Energy Resources card SHALL be dark in both themes.

#### Scenario: Hints readable in light mode
- **WHEN** the theme is light and the surplus-PV hint is shown
- **THEN** its text and border use the theme's warning or good colour and are readable on the light background

#### Scenario: Dark text on gold buttons
- **WHEN** the "Configure Goal" button is shown
- **THEN** its label uses the on-accent (dark) text colour
