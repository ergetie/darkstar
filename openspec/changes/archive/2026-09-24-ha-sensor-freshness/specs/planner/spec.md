## ADDED Requirements

### Requirement: SoC reading timestamp is supplied to pre-flight
When the initial state is built from a live Home Assistant SoC entity, `initial_state.soc_timestamp` SHALL be set to that entity's reading-freshness timestamp (per `ha-reading-freshness`), as an ISO-8601 timezone-aware string. If no timestamp is available, `soc_timestamp` SHALL be omitted and the staleness check SHALL be skipped as today. The existing 30-minute `DATA_STALE` warning semantics are unchanged.

#### Scenario: SoC entity stops reporting
- **GIVEN** the SoC entity's `last_reported` is 45 minutes old
- **WHEN** the planner runs
- **THEN** `initial_state.soc_timestamp` carries that time
- **AND** the pre-flight validator emits a `DATA_STALE` warning but does not halt

#### Scenario: Steady SoC still reported
- **GIVEN** the battery has sat at 100 % for 2 hours (`last_updated` 2 h old) and `last_reported` is 1 minute old
- **WHEN** the planner runs
- **THEN** no `DATA_STALE` warning SHALL be emitted
