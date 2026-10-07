# Command Bar

## Purpose

TBD - Defines the CommandBar component that provides execution controls, parameter selectors, override actions, and status display for the dashboard.
## Requirements
### Requirement: CommandBar renders as a single full-width card
The `CommandBar` component (`frontend/src/components/CommandBar.tsx`) SHALL render as a single full-width card with three horizontally arranged groups: execution controls (left), parameter selectors and override actions (center), status badge (right).

#### Scenario: All three groups are visible on large screens
- **WHEN** the user views the dashboard on a large screen
- **THEN** the left, center, and right groups are displayed horizontally in one row

#### Scenario: Groups wrap on small screens
- **WHEN** the user views the dashboard on a small screen
- **THEN** the groups wrap to multiple lines rather than overflowing

---

### Requirement: Planner can be run from the command bar
The CommandBar SHALL include a Run Planner button that triggers the planner and displays inline progress. The button SHALL call `Api.runPlanner()` then `Api.executor.run()`. Progress SHALL be tracked through phases: `starting → fetching_inputs → fetching_prices → applying_learning → running_solver → applying_schedule → complete / failed`. The button SHALL be disabled while planning is in progress. The button SHALL reflect planner runs started by the server (goal changes, plug events, scheduler) through the same progress events, and SHALL handle the `planner_error` event by showing the failed state and surfacing the error message to the user.

#### Scenario: Planner button shows progress while running
- **WHEN** the user clicks the Run Planner button
- **THEN** the button shows a loading spinner and is disabled until the planner phase reaches `complete` or `failed`

#### Scenario: Planner button returns to normal after completion
- **WHEN** the planner phase reaches `complete`
- **THEN** the button returns to its default state and enables

#### Scenario: Server-started run spins the button
- **WHEN** a goal save triggers a planner run on the server
- **THEN** the button SHALL show the spinner and progress until the run completes or fails

#### Scenario: Planner error is surfaced
- **WHEN** a `planner_error` event is received
- **THEN** the button SHALL show the failed state
- **AND** the error message SHALL be shown to the user (for example as an error toast)

### Requirement: Executor can be paused and resumed from the command bar
The CommandBar SHALL include a Pause/Resume button. When the executor is running, the button SHALL show a Pause action (green). When the executor is paused, the button SHALL show a Resume action (red, pulsing). Toggling SHALL call `Api.executor.pause()` or `Api.executor.resume()` accordingly, then call `onRefresh`.

#### Scenario: Pause button shown when executor is running
- **WHEN** `executorStatus.paused` is null
- **THEN** the button shows green with a Pause icon

#### Scenario: Resume button shown when executor is paused
- **WHEN** `executorStatus.paused` is not null
- **THEN** the button shows red with a pulsing ring and a Play icon

---

### Requirement: Quick actions open a popover
Every command bar control apart from Run Planner and Pause (Risk, Water, Top Up, EV Charge, Boost, Vacation) SHALL be a single `QuickAction` button (`components/ui/QuickAction.tsx`) showing an icon, a label and its current value. Tapping it SHALL open a popover holding the action's settings. On viewports narrower than 640px the popover SHALL be a bottom sheet. The popover SHALL close on its close button, on Escape and on a tap outside it. An active action SHALL show a filled button with its live status (target or countdown), and its popover SHALL offer a Stop action. Touch targets SHALL be at least 44px high on mobile.

#### Scenario: Opening a quick action
- **WHEN** the user taps the Top Up button
- **THEN** a dialog titled "Battery Top Up" opens with the target presets and a Start button

#### Scenario: Closing with Escape
- **WHEN** a quick action popover is open and the user presses Escape
- **THEN** the popover closes

---

### Requirement: Risk appetite can be selected from the command bar
The CommandBar SHALL include a Risk button showing the current level and name (e.g. "Risk 3 · Neutral"). Its popover SHALL list levels 1–5 with name and a short hint, each with a distinct color: 1=good, 2=night, 3=water, 4=warn, 5=ai. Tapping a level SHALL call `onSetRiskAppetite(level)` and close the popover.

#### Scenario: Selecting a risk level
- **WHEN** the user opens Risk and taps "Aggressive"
- **THEN** `onSetRiskAppetite(4)` is called and the popover closes

---

### Requirement: Water comfort level can be selected from the command bar
The CommandBar SHALL include a Water button showing the current comfort level and name. Its popover SHALL list levels 1–5 with name and hint, each with a distinct color: 1=good, 2=night, 3=water, 4=warn, 5=bad. Tapping a level SHALL call `onSetComfortLevel(level)` and close the popover.

#### Scenario: Selecting a comfort level
- **WHEN** the user opens Water and taps "Economy"
- **THEN** `onSetComfortLevel(1)` is called

---

