## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: EV Charge control in the command bar
The CommandBar SHALL include the EV Charge control defined by the `ev-manual-charge` capability, using the same shared SoC stepper as Top Up.

#### Scenario: Shared stepper
- **WHEN** the EV Charge control is shown
- **THEN** its target selector SHALL behave identically to the Top Up stepper
