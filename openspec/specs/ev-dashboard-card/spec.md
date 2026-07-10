# ev-dashboard-card Specification

## Purpose
TBD - created by archiving change price-forecasting-module-5. Update Purpose after archive.
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
For each configured charger, the EV tab SHALL render: a target SoC % slider (default 80), a ready-by time input, a repeat selector (Every day / Weekdays / Weekends / Every N days / Specific date), a date input shown only for "Specific date", and a keep-charger-on-after-target checkbox. **No "EV-before-battery priority" checkbox** — surplus ordering is owned by the shipped `excess_pv.priority[]` list (home battery implicitly first via `soc_threshold_percent`). There SHALL be no "daily vs multi-day" mode dropdown. Changing any control SHALL call the schedule write API.

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

### Requirement: EV tab shows read-only progress and status
The EV tab SHALL display, per charger, a progress bar (`delivered_kwh / required_kwh`), today's quota when present, a status badge (`on_track` / `behind` / `complete` / `idle` / `paused_by_load_balancer`), and the day-by-day `quota_schedule` when present.

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

### Requirement: EV tab surfaces the Excess-PV priority-list prerequisite (surplus absorption off)
Surplus-PV absorption requires the charger to be listed as an `ev` entry in `excess_pv.priority[]` (configured under Settings → Advanced → "Excess PV Dispatch"). For a current-type charger not found in that list, the EV tab SHALL show a non-blocking hint "Surplus absorption off — add this charger to Excess PV priority" with a jump-link to that Advanced editor. The jump-link SHALL use client-side routing (React Router `Link`, honoring the router basename) so it works under HA Ingress; raw anchors that trigger full-page navigation are a defect. For a binary charger (which can never absorb surplus), the EV tab SHALL instead show an informational note that binary chargers cannot absorb surplus and that a current-type charger is required for free-PV charging.

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

### Requirement: Paused-by-load-balancer status wording
When the fuse balancer is currently throttling or shedding the EV (per-phase cap reached), the EV tab's status badge SHALL read "Paused by load balancer" rather than "behind on target", so the user understands the goal isn't failing — the fuse, a physical constraint, is the authority. The badge SHALL key on the balancer's actual per-EV states — `throttling`, `paused`, and `stale_fallback` — not on non-existent state names. `stale_fallback` (charging halted by the stale-sensor fail-safe) SHALL be surfaced as a paused-style badge, never as "on track". When headroom returns, the badge SHALL revert to the underlying goal status (`on_track` / `behind` / `complete` / `idle`).

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

### Requirement: Card state truthfully mirrors server state
The EV charging card SHALL derive its view/edit mode and displayed values from the current server-provided charger props on every render — never from a one-shot initialization. Specifically: when the server reports no goal, the card SHALL show the no-goal editing state (never a phantom goal built from local defaults); after a save, the card SHALL show the submitted values and SHALL NOT transiently revert to pre-save values while the refetch is in flight; fields cleared server-side SHALL reset locally rather than leaking into the next edit session; a failed charger fetch SHALL surface an error that is cleared on the next successful fetch; and concurrent fetches SHALL be guarded so a stale response never overwrites a newer one.

#### Scenario: Goal cleared elsewhere
- **WHEN** the goal is cleared from another browser or via HA and the card refreshes
- **THEN** the card SHALL show the "no goal" state (not a default 80%/07:00 goal with a progress bar)

#### Scenario: No revert flash after save
- **WHEN** the user saves target 90% and the refetch takes 2 seconds
- **THEN** the card SHALL display 90% throughout (no flash back to the previous value)

#### Scenario: Error state recovers
- **WHEN** one chargers fetch fails and a later fetch succeeds
- **THEN** the error message SHALL be replaced by the fetched content

### Requirement: All date logic uses the user's local calendar
Date defaults, "today" comparisons, and weekday labels in the EV card SHALL be computed in the browser's local timezone (and quota-schedule keys interpreted as planner-local dates). UTC-based helpers (`toISOString().slice(0,10)`, `new Date("YYYY-MM-DD")` for display) SHALL NOT be used for calendar logic.

#### Scenario: Default date near midnight
- **WHEN** a user in Europe/Stockholm opens the specific-date picker at 00:30 local time
- **THEN** the default "tomorrow" SHALL be the next local calendar day (not today)

#### Scenario: Today's quota chip highlighted
- **WHEN** the quota schedule contains an entry for the current local date
- **THEN** that entry SHALL be highlighted as today, including between local midnight and UTC midnight
