## ADDED Requirements

### Requirement: Resolved SoC carries a recent valid reading for a bounded window
For each charger with a configured SoC sensor, the planner and EV API SHALL use a resolved SoC with a status:
- `live`: the live reading is valid. Use it.
- `carried`: the live reading is none, and the last-known valid reading is no older than `ev_chargers[].soc_stale_after_minutes` (default 15). Use the last-known value.
- `stale`: otherwise. The resolved SoC is none.

#### Scenario: Brief sensor dropout
- **GIVEN** the last valid SoC reading was 55% six minutes ago and the window is 15 minutes
- **WHEN** the live SoC read returns none
- **THEN** the resolved SoC SHALL be 55% with status `carried`

#### Scenario: Sustained dropout
- **GIVEN** the last valid SoC reading was 40 minutes ago and the window is 15 minutes
- **WHEN** the live SoC read returns none
- **THEN** the resolved SoC SHALL be none with status `stale`

#### Scenario: Custom window
- **GIVEN** `soc_stale_after_minutes: 30` and a last valid reading 20 minutes ago
- **WHEN** the live SoC read returns none
- **THEN** the status SHALL be `carried`

#### Scenario: EV API exposes the resolution
- **WHEN** a client calls `GET /api/ev/chargers` for a charger with a SoC sensor
- **THEN** the response SHALL include `soc_status` (`live`, `carried` or `stale`) and `soc_age_minutes` (the age of the last valid reading, or null when there was none)
- **AND** `soc_percent` SHALL remain the live reading (null when unreadable)

### Requirement: Stale SoC suspends goal charging and warns
When a plugged charger's resolved SoC status is `stale`, the system SHALL apply all of the following:
- The planner SHALL NOT compute a required energy, and SHALL NOT pass a goal requirement to the solver for that charger.
- Surplus charging SHALL remain unaffected.
- The EV API SHALL report status `soc_unavailable`, with the age of the last valid reading.
- A single notification SHALL be sent per stale episode, only when the dedicated toggle `executor.notifications.on_ev_soc_stale` (default `true`) is enabled. This toggle SHALL be independent of all other notification toggles and SHALL appear with them in the settings notifications section.
- The planner SHALL NOT fall back to "target capacity minus delivered today" for a charger whose SoC sensor is configured.

An unplugged charger SHALL NOT be suspended, reported as `soc_unavailable` or notified for a stale SoC. Its goal SHALL keep being planned as assumed plugged from the resolved SoC, else the last persisted SoC regardless of age (`ev-target-charging`). A missing SoC SHALL NOT be persisted as 0%; the last persisted SoC SHALL be kept instead.

#### Scenario: Goal suspended
- **WHEN** a plugged charger with an active goal has SoC status `stale`
- **THEN** the solver SHALL receive no goal requirement for that charger
- **AND** the EV API SHALL return `status="soc_unavailable"`

#### Scenario: One notification per episode
- **WHEN** the status stays `stale` across several planner runs
- **THEN** exactly one stale-SoC notification SHALL be sent until a valid reading is seen again

#### Scenario: Notification toggle off
- **GIVEN** `executor.notifications.on_ev_soc_stale` is `false`
- **WHEN** a charger's SoC status becomes `stale`
- **THEN** no stale-SoC notification SHALL be sent
- **AND** goal charging SHALL still be suspended and the EV API SHALL still report `soc_unavailable`

#### Scenario: Unplugged charger with a stale SoC
- **WHEN** an unplugged charger with an active goal has SoC status `stale` and a persisted SoC of 70%
- **THEN** its goal SHALL be planned as assumed plugged from 70%
- **AND** no stale-SoC notification SHALL be sent and the EV API SHALL NOT report `soc_unavailable`

#### Scenario: Recovery
- **WHEN** a valid SoC reading arrives after a stale episode
- **THEN** the status SHALL become `live` and goal planning SHALL resume on the next planner run

### Requirement: SoC recovery triggers one immediate replan
When a plugged charger's stale episode is ended by a valid SoC reading, the system SHALL request exactly one immediate replan for that episode through the shared `scheduler_service.request_replan` helper, with reason `ev_soc_recovered` and the charger's ID. No replan SHALL be requested while the SoC stays stale, while it is fresh without a prior stale episode, or when the episode ends because the charger is unplugged. A recovery first observed by a planner run SHALL NOT trigger an additional replan.

#### Scenario: Recovery replans once
- **GIVEN** a plugged charger in a stale episode
- **WHEN** a valid SoC reading arrives and several executor ticks follow
- **THEN** exactly one replan SHALL be requested with reason `ev_soc_recovered` and that charger's ID

#### Scenario: No replan while stale
- **WHEN** the SoC stays stale across several executor ticks
- **THEN** no recovery replan SHALL be requested

#### Scenario: No replan without a prior stale episode
- **WHEN** valid SoC readings arrive with no preceding stale episode
- **THEN** no recovery replan SHALL be requested

### Requirement: SoC read failures are logged truthfully
A failed or unavailable SoC read SHALL be logged as unavailable, with the carry or suspend outcome. The log SHALL NOT claim a default of 0%.

#### Scenario: Log wording
- **WHEN** a SoC read returns no data
- **THEN** the log line SHALL state the reading is unavailable and whether the last-known value is carried or goal charging is suspended
- **AND** SHALL NOT contain "defaulting to 0%"
