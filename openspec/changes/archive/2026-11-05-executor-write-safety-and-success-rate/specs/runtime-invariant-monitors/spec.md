## MODIFIED Requirements

### Requirement: Invariant catalog
The monitors SHALL evaluate at least the following invariants; exact thresholds SHALL be constants informed by the evidence phase of the stabilization review and documented alongside the implementation. The invariants are slot continuity, energy accounting, SoC bounds, plan freshness, command success, forecast sanity, data quality and EV charge delivery, as specified in the scenarios below.

#### Scenario: Violated invariant is detected
- **WHEN** the trailing-24 h observation data contains a missing 15-minute slot
- **THEN** the slot-continuity invariant evaluates to violation, identifying the missing slot(s)

#### Scenario: Healthy system evaluates green
- **WHEN** all catalog invariants hold over the evaluation window
- **THEN** every invariant reports pass and no alert is raised

#### Scenario: Large array does not trip forecast sanity
- **WHEN** the configured solar arrays sum to 14.94 kWp and the maximum future PV forecast is 2.781 kWh per 15-minute slot
- **THEN** the forecast-sanity invariant passes, because 2.781 ≤ 14.94 × 0.25 = 3.735 kWh/slot

#### Scenario: Forecast above the configured ceiling is a violation
- **WHEN** the configured solar arrays sum to 7.11 kWp and a future PV forecast slot exceeds 7.11 × 0.25 = 1.778 kWh
- **THEN** the forecast-sanity invariant reports a violation naming the offending value and the config-derived ceiling

#### Scenario: No arrays configured skips forecast sanity
- **WHEN** the configuration contains no solar arrays (or their summed kWp is zero)
- **THEN** the forecast-sanity invariant reports skipped with a reason, not a violation

#### Scenario: Brief outage does not trip command success
- **WHEN** 18 of 1321 executed ticks in the trailing 24 h failed (success rate 98.64 %)
- **THEN** the command-success invariant passes, because 98.64 % ≥ 95 %

#### Scenario: Slot continuity invariant
- **WHEN** the monitors evaluate slot continuity
- **THEN** recorded observation slots SHALL form a gap-free, duplicate-free 15-minute sequence over the trailing 24 h

#### Scenario: Energy accounting and SoC bounds invariants
- **WHEN** the monitors evaluate energy accounting and SoC bounds
- **THEN** per recorded slot, energy flows SHALL balance within tolerance (PV + import + battery discharge ≈ load + export + battery charge + losses)
- **AND** recorded battery SoC SHALL stay within the configured floor/ceiling band

#### Scenario: Plan freshness and command success invariants
- **WHEN** the monitors evaluate plan freshness and command success
- **THEN** the executor SHALL be acting on a schedule generated within the expected planner cadence (no stale-plan execution)
- **AND** the executor's tick success rate, computed from the unthrottled persisted tick counters (not from `execution_log`), SHALL stay at or above 95 % over the trailing 24 h, so that short outages or restarts do not raise a violation while sustained breakage still does

#### Scenario: Forecast sanity invariant
- **WHEN** the monitors evaluate forecast sanity
- **THEN** the active PV forecast SHALL never exceed the physical ceiling of the *configured* system, computed at evaluation time as the sum of `system.solar_arrays[].kwp` × 0.25 kWh per 15-minute slot
- **AND** the ceiling SHALL NOT be a hardcoded constant
- **AND** if no solar arrays are configured (or their summed kWp is not positive), the invariant SHALL report skipped-with-reason instead of evaluating

#### Scenario: Data quality invariant
- **WHEN** the monitors evaluate data quality
- **THEN** the most recent `data_quality_daily` status SHALL NOT be in a failed state

## ADDED Requirements

### Requirement: Executor counts every executed tick, unthrottled and persisted
The executor SHALL count every executed tick (total, failed, and failures per action type with entity id and last error text) in hourly UTC buckets persisted in the `system_state` table under key `executor_tick_stats`, without a schema change.

#### Scenario: What is a failed tick
- **WHEN** any non-skipped action result failed or the tick raised
- **THEN** the tick is counted failed once, and each failing action is counted under its type

#### Scenario: Ticks that are not counted
- **WHEN** the executor is disabled, or a tick is a per-write EV event (`source='ev_charger'`) or the EV zero-power heuristic
- **THEN** no counter changes

#### Scenario: Retention and safety
- **WHEN** buckets are older than 25 hours
- **THEN** they are pruned, and persistence failures never raise into the tick

#### Scenario: Throttled log does not bias the rate
- **WHEN** 1410 ticks execute, 82 fail and only 130 rows are written to `execution_log`
- **THEN** the persisted counters read total 1410 and failed 82

#### Scenario: Paused, shadow, override or stale-hold ticks
- **WHEN** the executor is paused, in shadow mode, under manual override, or holding on a stale schedule
- **THEN** no counter changes

#### Scenario: Restart preserves the window
- **WHEN** the executor restarts after 800 counted ticks within the last 24 h
- **THEN** the counters resume from the persisted 800

#### Scenario: HA down
- **WHEN** a tick fails because HA cannot be reached
- **THEN** it is counted failed under reason "HA unavailable"

### Requirement: Command success names the failing actions
The `command_success` invariant SHALL read the persisted tick counters over the trailing 24 h. It SHALL report skipped while fewer than 12 ticks are available (fresh install or reset) or the counters are absent or unreadable. On violation the detail SHALL state the rate, the failed/total counts and name up to two top failing actions with count, entity and last error text, e.g. `charge_discharge_power failed 83× on input_number.darkstar_power_rec_w: <HA error>`.

#### Scenario: Violation names the action
- **WHEN** 82 of 1410 ticks failed, 82 of them on action `charge_discharge_power` entity `input_number.darkstar_power_rec_w`
- **THEN** the invariant reports violation with a detail containing "charge_discharge_power failed 82×" and the entity and error text

#### Scenario: Too few ticks after restart
- **WHEN** the counters contain 5 ticks
- **THEN** the invariant reports skipped with the reason "only 5 ticks recorded"

### Requirement: EV charge delivery invariant
The monitors SHALL evaluate an `ev_charge_delivery` invariant from the `system_state` key `executor_ev_charge_notice`. It SHALL report violation with the notice message while a notice is active, pass when none is active, and skipped when no EV charger is configured or the key is absent. A notice older than 6 hours SHALL be ignored.

#### Scenario: Charger draws no power
- **WHEN** an EV charge-failure notice is active
- **THEN** `ev_charge_delivery` reports violation with the commanded and actual power in the detail, and `command_success` is unaffected

#### Scenario: No EV
- **WHEN** no EV charger is configured
- **THEN** `ev_charge_delivery` reports skipped
