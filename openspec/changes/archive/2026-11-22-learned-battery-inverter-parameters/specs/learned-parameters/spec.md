## Purpose

Defines how Darkstar stores, validates, applies, expires, locks and reports values it learns about the user's own hardware, so a learned value is always evidenced, bounded, visible, reversible and never silently stale.

## ADDED Requirements

### Requirement: Learned values live outside config.yaml with evidence and history
Each learned parameter SHALL be stored in the learning database with its learned value, confidence (0 to 1), evidence (data window, row counts and the figures the estimate used), the time of the last successful estimate, the time the applied value last changed, and its lock state. Every applied change, expiry, recovery and lock change SHALL add a history row with old value, new value, confidence and evidence. Learning SHALL NOT write `config.yaml`.

#### Scenario: Value stored with evidence
- **WHEN** an estimate is accepted
- **THEN** the stored row holds the value, confidence, window start and end, the slot count and the time of the estimate
- **AND** a history row records the old and new value

#### Scenario: Config untouched
- **WHEN** a learning run applies, expires or restores any value
- **THEN** the bytes of `config.yaml` are unchanged

### Requirement: Estimates need enough data and plausible values
An estimate SHALL be used only when its minimum-data gate and its confidence threshold are met and its value lies inside the parameter's physical bounds. An estimate outside the bounds SHALL be rejected, not clamped. A rejected or gated-out estimate SHALL leave the stored value unchanged and SHALL NOT refresh its last-estimate time.

#### Scenario: Not enough data
- **WHEN** the data gate of a parameter is not met
- **THEN** no value is stored or changed and the reason is available as evidence in the API

#### Scenario: Implausible estimate
- **WHEN** an estimate falls outside the physical bounds
- **THEN** it is rejected, the previous value stays, and the rejection is visible in the evidence

### Requirement: Applied values move in bounded steps with a deadband
The first accepted value SHALL be adopted directly. Later updates SHALL move the stored value toward the estimate by at most the parameter's maximum step per update, and SHALL be skipped when the difference to the stored value is below the parameter's deadband. At most one update per parameter SHALL be applied per local day.

#### Scenario: Step limit
- **WHEN** the estimate differs from the stored value by more than the maximum step
- **THEN** the stored value moves by exactly the maximum step toward the estimate

#### Scenario: Deadband
- **WHEN** the estimate differs from the stored value by less than the deadband
- **THEN** the stored value and the applied-change time stay unchanged and no history row or notification is created

### Requirement: Learned values expire and fall back to config
A learned value SHALL be used only while its last successful estimate is at most 30 days old. After that its status SHALL be `expired`, the planner SHALL use the config fallback, and the API and UI SHALL say so. A later accepted estimate SHALL restore the learned value.

#### Scenario: Expiry
- **WHEN** the last successful estimate is 31 days old
- **THEN** the effective value is the config fallback and the status is `expired`

#### Scenario: Recovery
- **WHEN** an expired parameter gets a new accepted estimate
- **THEN** the status becomes `learned` and a history row records the recovery

#### Scenario: Locked value never expires
- **WHEN** a parameter is locked and its last estimate is older than 30 days
- **THEN** the locked value is still used

### Requirement: The user can lock any learned parameter to their own value
The user SHALL be able to lock a parameter to a number inside its physical bounds, and unlock it, through the API and the UI. A locked value SHALL be the effective value, SHALL NOT be changed by learning, and SHALL NOT expire. Estimation SHALL continue while locked so the learned value stays visible. Locking, changing the lock value and unlocking SHALL be recorded in history and SHALL NOT send a notification.

#### Scenario: Lock
- **WHEN** the user locks the inverter discharge efficiency to 0.95
- **THEN** the effective value is 0.95 with source `locked`, even if a different value is learned

#### Scenario: Out-of-bounds lock rejected
- **WHEN** a lock value outside the bounds is submitted
- **THEN** the request is rejected with a validation error and nothing changes

