## MODIFIED Requirements

### Requirement: Phase mode is selected by a threshold state machine with hysteresis

For chargers with `phase_mode_entity` configured and `phase_switching.enabled: true`, the executor SHALL select the charging phase mode from the target charging power: 1-phase when the target power is below the 3-phase minimum (6 A × 3 × 230 V ≈ 4.14 kW) plus `hysteresis_kw`, and 3-phase when the target power is above that threshold. For surplus-driven, manual and keep-on-only targets, the condition SHALL have held for the full dwell window before switching. For planned targets (the scheduled EV kW for the charger, including the idle look-ahead target), the executor SHALL NOT wait for the condition to hold and SHALL switch as soon as the minimum time since the previous switch allows.

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

#### Scenario: Planned target switches at the slot boundary
- **WHEN** the charger is in 1-phase mode, the last switch was more than `min_dwell_s` ago
- **AND** a new slot starts with a planned 6.9 kW for the charger
- **THEN** the executor SHALL command 3-phase mode on the first tick of that slot

## ADDED Requirements

### Requirement: Idle charger pre-switches for the next planned slot

When a phase-switching charger is idle in the current slot — no manual charge, not surplus-eligible, not keep-on-only, and planned kW ≤ 0.1 — and the next slot plans more than 0.1 kW for it, the executor SHALL use the next slot's planned kW as the phase-mode target, as a planned target. The charger SHALL NOT be commanded to charge before its slot starts. The minimum time between phase switches SHALL still apply.

#### Scenario: Idle 1-phase charger before a 3-phase slot
- **WHEN** the charger is idle in 1-phase mode at 11:50 and the 12:00 slot plans 6.9 kW
- **AND** the last switch was more than `min_dwell_s` ago
- **THEN** the executor SHALL command 3-phase mode during the 11:45 slot
- **AND** SHALL NOT command a charging current until 12:00

#### Scenario: Idle charger before a 1-phase slot
- **WHEN** the charger is idle in 3-phase mode and the next slot plans 2.0 kW
- **THEN** the executor SHALL command 1-phase mode during the idle slot

#### Scenario: No plan in the next slot
- **WHEN** the charger is idle and the next slot plans no charging for it
- **THEN** phase-mode selection SHALL behave as before (target 0 with the hold window)

#### Scenario: Charging in the current slot is not pre-switched
- **WHEN** the charger is charging at 2.3 kW in the current slot and the next slot plans 6.9 kW
- **THEN** the executor SHALL NOT switch before the next slot starts
