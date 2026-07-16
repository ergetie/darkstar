# Settings UX

## Purpose

Usability behaviors of the settings page: verifying notification configuration in place, seeing what unsaved changes would be discarded, and naming the heating-related tab to match what the system supports.

## Requirements

### Requirement: Notification configuration is testable from the settings page

The Settings UI tab's Notifications section SHALL provide a "Send Test Notification" control adjacent to the HA Notify Service field. Activating it SHALL call the existing `POST /api/executor/notifications/test` endpoint (no new backend path), SHALL show a busy state while the request is in flight, and SHALL surface the outcome (success or failure with the returned message) to the user. The Executor page's existing test button SHALL keep working and SHALL share the same API client method.

#### Scenario: Successful test from settings
- **WHEN** the user clicks "Send Test Notification" in the Settings UI tab and the endpoint returns success
- **THEN** a success indication is shown
- **AND** the notification was dispatched through the existing executor notification path

#### Scenario: Failing test surfaces the error
- **WHEN** the endpoint returns an error status or the request fails
- **THEN** the user sees a failure indication including the error message
- **AND** the button returns to its idle state

#### Scenario: Single shared client method
- **WHEN** the frontend code is inspected
- **THEN** the Settings button and the Executor page button call the same `lib/api.ts` method for this endpoint

### Requirement: Unsaved-changes dialog lists the changes being discarded

The navigation-blocker dialog SHALL display the list of changed fields (human-readable label with old and new values) computed from the same form-vs-config comparison semantics used to build save patches. The list SHALL be scroll-capped so many changes cannot break the dialog layout. With no changes provided, the dialog SHALL render as before.

#### Scenario: Dirty form shows field list
- **WHEN** the user edits two fields and triggers navigation away
- **THEN** the dialog lists both fields by label with their old and new values

#### Scenario: Diff list agrees with save semantics
- **WHEN** the form state would produce a non-empty save patch
- **THEN** the changed-fields list is non-empty for the same inputs (and vice versa)

#### Scenario: Many changes stay contained
- **WHEN** more fields changed than fit the dialog
- **THEN** the list scrolls within a capped height and the Stay/Discard buttons remain visible

### Requirement: Heating tab naming

The settings tab previously labeled "Water" SHALL be labeled "Heating". The tab's internal `id` (`'water'`), the `system.has_water_heater` visibility flag, and all configuration keys SHALL remain unchanged.

#### Scenario: Label changed, identity stable
- **WHEN** the settings page renders for a system with a water heater configured
- **THEN** the tab shows "Heating"
- **AND** deep links / persisted tab state referencing the `water` id still resolve to it
