# Spec: Fuse Overload Timing

## Purpose

Defines per-phase thermal fuse protection, preset and custom time-current curves, cooling gates, configuration and settings for load balancing.

## Requirements

### Requirement: Time-based fuse overload model
The fuse heat model SHALL be the default implementation of the pluggable reduction trigger of `phase-load-balancing` ("Reduction triggering is pluggable"). It SHALL decide from per-phase accumulated heat against a fuse time-current curve when any controlled load must give way, and SHALL be the only place overload is detected (no instant trigger, pause delay or severe-overload threshold remains). Heat SHALL be measured against `main_fuse_a`.

#### Scenario: Other balancer mechanisms are unchanged
- **WHEN** the heat model replaces the instant trigger
- **THEN** the give-way order, the pending-increase ledger, the shared room gate, step pacing and the fresh-sample guard SHALL behave as before

#### Scenario: One model for all loads
- **WHEN** a phase's accumulated heat reaches the action threshold
- **THEN** the trigger SHALL report relief for that phase and the balancer SHALL give way using the existing `give_way_order` (battery, EV, water heater by default), identically for every load kind
- **AND** the relief amount SHALL be the momentary reading minus the target margin limit (`main_fuse_a` x `target_margin_percent`), not merely the excess over `main_fuse_a`, so the phase drops below 1.0x and cools

#### Scenario: Over the rating but below the action condition
- **WHEN** a phase is over `main_fuse_a`, its heat is below the action threshold and the immediate-cut condition does not hold
- **THEN** no load SHALL be reduced, shed or paused for that phase

#### Scenario: Trigger output
- **WHEN** the action condition or the immediate-cut condition holds on a phase
- **THEN** the trigger SHALL return relief equal to the momentary reading minus the target margin limit (0 when the reading is already at or below it), flagged urgent only when the immediate-cut condition holds
- **AND** the urgent flag SHALL bypass the hold for unmeasured relief (for example a shed entry above gave way this tick) but SHALL NOT bypass the one-cut-per-fresh-sample and bounded response guards
- **AND** no other code path SHALL decide, delay or escalate a reduction by comparing readings with the fuse rating

#### Scenario: Heat is evaluated once per tick
- **WHEN** a tick runs
- **THEN** the model SHALL update each fresh phase with the real time since that phase's previous update, before the relief for that tick is computed
- **AND** a gap longer than `max(120 s, 2 x executor.interval_seconds)` SHALL NOT be integrated (heat holds), so a paused or restarted executor does not add or remove heat

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
The trigger SHALL flag relief urgent and call for relief in the same tick when the safety-scaled trip time at the current overload multiple (trip time times safety%) is shorter than one reading interval, where the reading interval is `executor.interval_seconds`. No fixed overload multiple SHALL be used.

#### Scenario: Large overload
- **WHEN** `executor.interval_seconds` is 15 and the safety-scaled trip time at the current reading is 10 s
- **THEN** the trigger SHALL call for urgent relief in that tick without waiting for heat to accumulate

#### Scenario: Interval guidance
- **WHEN** `config.default.yaml` documents `load_balancing`
- **THEN** it SHALL keep advising `executor.interval_seconds` of 15 s or less when load balancing is enabled, because the immediate-cut rule and heat integration use that interval

### Requirement: Stale or missing readings bypass the model
When a phase reading is missing or stale per `sensor_stale_after_s`, the model SHALL freeze its heat, SHALL NOT call for relief on it, and SHALL NOT delay or replace the existing stale-sensor fail-safes (EV charger and battery to minimum at once, pause after `resume_delay_s`).

#### Scenario: Stale phase
- **WHEN** a phase sensor is stale while its last reading was over `main_fuse_a`
- **THEN** its heat SHALL stay frozen and the charger and the battery SHALL follow their stale fail-safe (minimum at once, pause after `resume_delay_s`), without waiting for heat

#### Scenario: Heat resumes with fresh readings
- **WHEN** the phase reading becomes fresh again
- **THEN** heat SHALL continue from the frozen value with the first fresh reading, without integrating the stale period

