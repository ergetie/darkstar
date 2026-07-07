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