### Requirement: Top Up override can be activated and stopped from the command bar
The Top Up popover SHALL offer target presets 40/60/80/100% (presets below the configured `min_soc_percent` hidden) and the shared SoC stepper for a custom target (− / + change by 15 percentage points, clamped to `min_soc_percent`–100; tapping the value allows typing an exact integer, invalid input keeps the previous value). The default target SHALL be 60%. "Start Top Up to X%" SHALL call `Api.executor.quickAction.set('force_charge', …, { target_soc })`; the Top Up runs until the target SoC is reached, not for a fixed time. When active, the button SHALL show "→ target%" and the popover SHALL offer "Stop Top Up", which calls `Api.executor.quickAction.clear()`. After any action, `onRefresh` is called.

#### Scenario: Top Up target selector is hidden when active
- **WHEN** `executorStatus.quick_action.type === 'force_charge'`
- **THEN** the popover shows the status and a Stop button, without presets or stepper

#### Scenario: Stepper increments by 15
- **GIVEN** the target is 60%
- **WHEN** the user presses +
- **THEN** the target becomes 75%, and pressing + at 95% gives 100%

---

### Requirement: EV Charge control in the command bar
The CommandBar SHALL include the EV Charge control defined by the `ev-manual-charge` capability as a quick action. Its popover SHALL offer a charger selector (only with more than one candidate charger), target presets 40/60/80/100% plus the shared SoC stepper (default 60%), and for current-type chargers a charging current selector defaulting to "Charger maximum" (no `current_a` sent).

#### Scenario: Custom charging current
- **WHEN** the user selects 10 A and starts charging
- **THEN** `Api.ev.manualCharge.start` is called with `current_a: 10`

---

### Requirement: Water Boost override can be activated and stopped from the command bar
The Boost popover SHALL offer presets 30m, 1h, 2h (default 1h) plus a custom duration stepper (15–360 minutes in 15-minute steps; typed values are rounded to the nearest step) and, with more than one water heater, a heater selector. Starting calls `Api.waterBoost.start(duration)` (or `startFor` for a selected heater). When active, the button SHALL show a countdown (m:ss) with a pulsing flame icon, and the popover SHALL offer "Stop Boost", which calls `Api.waterBoost.cancel()`. The component SHALL subscribe to `water_boost_updated` WebSocket events to stay in sync with external boost state changes.

#### Scenario: Boost state syncs via WebSocket
- **WHEN** a `water_boost_updated` WebSocket event arrives
- **THEN** the boost active state and remaining seconds update without a manual refresh

---

### Requirement: Vacation mode override can be activated and stopped from the command bar
The Vacation popover SHALL offer presets of 1, 3, 7, 14, 30 days (default 3) and a custom day stepper (1–365, step 1, tap to type). Starting calls `Api.configSave` with vacation_mode enabled and a computed end date. When active, the button SHALL show "On" and the popover SHALL offer "Turn off Vacation Mode". After any change, `window.dispatchEvent(new Event('config-updated'))` SHALL be fired.

#### Scenario: Custom vacation length
- **WHEN** the user types 10 in the custom stepper
- **THEN** the start button reads "Start Vacation (10 days)"

---

### Requirement: Status badge shows plan freshness and next run
The CommandBar SHALL display a plan status on the right, derived from `plannerMeta`, `schedulerStatus` and `automationConfig`, using icons (no emoji). It SHALL show two aligned rows at the same text size: "Last" with the time of the latest plan (muted; "No plan yet" in warn color if none) and "Next" with the next scheduled run (emphasized; "Auto off" in warn color when the scheduler is disabled). The plan SHALL be marked outdated (warn icon and " · outdated") when it is older than 3 scheduler intervals, or 180 minutes when the interval is unknown. The status SHALL re-evaluate every minute. A tooltip SHALL show the full last and next run times.

#### Scenario: Status badge is always visible
- **WHEN** the user views the dashboard
- **THEN** the plan status is visible in the command bar

#### Scenario: Outdated plan
- **GIVEN** the scheduler runs every 15 minutes
- **WHEN** the last plan is 50 minutes old
- **THEN** the Last time is shown in warn color with " · outdated"

### Requirement: Grid domain displays a consistent estimated battery comparison
The dashboard Grid domain SHALL retain actual metered electricity costs prominently and SHALL display every amount-bearing battery comparison on a consistent economic basis as one compact line, "Darkstar saved you X kr" (or "Darkstar cost you extra X kr" when negative), with an “Estimate” chip for a configured-loss result or a “Verified” chip for a result whose strict fitted model passed the calibration and selected-period checks, as defined by grid-financial-wear-display. The two raw comparison costs SHALL NOT be shown inline. The cost chart SHALL be a single chart with the solid Actual line and, when comparison amounts exist, a dotted “Without Darkstar” line on the same kr scale; there SHALL be no Actual/Comparison view switch. The gap between the lines at the last comparison point SHALL match the displayed saving within rounding for a fully covered period. The UI SHALL NOT use legacy baseline savings as a fallback or present a configured-loss estimate as verified.