### Requirement: Restore after cooling
After a cut, EV ramp-up, battery cap raises and shed-load restores SHALL wait until the worst phase the load draws on has cooled below 50% heat, replacing the `ramp_up_window_s` hold-off. This is an additional condition: the room gate, step pacing, `increase_step_a`, `resume_delay_s` and `min_off_s` still apply and all SHALL hold. `ramp_up_window_s` remains only the averaging window.

#### Scenario: Cut, cool, restore
- **WHEN** `main_fuse_a` is 16 A, `target_margin_percent` is 85, Typ C safety is 80, and L1 reads 24 A (1.5x) until heat reaches 80% (about 240 s)
- **THEN** the balancer SHALL reduce loads on L1 until L1 is at or below 13.6 A (0.85x), below 1.0x
- **AND** L1 heat SHALL then fall at the rate it built, so a load SHALL be ramped back or restored only after heat is below 50% (about 90 s later), and then only within the existing room-gate, pacing, target-margin and `resume_delay_s` conditions

#### Scenario: Hot phase blocks restore
- **WHEN** a load was cut and its worst phase still has 60% heat
- **THEN** the load SHALL NOT be restored

#### Scenario: Cooled phase allows a ramp step
- **WHEN** the worst phase has cooled below 50% heat and the room gate and step pacing allow the step
- **THEN** the balancer MAY ramp back by at most `increase_step_a` per granted step

#### Scenario: Water heater restore needs room, minimum off time and cooling
- **WHEN** a water heater was shed and its `min_off_s` and `resume_delay_s` have elapsed and the shared room gate has room for its power
- **THEN** it SHALL NOT be restored while any phase it draws on still has 50% or more heat
- **AND** when its phases have cooled below 50% but `min_off_s` has not elapsed, or the room gate has no room for its power, it SHALL NOT be restored either
- **AND** only when all three hold (room for its power, `min_off_s` elapsed, heat below 50%) SHALL it be restored

#### Scenario: Re-fit of a paused charger is not heat-gated
- **WHEN** a paused charger or battery has fitted its minimum within the target margin for the confirm window
- **THEN** it SHALL re-fit at its minimum without waiting for heat to drop below 50%, since it cannot push the phase back over the rating

### Requirement: Heat floor while relief is needed
While the trigger calls for relief on a phase, that phase's heat SHALL be held at no less than the safety percentage, so the cooled gate after a cut always lasts a real cooling time from the action threshold.

#### Scenario: Urgent cut does not skip cooling
- **WHEN** a large overload causes an urgent cut while L1 heat is only 20%
- **THEN** L1 heat SHALL be raised to the safety percentage at that tick
- **AND** loads on L1 SHALL NOT ramp back or restore until L1 has cooled below 50% from there

### Requirement: Battery uses the same trigger
The house battery's grid-charge cut SHALL use the same trigger as the other loads, including while it holds for unmeasured relief. The cut size SHALL come from the relief amount and the reducible grid charge, never from a lagging measured charge. Stale phases follow the battery stale fail-safe.

#### Scenario: Battery waits for the trigger
- **WHEN** a battery phase is over `main_fuse_a` and the trigger does not call for relief
- **THEN** the battery grid-charge cap SHALL NOT be cut

#### Scenario: Battery cut ignores lagging measured charge
- **WHEN** the trigger calls for relief while the measured battery charge still lags the cap
- **THEN** the cap SHALL be cut by the relief amount limited to the reducible grid charge, and the measured charge SHALL only limit the relief credited to the pool

#### Scenario: Battery holding for unmeasured relief
- **WHEN** a shed entry above the battery gave way this tick, or a cut on the phase still awaits its response, and the trigger does not flag the battery's phases urgent
- **THEN** the battery SHALL hold its cap; if the trigger flags a phase urgent and no response is awaited on it, the battery SHALL be cut in the same tick

#### Scenario: Stale battery phase
- **WHEN** a battery phase is stale
- **THEN** the cap SHALL drop to the profile minimum charge value at once and grid charging SHALL pause after `resume_delay_s`, whatever the heat on that phase

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

