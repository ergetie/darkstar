## Purpose

For current-type EV chargers capable of switching between 1-phase and 3-phase charging, the executor SHALL be able to command the phase mode based on available charging power (surplus or scheduled), using hysteresis and a minimum dwell time to avoid contactor thrashing, and SHALL fail safe when phase-mode control is unavailable.
## Requirements
### Requirement: Phase mode is selected by a threshold state machine with hysteresis

For chargers with `phase_mode_entity` configured and `phase_switching.enabled: true`, the executor SHALL select the charging phase mode from the target charging power: 1-phase when the target power has remained below the 3-phase minimum (6 A × 3 × 230 V ≈ 4.14 kW) plus `hysteresis_kw` for the full dwell window, and 3-phase when the target power has remained above that threshold for the full dwell window. The state machine SHALL apply to both surplus-driven and scheduled charging targets.

#### Scenario: Small surplus switches to 1-phase
- **WHEN** measured surplus supports only 2.5 kW and the charger is in 3-phase mode
- **AND** the condition persists beyond the dwell window
- **THEN** the executor SHALL command 1-phase mode so charging can continue at ≥ 1.38 kW

#### Scenario: Large surplus switches back to 3-phase
- **WHEN** the charger is in 1-phase mode at its maximum 1-phase power and the target power exceeds the 3-phase minimum plus hysteresis for the full dwell window
- **THEN** the executor SHALL command 3-phase mode

#### Scenario: Hysteresis prevents boundary oscillation
- **WHEN** the target power fluctuates within ±`hysteresis_kw` around the 3-phase minimum
- **THEN** the executor SHALL NOT change the phase mode

### Requirement: Minimum dwell time between phase switches

The executor SHALL NOT command a phase-mode change within `min_dwell_s` (default 600 s) of the previous phase-mode change, regardless of target power.

#### Scenario: Rapid cloud cycles cannot thrash the contactor
- **WHEN** surplus alternates above and below the 3-phase minimum every 60 s
- **THEN** phase-mode commands SHALL be at least `min_dwell_s` apart

### Requirement: kW-to-ampere conversion uses the commanded phase count

All kW↔A conversions for the charger (target setpoints, minimum-floor checks, surplus feedback) SHALL use the currently commanded phase count, falling back to the configured `phases` value when no phase mode has been commanded. The charger's measured per-phase draw SHALL be used to detect cars that draw fewer phases than commanded, and the effective phase count for power accounting SHALL follow the measurement once available.

#### Scenario: Conversion in 1-phase mode
- **WHEN** the commanded phase mode is 1-phase and the target power is 2.3 kW
- **THEN** the ampere setpoint SHALL be computed as 2300 / 230 = 10 A

#### Scenario: Car charges on one phase despite 3-phase mode
- **WHEN** the commanded mode is 3-phase but the charger's measured draw shows current on only one phase
- **THEN** power accounting SHALL use one phase for the kW↔A conversion

### Requirement: Fail-safe behavior when phase-mode control is unavailable

If the phase-mode entity is unreadable, unavailable, or a mode write fails, the executor SHALL stop attempting phase switches, assume the configured `phases` value for conversions, log the condition, and continue charging in whatever mode the charger is in. Chargers without `phase_mode_entity`, with `phase_switching.enabled: false`, or of `type: binary` SHALL never receive phase-mode commands.

#### Scenario: Entity unavailable mid-operation
- **WHEN** the phase-mode entity becomes `unavailable` in HA
- **THEN** the executor SHALL log the condition, skip phase switching, and keep charging with the configured phase count

#### Scenario: Phase switching disabled
- **WHEN** `phase_switching.enabled` is false
- **THEN** the executor SHALL never write the phase-mode entity and SHALL use the configured `phases` for all conversions

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

### Requirement: Balancer can demand 1-phase mode for overload relief
The phase controller SHALL accept a relief demand from the load balancer (see `phase-load-balancing` "1-phase relief step in the degradation ladder"). When a relief demand is present and the charger is in 3-phase mode, the controller SHALL command 1-phase mode without waiting for the target-power threshold or hysteresis window. It SHALL still refuse the switch while `min_dwell_s` has not elapsed since the previous phase change, or while the controller is in its failed state. While the charger is in 1-phase mode because of a relief demand, the controller SHALL NOT return to 3-phase mode until both of these hold:
- (a) `min_dwell_s` has elapsed;
- (b) the balancer reports that every phase the charger would use in 3-phase mode has averaged headroom for `min_current_a` within `target_margin_percent`, sustained for the full `ramp_up_window_s`.

Once returned to 3-phase mode, the normal power-threshold state machine SHALL resume.

The same relief demand SHALL be used when the balancer re-fits a paused charger into 1-phase mode (see `phase-load-balancing` "Pause below minimum current with anti-flap resume"), with the same dwell and fail-safe rules. If the controller refuses the switch or the write fails, the charger SHALL stay paused rather than start in 3-phase mode.

#### Scenario: Relief overrides the power threshold
- **WHEN** the planner target is 6.9 kW (well above the 3-phase minimum) and the balancer demands relief
- **THEN** the controller SHALL command 1-phase mode, provided dwell has elapsed

#### Scenario: Relief-held 1-phase does not bounce back on target power alone
- **WHEN** the charger is in 1-phase mode due to relief, the planner target is above the 3-phase threshold, but L3's averaged current still leaves no room for 6 A within the target margin
- **THEN** the controller SHALL NOT command 3-phase mode

#### Scenario: Refused re-fit switch keeps the charger paused
- **WHEN** the balancer re-fits a paused charger into 1-phase mode and the phase-mode write fails
- **THEN** the charger SHALL stay paused and the confirm window SHALL start over

#### Scenario: Return to 3-phase after the load ends
- **WHEN** floor heating on L3 stops, all three phases have averaged room for 6 A within the target margin for 60 s, and 600 s have passed since the switch
- **THEN** the controller SHALL command 3-phase mode

### Requirement: Configurable 1-phase grid line
Each phase-switching charger SHALL declare `phase_1_line` (1, 2 or 3; default 1): the grid phase the charger draws on in 1-phase mode. The balancer SHALL use it to decide which phases a 1-phase switch relieves. While the charger is in 1-phase mode, the balancer SHALL attribute its draw only to that line. Validation SHALL reject a `phase_1_line` that is not among the charger's configured `phases`.

#### Scenario: Default line
- **WHEN** `phase_1_line` is absent
- **THEN** the charger SHALL be treated as drawing on L1 in 1-phase mode

#### Scenario: Charger wired to a different line
- **WHEN** `phase_1_line: 2` and L2 is overloaded
- **THEN** a 1-phase switch SHALL NOT be treated as relief for L2
