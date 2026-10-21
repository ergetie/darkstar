## ADDED Requirements

### Requirement: Time-based fuse overload model
The load balancer SHALL decide when to reduce, shed or pause any controlled load (battery grid charging, EV chargers, shed loads) from a per-phase accumulated heat value computed against a fuse time-current curve, replacing the instant battery cut and the separate EV pause delay. The give-way order SHALL be unchanged. Heat SHALL be measured against the real fuse rating `main_fuse_a`.

#### Scenario: One model for all loads
- **WHEN** a phase's accumulated heat reaches the action threshold
- **THEN** the balancer SHALL give way using the existing `give_way_order` (battery, EV, water heater by default), identically for every load kind
- **AND** the reduction SHALL bring the phase down to the target margin limit (`main_fuse_a` x `target_margin_percent`), not merely to `main_fuse_a`, so the phase drops below 1.0x and cools

#### Scenario: Over the rating but below the action condition
- **WHEN** a phase is over `main_fuse_a`, its heat is below the action threshold and the immediate-cut condition does not hold
- **THEN** no load SHALL be reduced, shed or paused for that phase

#### Scenario: Margin is the target, not the fuse
- **WHEN** heat triggers a reduction
- **THEN** `target_margin_percent` SHALL be the level the phase is brought down to, and the ramp-up and restore target

#### Scenario: Margin does not build heat
- **WHEN** a phase is above `target_margin_percent` of `main_fuse_a` but not above `main_fuse_a`
- **THEN** no heat SHALL build and no load SHALL be reduced because of the margin

#### Scenario: Power-mode sensors use converted current
- **WHEN** a phase sensor is in power mode
- **THEN** the heat model SHALL use the current converted by `power_to_current_a`, the same value the headroom check uses

### Requirement: Per-phase thermal accumulation
The balancer SHALL keep one heat value per phase, as a fraction of the trip time at the current overload multiple `m = current / main_fuse_a`. Heat SHALL build while `m` is at or above the preset curve's first timed point, hold steady while `m` is from 1.0 up to that point, and cool while `m` is below 1.0, at the same rate at which it built (the build rate at the most recent overload multiple on that phase). The balancer SHALL act on the worst phase.

#### Scenario: Heat builds over the curve start
- **WHEN** a phase reads 1.5x on the Typ C curve (about 300 s trip) for 150 s
- **THEN** its heat SHALL be 50% of the trip time

#### Scenario: Cooling is symmetric below the rating
- **WHEN** a phase has 50% heat built at 1.5x and then reads below 1.0x for 150 s
- **THEN** its heat SHALL be 0%

#### Scenario: Heat holds between the rating and the curve start
- **WHEN** a phase with 40% heat reads 1.05x on the Typ C curve (first timed point 1.13x)
- **THEN** its heat SHALL stay at 40% for as long as the reading stays from 1.0x up to 1.13x

#### Scenario: No heat below the curve start
- **WHEN** a phase with 0% heat reads 1.05x for any length of time
- **THEN** its heat SHALL stay 0% and no load SHALL be reduced because of it

#### Scenario: Repeated short overloads add up
- **WHEN** a phase has several short overloads separated by cool-down periods shorter than the build periods
- **THEN** heat SHALL carry over between them and MAY reach the action threshold

#### Scenario: Same logic for both fuse types
- **WHEN** the preset is Typ C (3-pole, one pole tripping opens all) or Diazed gG (the phase blows alone)
- **THEN** accumulation and action logic SHALL be identical; only the consequence of a trip differs

#### Scenario: Worst phase decides
- **WHEN** L1 has 20% heat and L3 has 85% heat with a safety of 80%
- **THEN** the balancer SHALL act on L3

### Requirement: Fuse presets and curves
The `Typ C` preset SHALL be the default; `Diazed gG` and `Custom` SHALL also be offered. Curves SHALL be in multiples of the rated current (In), so one curve per preset covers every fuse size, SHALL be interpolated log-log between points, and SHALL build no heat below the preset's first timed point. All values are read from manufacturer graphs with about +/-30% accuracy and SHALL be documented as such, with the anchor values below marked as assumptions.

#### Scenario: Typ C curve points
- **WHEN** the preset is Typ C
- **THEN** the curve SHALL use the fastest edge of the EN 60898 band (Hager technical sheet SE_TECHAPP_28-04-2015_31_DVB.pdf, read from graph, +/-30%): 1.13x about 1 h (first timed point; assumption: treated as exactly 1 h, it is "no trip for 1 h or more" in the graph); 1.2x about 1 h; 1.3x about 20 min; 1.5x about 5 min; 2x about 30 s; 3x about 4 s; 5x or more instant (assumption: 0.1 s at 5x for interpolation between 3x and 5x)

