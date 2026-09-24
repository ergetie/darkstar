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
The CommandBar SHALL include a Run Planner button that triggers the planner and displays inline progress. The button SHALL call `Api.runPlanner()` then `Api.executor.run()`. Progress SHALL be tracked through phases: `starting → fetching_inputs → fetching_prices → applying_learning → running_solver → applying_schedule → complete / failed`. The button SHALL be disabled while planning is in progress.

#### Scenario: Planner button shows progress while running
- **WHEN** the user clicks the Run Planner button
- **THEN** the button shows a loading spinner and is disabled until the planner phase reaches `complete` or `failed`

#### Scenario: Planner button returns to normal after completion
- **WHEN** the planner phase reaches `complete`
- **THEN** the button returns to its default state and enables

---

### Requirement: Executor can be paused and resumed from the command bar
The CommandBar SHALL include a Pause/Resume button. When the executor is running, the button SHALL show a Pause action (green). When the executor is paused, the button SHALL show a Resume action (red, pulsing). Toggling SHALL call `Api.executor.pause()` or `Api.executor.resume()` accordingly, then call `onRefresh`.

#### Scenario: Pause button shown when executor is running
- **WHEN** `executorStatus.paused` is null
- **THEN** the button shows green with a Pause icon

#### Scenario: Resume button shown when executor is paused
- **WHEN** `executorStatus.paused` is not null
- **THEN** the button shows red with a pulsing ring and a Play icon

---

### Requirement: Auto scheduler can be toggled from the command bar
The CommandBar SHALL include an Auto toggle button that calls `onToggleScheduler` and reflects `automationConfig.enable_scheduler`. The button SHALL be disabled while `automationSaving` is true.

#### Scenario: Auto toggle shows correct on/off state
- **WHEN** the scheduler is enabled
- **THEN** the toggle shows "Auto: ON" with a green indicator dot

#### Scenario: Auto toggle disabled while saving
- **WHEN** `automationSaving` is true
- **THEN** the toggle is non-interactive

---

### Requirement: Risk appetite can be selected from the command bar
The CommandBar SHALL include a 5-level Risk pill selector (levels 1–5). Clicking a level SHALL call `onSetRiskAppetite(level)`. The active level SHALL be visually highlighted. Each level SHALL have a distinct color: 1=good, 2=night, 3=water, 4=warn, 5=ai.

#### Scenario: Selecting a risk level highlights it
- **WHEN** the user clicks risk level 3
- **THEN** pill 3 becomes highlighted and the others become inactive

---

### Requirement: Water comfort level can be selected from the command bar
The CommandBar SHALL include a 5-level Water comfort pill selector (levels 1–5). Clicking a level SHALL call `onSetComfortLevel(level)`. The active level SHALL be highlighted. Each level SHALL have a distinct color: 1=good, 2=night, 3=water, 4=warn, 5=bad.

#### Scenario: Selecting a comfort level highlights it
- **WHEN** the user clicks water comfort level 2
- **THEN** pill 2 becomes highlighted and the others become inactive

---

### Requirement: Top Up override can be activated and stopped from the command bar
The CommandBar SHALL include a Top Up button with the shared SoC stepper as target selector: − and + change the target by 15 percentage points, clamped to the configured `min_soc_percent`–100, and tapping the value opens an input where an exact integer in that range can be entered (invalid input is rejected and the previous value kept). When inactive, the user can adjust the target and activate by clicking "Top Up" (calls `Api.executor.quickAction.set('force_charge', …, { target_soc })`; the Top Up runs until the target SoC is reached, not for a fixed time). When active, the button shows "STOP" and clicking it calls `Api.executor.quickAction.clear()`. After any action, `onRefresh` is called.

#### Scenario: Top Up target selector is hidden when active
- **WHEN** `executorStatus.quick_action.type === 'force_charge'`
- **THEN** the stepper is hidden and only the "STOP" button is shown

#### Scenario: Clicking Stop deactivates Top Up
- **WHEN** the user clicks "STOP" on an active Top Up
- **THEN** `Api.executor.quickAction.clear()` is called and onRefresh is triggered

#### Scenario: Stepper increments by 15
- **GIVEN** the target is 50%
- **WHEN** the user presses +
- **THEN** the target becomes 65%, and pressing + at 95% gives 100%

#### Scenario: Exact value entry
- **WHEN** the user taps the value and enters 72
- **THEN** the target becomes 72%

---

### Requirement: EV Charge control in the command bar
The CommandBar SHALL include the EV Charge control defined by the `ev-manual-charge` capability, using the same shared SoC stepper as Top Up.

#### Scenario: Shared stepper
- **WHEN** the EV Charge control is shown
- **THEN** its target selector SHALL behave identically to the Top Up stepper

---

### Requirement: Water Boost override can be activated and stopped from the command bar
The CommandBar SHALL include a Boost button with a chevron-based duration selector (options: 30m, 1h, 2h). When inactive, clicking "Boost" calls `Api.waterBoost.start(duration)`. When active, the button shows "STOP", a countdown timer is displayed, and clicking stops the boost via `Api.waterBoost.cancel()`. The component SHALL subscribe to `water_boost_updated` WebSocket events to stay in sync with external boost state changes.

#### Scenario: Boost button shows countdown when active
- **WHEN** a water boost is active
- **THEN** the Boost button shows "STOP" with a countdown timer (m:ss format) and a pulsing flame icon

#### Scenario: Boost state syncs via WebSocket
- **WHEN** a `water_boost_updated` WebSocket event arrives
- **THEN** the boost active state and remaining seconds update without a manual refresh

---

### Requirement: Vacation mode override can be activated and stopped from the command bar
The CommandBar SHALL include a Vacation button with a chevron-based duration selector (options: 1, 3, 7, 14, 30 days). When inactive, clicking "Vacay" calls `Api.configSave` with vacation_mode enabled and a computed end date. When active, clicking "ON" disables vacation mode. After any change, `window.dispatchEvent(new Event('config-updated'))` SHALL be fired.

#### Scenario: Vacation button shows ON state when active
- **WHEN** `vacationMode || vacationModeHA` is true
- **THEN** the Vacation button shows "ON" with amber highlighting, and the duration selector is hidden

---

### Requirement: Status badge shows plan freshness and next run
The CommandBar SHALL display a status badge on the right showing a summary of the last planned schedule and the next scheduled run time. The badge SHALL be derived from `plannerMeta` and `schedulerStatus`.

#### Scenario: Status badge is always visible
- **WHEN** the user views the dashboard
- **THEN** the status badge is visible in the right group of the command bar