### Requirement: Removed settings
`load_balancing.pause_debounce_s` and `load_balancing.severe_overload_percent` SHALL be removed from `config.default.yaml`, the config loader, the API validator, the settings UI and the tests. Existing configs are cleaned by the startup sweep specified in `config-migration` "Remove balancer pause-delay and severe-overload settings".

#### Scenario: Old keys are ignored
- **WHEN** a config still contains either key
- **THEN** the loader and the validator SHALL ignore it without error or warning until the sweep removes it

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


### Requirement: Live fuse characteristic graph
The Overload Handling section SHALL show a responsive, accessible live characteristic graph for every preset, with logarithmic axes and labelled fuse-trip and safety-scaled cold-start threshold curves matching the executor model. It SHALL explain approximation and response limits.

#### Scenario: Curve axes and model agreement
- **WHEN** any preset is selected
- **THEN** logarithmic axes SHALL show current as a multiple of rated fuse current, and time in seconds
- **AND** the labelled curves SHALL use the executor's anchors and log-log interpolation
- **AND** the graph SHALL NOT imply guaranteed fuse protection

#### Scenario: Unsaved curve edits
- **WHEN** the user changes preset, safety percentage or custom points before saving
- **THEN** the preview SHALL immediately reflect those inputs and the preset-dependent safety default when safety is unset
- **AND** invalid or incomplete custom points or safety values SHALL show an explanation instead of an invalid curve

#### Scenario: Approximation and thermal history
- **WHEN** the graph is displayed
- **THEN** the safety-scaled curve SHALL be labelled as a cold-start threshold at constant current
- **AND** the UI SHALL explain that retained heat from repeated overloads can cause earlier intervention and that actual response depends on sensor updates, executor timing and equipment
- **AND** preset curves SHALL disclose graph-derived approximately ±30% accuracy and the assumed first/instantaneous anchors and extension rules
- **AND** no finite timed-heating curve SHALL be drawn below the first timed point

### Requirement: Live estimated fuse heat
The load-balancing status views SHALL show per-phase estimated fuse heat alongside phase current, the configured intervention threshold, model-reported heat state and a plain explanation of heat-related holds. Heat SHALL be labelled as estimated, not measured temperature. Settings SHALL distinguish the ramp-up target from the heat intervention threshold.

#### Scenario: Independent phase trends
- **WHEN** heat rises on L1, falls on L2 and stays constant on L3 during a model evaluation
- **THEN** status SHALL report heating, cooling and holding (or cold at zero) respectively, and each phase SHALL show its own heat bar, percentage and intervention marker
- **AND** an idle balancer accumulating heat SHALL say it is monitoring an overload rather than reporting within limits

#### Scenario: Sensor and executor freshness
- **WHEN** a phase reading is stale or the heat evaluation timestamp stops advancing beyond the status freshness window
- **THEN** the UI SHALL retain the last heat percentage, mark the affected estimate stale and frozen, and SHALL NOT imply ongoing heating or cooling
- **AND** missing telemetry SHALL be unavailable rather than fabricated as zero heat

#### Scenario: Heat hold explanation
- **WHEN** an EV, battery or shed restore is held by its heat cooling gate
- **THEN** the status SHALL explain that increasing or restoring requires heat below 50%, without implying that other room, pacing or minimum-off conditions no longer apply

#### Scenario: Clear settings and compact presentation
- **WHEN** the user reviews load-balancing settings
- **THEN** the percentage controls SHALL be labelled “Ramp-up target (% of fuse rating)” and “Intervene at (% of estimated fuse heat)”
- **AND** the characteristic graph SHALL sit beside a concise explanation on wider screens and stack on small screens, with assumptions behind a collapsed technical-details disclosure

#### Scenario: Integrated phase rows with optional explanation
- **WHEN** either status view displays live heat telemetry
- **THEN** each phase SHALL appear once, grouping its current bar and smaller heat bar with percentage and trend
- **AND** redundant heat summaries SHALL be omitted and explanations SHALL be in a collapsed accessible disclosure
- **AND** stale readings SHALL override the within-limits headline without marking other fresh phases stale
