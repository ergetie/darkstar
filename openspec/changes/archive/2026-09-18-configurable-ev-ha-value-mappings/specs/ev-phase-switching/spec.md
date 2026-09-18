## ADDED Requirements

### Requirement: Phase-mode select options are configurable per charger
Each phase-switching charger SHALL map the controller's internal phase counts to the charger-specific HA select options using `phase_1_value` (default `"1"`) and `phase_3_value` (default `"3"`). The executor SHALL preserve the configured option's spelling and case when calling `select.select_option`, and SHALL use the same mapped value for idempotence checks, shadow-mode reporting, post-action verification, and any commanded-mode caching. The phase controller SHALL continue to reason internally in numeric phase counts and SHALL NOT require an automatic-mode mapping.

When `phase_switching_enabled` is true, `phase_mode_entity` SHALL be a Home Assistant `select` or `input_select` entity, and `phase_1_value` and `phase_3_value` SHALL both be non-empty and SHALL differ from each other.

#### Scenario: Go-e charger is forced to one phase
- **WHEN** the phase controller commands one phase and `phase_1_value` is `Force_1`
- **THEN** the executor SHALL call the configured phase-mode select with option `Force_1`

#### Scenario: Go-e charger is forced to three phases
- **WHEN** the phase controller commands three phases and `phase_3_value` is `Force_3`
- **THEN** the executor SHALL call the configured phase-mode select with option `Force_3`

#### Scenario: Mapped value is used for idempotence and verification
- **WHEN** `phase_3_value` is `Force_3` and the phase-mode select already reports `Force_3`
- **THEN** the executor SHALL skip the redundant HA service call
- **AND** a completed three-phase write SHALL verify against `Force_3`, not `3`

#### Scenario: Legacy phase options remain compatible
- **WHEN** `phase_1_value` and `phase_3_value` are absent
- **THEN** one-phase and three-phase commands SHALL continue to send `1` and `3` respectively

#### Scenario: Current automatic state does not suppress a forced command
- **WHEN** the phase-mode select currently reports `Auto`
- **AND** the phase controller warrants a switch to one or three phases
- **THEN** the executor SHALL send the corresponding configured forced-phase option

#### Scenario: Non-select phase-mode entity is rejected
- **WHEN** `phase_switching_enabled` is true and `phase_mode_entity` is `switch.ev_phase`
- **THEN** config validation SHALL report an actionable error naming the required select domain
