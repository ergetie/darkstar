# Spec: Schedule Fallback Alerting

## Purpose
Make the executor's idle fallback visible whenever there is no valid schedule, whatever the cause.

## Requirements

### Requirement: Alert on every no-valid-schedule cause
The executor SHALL send one error notification per valid-to-invalid transition when the schedule file is missing, unreadable, empty, lacks `generated_at`, or is stale, and SHALL re-arm when a valid slot is found again.

#### Scenario: Missing file
- **WHEN** the schedule file does not exist on a tick
- **THEN** one error notification is sent and subsequent ticks do not repeat it

#### Scenario: Cause changes while invalid
- **WHEN** the schedule goes from stale to deleted
- **THEN** no second notification is sent

#### Scenario: Recovery re-arms
- **WHEN** a valid slot is found and the schedule later becomes invalid again
- **THEN** a new notification is sent

### Requirement: Warning state reset on every path
The stale-schedule warning SHALL be cleared at the start of every schedule load so it never persists after the cause is gone.

#### Scenario: Stale then deleted then restored
- **WHEN** the schedule was stale, then deleted, then replaced with a fresh one
- **THEN** no warning remains and the tick is counted

### Requirement: Accurate wording
Messages SHALL read "no valid schedule, idle fallback" and SHALL NOT say "holding".

#### Scenario: Stale text
- **WHEN** the schedule is 3.0 hours old with a 2 hour limit
- **THEN** the message contains "no valid schedule, idle fallback"
