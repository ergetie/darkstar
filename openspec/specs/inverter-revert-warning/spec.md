# Spec: Inverter Revert Warning

## Purpose
Warn the user when the inverter repeatedly leaves a discrete value (select or switch) Darkstar commanded, so a silently reverting inverter or integration is visible instead of being quietly overwritten every tick.

## Requirements

### Requirement: Watched entities are the discrete mode-action entities
The system SHALL watch every entity that a profile mode action writes and whose profile domain is not a number domain (selects and switches), resolved to its configured entity id, for all profiles. It SHALL NOT watch numeric entities (for example currents, SoC targets and power limits).

#### Scenario: Deye grid charging switch is watched
- **WHEN** the Deye profile writes `grid_charging_enable` and the entity later reads a value different from the last verified one
- **THEN** it is eligible for revert detection

#### Scenario: Sungrow forced command is watched
- **WHEN** the Sungrow profile writes `forced_charge_discharge_cmd`
- **THEN** it is eligible for revert detection

#### Scenario: Numeric entity is not watched
- **WHEN** a numeric entity such as `soc_target` or `max_charge_current` reads a value different from the one written
- **THEN** no revert event is counted

### Requirement: Detect departures from the last verified command per entity
The executor SHALL record, per watched entity, the value it last wrote and verified. When that entity is later read at a value different from its recorded value, the system SHALL count one revert event for that entity. The comparison SHALL be against the entity's last verified command, not against the target of the current plan slot. The system SHALL NOT change which writes it makes because of this detection.

#### Scenario: Inverter reverts after a write
- **WHEN** Darkstar verified "Charge from Grid" on the Fronius work-mode entity and at a later tick the entity reads "Discharge Limit"
- **THEN** one revert event is counted for that entity

#### Scenario: Switch reverts after a write
- **WHEN** Darkstar verified the Deye grid-charging switch on and at a later tick it reads off while the plan is still charging
- **THEN** one revert event is counted for the switch entity and none for the work-mode entity

#### Scenario: Normal plan transition is not a revert
- **WHEN** the plan changes from charge to idle and the entity still holds the last verified value
- **THEN** no revert event is counted

#### Scenario: Executor's own write is not a revert
- **WHEN** Darkstar writes a new value and the entity briefly reports its previous value, or the entity's last write is less than 30 seconds old
- **THEN** no revert event is counted

#### Scenario: Unverified write sets no baseline
- **WHEN** a write is not confirmed by read-back
- **THEN** no baseline is recorded for that entity and no revert event can be counted for it until a write is verified

#### Scenario: Unreadable state is ignored
- **WHEN** a watched entity reads unavailable, unknown, empty or cannot be read
- **THEN** no revert event is counted

#### Scenario: Unmapped generic profile
- **WHEN** the generic profile's value is still `CONFIGURE_ME` or the entity is not configured
- **THEN** no detection runs for that entity

#### Scenario: Entity not written by the current mode
- **WHEN** a watched entity is not among the actions of the mode executed in a tick (for example Sungrow `export_power_limit_switch` outside export mode)
- **THEN** its recorded command is dropped and it is not compared until it is written again

### Requirement: Manual control is never reported
All recorded commands SHALL be cleared whenever the executor does not write (manual override active, executor paused, automation toggle off, executor disabled, shadow mode) and when the inverter profile or entity mapping changes. After start-up no command is recorded until the first verified write.

#### Scenario: User takes manual control
- **WHEN** the manual override entity is on and the user changes an inverter mode or switch
- **THEN** no revert event is counted, and the first tick after override ends records fresh baselines

#### Scenario: Restart
- **WHEN** the executor starts
- **THEN** no revert event can be counted before a write has been verified

### Requirement: Debounced warning on recurrence per entity
The system SHALL count events per entity and raise a warning only when at least 3 revert events on the same entity occur within a rolling window of the larger of 60 minutes and four executor tick intervals. Events on different entities SHALL NOT be added together. A single or double event SHALL NOT raise a warning. The warning SHALL clear when no entity has 3 or more events in the window.

#### Scenario: Recurrent reverts
- **WHEN** 3 revert events on one entity occur within 20 minutes at a 5-minute tick
- **THEN** a warning is raised

#### Scenario: Spread across entities
- **WHEN** 2 events occur on one entity and 2 on another within the window
- **THEN** no warning is raised

#### Scenario: Isolated revert
- **WHEN** one revert event occurs and no others follow within the window
- **THEN** no warning is raised

#### Scenario: Recovery
- **WHEN** no revert event has occurred for one full window after a warning
- **THEN** the warning is no longer reported

### Requirement: Warning surface
An active warning SHALL appear in the health issues with code `INVERTER_MODE_REVERT`, severity warning, snoozable like other issues, naming each affected entity with its commanded value, observed value and event count. Its guidance SHALL mention checking the inverter's own schedule or app, the integration and firmware, and using manual override or pause for manual changes. The warning SHALL survive an application restart while the condition is current and be dropped once stale.

#### Scenario: Banner content
- **WHEN** the warning is active for two entities
- **THEN** the health API returns one issue with code `INVERTER_MODE_REVERT` naming both entity ids with their commanded and observed values and counts

### Requirement: Notification toggle
The setting `executor.notifications.on_inverter_mode_revert` (default true; an absent key behaves as true) SHALL control a notification sent once per warning episode, naming the affected entity or entities. It SHALL be exposed in the executor notifications API, the Executor page and the Settings page like the other `on_*` toggles.

#### Scenario: Toggle on
- **WHEN** a warning episode starts and the toggle is true
- **THEN** one notification is sent through the configured notification service

#### Scenario: Toggle off
- **WHEN** a warning episode starts and the toggle is false
- **THEN** no notification is sent but the health warning still appears
