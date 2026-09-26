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