#### Scenario: Unlock
- **WHEN** the user unlocks a parameter
- **THEN** the effective value is the learned value if valid, otherwise the config fallback

### Requirement: Every effective value reports its source
Each parameter SHALL expose its effective value and source: `locked`, `learned`, `default`, `config` (fallback because nothing valid is learned) or `expired`. The API SHALL also expose the learned value, confidence, evidence, the last-estimate time, the expiry time, the bounds and the config fallback.

#### Scenario: Fresh install
- **WHEN** nothing has been learned yet
- **THEN** each parameter reports a fallback source and no learned value

### Requirement: Every applied change sends one notification, which can be switched off
A learning run that changes any applied value (learned update, expiry, recovery) SHALL send one notification listing every change of that run, unless `executor.notifications.on_learned_parameter_change` is false (default true). The toggle SHALL be exposed like the other notification toggles in the executor notification API, the Executor page and the Settings page. Changes while a parameter is locked SHALL NOT notify.

#### Scenario: Change notifies
- **WHEN** a run changes the round-trip efficiency from 0.960 to 0.962 and the toggle is on
- **THEN** one notification names the parameter, old and new value and the window

#### Scenario: Toggle off
- **WHEN** the toggle is false
- **THEN** values still change and are recorded in history, and no notification is sent

#### Scenario: Delivery impossible
- **WHEN** the notification cannot be delivered
- **THEN** the history rows stay marked as not notified and the next run retries them, for at most 3 days

### Requirement: Learned parameters have a read and write API
The system SHALL provide `GET /api/learning/parameters` (all parameters with the fields above), `GET /api/learning/parameters/history` (recent history, filterable by parameter, limit 1 to 200), `PUT /api/learning/parameters/{key}/lock` with `{"value": number}`, `DELETE /api/learning/parameters/{key}/lock`, and `POST /api/learning/parameters/recompute`. Unknown keys SHALL return 404. A parameter that cannot be learned (inverter discharge efficiency) SHALL still be lockable.

#### Scenario: Unknown key
- **WHEN** the lock endpoint is called with an unknown key
- **THEN** it returns 404

#### Scenario: Recompute
- **WHEN** the recompute endpoint is called
- **THEN** the daily estimation runs once and the response lists the changes it applied

### Requirement: Settings show learned parameters and let the user lock them
The Battery settings tab SHALL show each parameter with its effective value, source badge, learned value, confidence, evidence summary, last change, expiry state and a lock control with an input. Expired values SHALL state that the config fallback is in use. The page SHALL follow the Darkstar design system.

#### Scenario: Expired value shown
- **WHEN** a parameter is expired
- **THEN** its row shows an `expired` badge and the text that the configured value is used

#### Scenario: Lock from the UI
- **WHEN** the user enters a value and activates the lock
- **THEN** the row shows source `locked` and the entered value

### Requirement: Nothing stale overrides a setting after Reflex removal
Startup SHALL remove the Reflex config keys and drop the tables `reflex_state` and `learning_daily_metrics`. After the removal, no code path SHALL read a stored value to override `s_index.base_factor`, `forecasting.pv_confidence_percent` or any other config setting except through the learned-parameter resolution.

#### Scenario: Stale row after upgrade
- **GIVEN** a database holding a `learning_daily_metrics` row with `s_index_base_factor` 1.4066
- **WHEN** the application upgrades
- **THEN** the table is gone and the planner uses the configured `base_factor`

#### Scenario: Manual settings keep their last values
- **WHEN** a config holds `pv_confidence_percent` 95 written earlier by Reflex
- **THEN** the value stays 95 and is treated as the user's manual setting

### Requirement: The daily run never disturbs planning
The estimation service SHALL run once a day after the nightly benchmark window and once shortly after startup. Any error SHALL be logged and SHALL NOT affect the planner, the executor or the recorder. The planner SHALL read the resolved values without waiting for or triggering an estimate.

#### Scenario: Estimator crash
- **WHEN** an estimator raises
- **THEN** the other parameters are still processed, the error is logged and planning continues with the previous effective values