#### Scenario: Diazed gG curve points
- **WHEN** the preset is Diazed gG
- **THEN** the curve SHALL use one typical melt line (Hager SE_TECHAPP_28-04-2015_21_SMAELTSAEKRINGAR.pdf, read from graph, +/-30%): 1.25x treated as 4 h (first timed point; assumption, the graph says "never"); 1.6x about 1 h; 1.8x about 15 min; 2.5x about 100 s; 4x about 10 s
- **AND** above 4x the curve SHALL continue along the log-log slope of the 2.5x to 4x segment (assumption)

#### Scenario: Typ C is the default
- **WHEN** no preset is configured
- **THEN** the balancer SHALL use the Typ C curve

#### Scenario: Log-log interpolation
- **WHEN** a phase reads 1.75x on the Typ C curve
- **THEN** the trip time SHALL be the log-log interpolation between the 1.5x (300 s) and 2x (30 s) points

#### Scenario: Custom curve from two points
- **WHEN** the preset is Custom
- **THEN** the curve SHALL be the log-log line through the two entered points, with no heat below the point with the lower overload and extension along the same line above the point with the higher overload
- **AND** the two points SHALL be prefilled from Typ C (130 % at 1200 s and 300 % at 4 s)

### Requirement: Safety percentage
The balancer SHALL act when accumulated heat reaches safety% of the trip time. `load_balancing.fuse_safety_percent` SHALL be a number from 50 to 100. When unset, the default SHALL follow the preset: Typ C 80, Diazed gG 65, Custom 80.

#### Scenario: Default follows the preset
- **WHEN** `fuse_safety_percent` is unset and the preset is Diazed gG
- **THEN** the effective safety % SHALL be 65

#### Scenario: Explicit value wins
- **WHEN** `fuse_safety_percent` is 70 and the preset is Typ C
- **THEN** the effective safety % SHALL be 70

#### Scenario: Action at safety-scaled heat
- **WHEN** the effective safety % is 80 and a phase's heat reaches 80% of the trip time
- **THEN** the balancer SHALL give way

### Requirement: Immediate cut without a fixed multiple
The balancer SHALL cut immediately when the safety-scaled trip time at the current overload multiple (trip time times safety%) is shorter than one reading interval, where the reading interval is `executor.interval_seconds`. No fixed overload multiple SHALL be used.

#### Scenario: Large overload
- **WHEN** `executor.interval_seconds` is 15 and the safety-scaled trip time at the current reading is 10 s
- **THEN** the balancer SHALL give way in that tick without waiting for heat to accumulate

#### Scenario: Interval guidance
- **WHEN** `config.default.yaml` documents `load_balancing`
- **THEN** it SHALL keep advising `executor.interval_seconds` of 15 s or less when load balancing is enabled, because the immediate-cut rule and heat integration use that interval

### Requirement: Stale or missing readings keep today's behaviour
When a phase reading is missing or stale per `sensor_stale_after_s`, the balancer SHALL fall back to the current behaviour: an immediate cut on a reading over the limit, and the existing stale-sensor handling otherwise. Heat for that phase SHALL be frozen, neither built nor cooled.

#### Scenario: Stale phase
- **WHEN** a phase sensor is stale
- **THEN** the heat model SHALL NOT delay any cut that the existing stale-sensor rules or an over-limit reading would trigger

### Requirement: Restore after cooling
After a cut, a load SHALL be restored only once the worst relevant phase has cooled below 50% heat, replacing the fixed ramp-back timing. `increase_step_a` SHALL be kept as the ramp step. `ramp_up_window_s` SHALL remain only as the averaging window for increases, and `resume_delay_s` and `resume_confirm_s` SHALL remain as additional anti-flap gates.

#### Scenario: Cut, cool, restore
- **WHEN** `main_fuse_a` is 16 A, `target_margin_percent` is 85, Typ C safety is 80, and L1 reads 24 A (1.5x) until heat reaches 80% (about 240 s)
- **THEN** the balancer SHALL reduce loads on L1 until L1 is at or below 13.6 A (0.85x), below 1.0x
- **AND** L1 heat SHALL then fall at the rate it built, so a load SHALL be restored only after heat is below 50% (about 90 s later), and then only within the existing target-margin, `resume_delay_s` and `resume_confirm_s` conditions

#### Scenario: Hot phase blocks restore
- **WHEN** a load was cut and its worst phase still has 60% heat
- **THEN** the load SHALL NOT be restored

#### Scenario: Cooled phase allows restore
- **WHEN** the worst phase has cooled below 50% heat and the existing target-margin, `resume_delay_s` and `resume_confirm_s` conditions hold
- **THEN** the balancer MAY ramp back by at most `increase_step_a` per tick

