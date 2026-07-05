## ADDED Requirements

### Requirement: Repeated action-command failures notify the operator

The executor SHALL send an operator notification via the dispatcher's `notify_error` path when an executor action of a given type fails on consecutive ticks and reaches a failure-streak threshold. The notification SHALL honor the existing `notifications.on_error` config gate. Each streak SHALL notify at most once (deduped per action type): the first tick at which the streak reaches the threshold notifies, and no further notification for that action type is sent until the streak is broken by a success (or the action stops being attempted).

#### Scenario: A failing action type crosses the streak threshold

- **WHEN** the same action type (e.g. `water_heat_start`) returns a non-skipped `ActionResult` with `success == False` on N consecutive ticks, where N is the configured streak threshold
- **THEN** the executor calls `dispatcher.notify_error` once with a message identifying the action type and the failure reason, and marks that action type as already-notified

#### Scenario: Notification is not repeated while the streak continues

- **WHEN** an action type has already notified for its current failure streak and continues to fail on subsequent ticks
- **THEN** no further notification is sent for that action type until the streak is reset

#### Scenario: Recovery resets the streak

- **WHEN** an action type that was failing returns a successful (or skipped) result on a later tick
- **THEN** its failure counter and already-notified flag are reset, so a future streak can notify again

#### Scenario: notifications.on_error is disabled

- **WHEN** `notifications.on_error` is false and an action-failure streak crosses the threshold
- **THEN** no push notification is sent (the existing `notify_error` gate is respected)

### Requirement: Execution log records a top-level failure reason

Every `execution_log` row written for a failed tick SHALL carry a non-null `error_message` containing a short human-readable summary of why the tick failed, derived from the per-action `action_results` detail at write time. Successful ticks SHALL leave `error_message` null.

#### Scenario: A tick with one or more failed actions

- **WHEN** a tick is recorded with aggregate `success == False` because one or more non-skipped actions failed
- **THEN** the row's `error_message` is a non-null summary naming the failed action type(s) and their failure message(s)

#### Scenario: A fully successful tick

- **WHEN** a tick is recorded with aggregate `success == True`
- **THEN** the row's `error_message` is null