#### Scenario: Available configured-loss estimate
- **WHEN** the comparison has status estimated, basis configured_losses, self-use cost 40 kr and Darkstar cost 30 kr
- **THEN** the UI shows "Darkstar saved you 10.00 kr" with an “Estimate” chip
- **AND** the dotted Without Darkstar line ends 10 kr from the Actual line
- **AND** actual metered electricity cost remains separately identifiable

#### Scenario: Negative comparison
- **WHEN** a comparison on either active basis has a negative saving
- **THEN** the UI shows "Darkstar cost you extra" with the amount and the chip for the active basis

### Requirement: Battery comparison assumptions and unavailable states are understandable
The comparison details panel (opened from the chip's info control) SHALL expose its latest completed time and an explanation that EV charging/water heating retain recorded timings, self-use storage serves only house/water demand and remaining PV may supply EV energy, losses are modeled on both sides according to the active basis, wear and energy left in the battery are included, and 15-minute observations cannot reproduce exact sub-slot inverter response. When coverage is partial it SHALL state how many completed slots were covered and left out. A nested fold-down SHALL expose grid cost, wear, stored-energy value and the common valuation price. The UI SHALL NOT claim full Darkstar savings or guaranteed conservative savings. When a configured-loss estimate is shown, it SHALL identify the estimate basis (Estimate chip) and the panel SHALL explain the underlying calibration state in a short plain sentence without suggesting validation passed. When no supported estimate can be produced for the selected period, it SHALL show one plain-language reason with no saving amount or comparison line; actual information SHALL remain visible. A calibration state alone SHALL NOT suppress a valid configured-loss estimate. No-battery installations SHALL hide comparison controls. Shared cost-chart changes SHALL be visually verified on Dashboard and Design System using existing design tokens, across mobile/desktop and light/dark themes.

#### Scenario: Fixed controlled loads
- **WHEN** the user opens the details panel
- **THEN** it states that recorded EV/water schedules are shared, storage supplies only non-EV demand, remaining PV may supply the EV, and scheduling savings are excluded

#### Scenario: Unreliable calibration with a usable estimate
- **WHEN** comparison status is estimated and its calibration status is unreliable_model
- **THEN** the UI shows the Estimate chip, explains the calibration state plainly in the panel and shows actual costs separately
- **AND** it does not claim that the estimate passed validation

#### Scenario: No battery
- **WHEN** no battery is configured
- **THEN** the user sees the actual chart with no battery-comparison line or controls

### Requirement: Grid domain explains trustworthy history availability
The Grid domain SHALL distinguish collecting trustworthy compatible history, an unsupported selected period and a numerical accuracy failure through one short plain-language reason. It SHALL keep actual electricity costs visible and omit unavailable saving amounts and comparison lines. It SHALL NOT blame hardware, instruct users to weaken checks, expose internal provenance terminology or present configured-loss estimates as if they were verified. Copy and fixtures SHALL follow the existing design system.

#### Scenario: Collecting trustworthy history
- **WHEN** reason is `unverified_history` or `insufficient_compatible_history`
- **THEN** the UI explains that the battery comparison needs more trustworthy energy history
- **AND** it does not describe this as a failed accuracy check

#### Scenario: Unsupported period readings
- **WHEN** reason is `unsupported_period_measurements`
- **THEN** the UI explains that this period includes readings the comparison cannot reliably use

#### Scenario: Model accuracy failure
- **WHEN** sufficient trustworthy data fails numeric validation and no usable configured-loss estimate exists
- **THEN** the UI retains the accuracy-failure explanation without an estimated saving

### Requirement: Grid comparison labels the active basis
When comparison amounts are present, the Grid domain SHALL label configured-loss results with an “Estimate” chip and calibrated results with a “Verified” chip. The details panel SHALL describe the calibration state beside an estimate without suggesting that the estimate passed validation. A period with any excluded slot SHALL NOT be labelled “Verified”. Saving amounts and the dotted chart comparison line SHALL all reflect the same active basis. Unavailable-period copy SHALL continue to explain missing or unsupported usable data plainly.

#### Scenario: Configured-loss result
- **WHEN** comparison amounts use configured losses
- **THEN** the line identifies the values as an Estimate and the panel notes that configured battery losses are used

#### Scenario: Verified result
- **WHEN** comparison amounts use the validated fitted model
- **THEN** the UI identifies the result as verified

#### Scenario: Learning reason accompanies estimate
- **WHEN** estimated amounts are available while history is insufficient or calibration is unreliable
- **THEN** the UI shows the Estimate chip and the panel's concise calibration sentence together