### Requirement: Battery uses the same trigger
The house battery's grid-charge cut SHALL use the same heat trigger as the other loads, including while it is holding for shed relief (`hold_for_relief`).

#### Scenario: Battery waits for the action condition
- **WHEN** a battery phase is over `main_fuse_a`, heat is below the action threshold and the immediate-cut condition does not hold
- **THEN** the battery grid-charge cap SHALL NOT be cut

#### Scenario: Battery holding for shed relief
- **WHEN** a shed entry above the battery gave way this tick and the immediate-cut condition does not hold on the battery's phases
- **THEN** the battery SHALL hold its cap; if the immediate-cut condition holds it SHALL be cut in the same tick

### Requirement: Heat state lifecycle
Heat state SHALL be kept in memory only. After an executor restart heat SHALL start at 0 on every phase. A change to `fuse_preset`, `fuse_custom_points` while Custom is selected, or `main_fuse_a` at runtime SHALL reset heat to 0 on every phase.

#### Scenario: Restart
- **WHEN** the executor restarts while a phase has 70% heat
- **THEN** heat SHALL be 0% on every phase after the restart

#### Scenario: Preset or fuse rating changes
- **WHEN** `fuse_preset` or `main_fuse_a` is changed at runtime
- **THEN** all phase heat SHALL be reset to 0

### Requirement: Fuse configuration keys
The `load_balancing` config SHALL support `fuse_preset` (`typ_c` | `diazed_gg` | `custom`, default `typ_c`), `fuse_safety_percent` (see "Safety percentage") and `fuse_custom_points` (a list of exactly two points, each with `overload_percent` from 101 to 1000 and `time_s` from 0.5 to 86400). Validation failures SHALL name the key and its valid range.

#### Scenario: Custom points are used only for Custom
- **WHEN** `fuse_preset` is not `custom`
- **THEN** `fuse_custom_points` SHALL be ignored

#### Scenario: Defaults
- **WHEN** none of the fuse keys are configured
- **THEN** the balancer SHALL use `typ_c` with an effective safety of 80

#### Scenario: Invalid safety percent
- **WHEN** a user saves `fuse_safety_percent: 40`
- **THEN** validation SHALL fail naming `load_balancing.fuse_safety_percent` and its 50-100 range

#### Scenario: Custom points ordering
- **WHEN** the preset is `custom` and the higher-overload point does not have the shorter time
- **THEN** validation SHALL fail naming `load_balancing.fuse_custom_points`; the point with the higher `overload_percent` must have the strictly shorter `time_s`

#### Scenario: Custom point out of range
- **WHEN** a point has `overload_percent: 100` or `time_s: 100000`
- **THEN** validation SHALL fail naming the key and its valid range

### Requirement: Removed settings are migrated away
`load_balancing.pause_debounce_s` and `load_balancing.severe_overload_percent` SHALL be removed from `config.default.yaml`, the config loader, the API validator, the settings UI and the tests, and SHALL be added to the deprecated-key list used by `remove_deprecated_keys` in `backend/config_migration.py`.

#### Scenario: Old keys load without error
- **WHEN** a config still contains `pause_debounce_s` or `severe_overload_percent`
- **THEN** it SHALL load without validation errors or user-facing warnings

#### Scenario: Old keys are removed by migration
- **WHEN** the startup deprecated-key sweep runs on such a config
- **THEN** both keys SHALL be removed, the removal logged like other deprecated keys, and the result written through the existing atomic write with backup path

### Requirement: Slow executor interval warning
The settings UI SHALL show a warning, styled per `docs/design-system/AI_GUIDELINES.md`, when load balancing is enabled and `executor.interval_seconds` is greater than 15. The warning SHALL explain that slower ticks make overload timing coarse and cut sooner.

#### Scenario: Warning shown
- **WHEN** `load_balancing.enabled` is true and `executor.interval_seconds` is 60
- **THEN** the load-balancing section SHALL show the warning

#### Scenario: Warning hidden
- **WHEN** load balancing is disabled, or `executor.interval_seconds` is 15 or less
- **THEN** the warning SHALL NOT be shown

### Requirement: Fuse settings UI
The load-balancing settings UI SHALL follow `docs/design-system/AI_GUIDELINES.md` and SHALL show a preset select, the safety % and, only when Custom is selected, the two custom points (overload % and time).

#### Scenario: Custom points visibility
- **WHEN** the preset select is not Custom
- **THEN** the custom point fields SHALL NOT be shown

#### Scenario: Safety placeholder
- **WHEN** `fuse_safety_percent` is unset
- **THEN** the field SHALL show the preset default (80, 65 or 80) as its placeholder

#### Scenario: Removed fields gone
- **WHEN** the section is displayed
- **THEN** it SHALL NOT show a pause delay or an immediate-pause field
