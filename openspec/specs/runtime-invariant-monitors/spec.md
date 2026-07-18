# Runtime Invariant Monitors

## Purpose
This specification defines the runtime invariant monitors that continuously evaluate a catalog of safety and correctness invariants against Darkstar's persisted data and in-process state, alert on violations without duplicating noise, and remain fully isolated from the planner, executor, recorder, and ML training so a monitor defect cannot degrade control.

## Requirements

### Requirement: Continuous invariant evaluation
The system SHALL periodically evaluate a catalog of runtime invariants against existing persisted data (`planner_learning.db`) and in-process state, without issuing any Home Assistant commands and without writing to any table that control or learning paths read. The evaluation cadence SHALL be configurable with a safe default (at most once per recorder cycle, i.e. every 15 minutes).

#### Scenario: Periodic evaluation runs
- **WHEN** the application has been running for at least one evaluation interval
- **THEN** every invariant in the catalog has a recorded evaluation result (pass, violation, or skipped-with-reason) with a timestamp

#### Scenario: Read-only guarantee
- **WHEN** a full evaluation cycle completes
- **THEN** no Home Assistant service call was made by the monitors and no row consumed by planner, executor, recorder, or ML training was created or modified by the monitors

### Requirement: Invariant catalog
The monitors SHALL evaluate at least the following invariants; exact thresholds SHALL be constants informed by the evidence phase of the stabilization review and documented alongside the implementation:

1. **Slot continuity** — recorded observation slots form a gap-free, duplicate-free 15-minute sequence over the trailing 24 h.
2. **Energy accounting** — per recorded slot, energy flows balance within tolerance (PV + import + battery discharge ≈ load + export + battery charge + losses).
3. **SoC bounds** — recorded battery SoC stays within the configured floor/ceiling band.
4. **Plan freshness** — the executor is acting on a schedule generated within the expected planner cadence (no stale-plan execution).
5. **Command success** — the executor's recent tick success rate (from `execution_log.success`) stays at or above 95 % over the trailing 24 h, so that short outages or restarts (up to roughly 72 failed one-minute ticks per day) do not raise a violation while sustained breakage still does.
6. **Forecast sanity** — the active PV forecast never exceeds the physical ceiling of the *configured* system, computed at evaluation time as the sum of `system.solar_arrays[].kwp` × 0.25 kWh per 15-minute slot. The ceiling SHALL NOT be a hardcoded constant. If no solar arrays are configured (or their summed kWp is not positive), the invariant SHALL report skipped-with-reason instead of evaluating.
7. **Data quality** — the most recent `data_quality_daily` status is not in a failed state.

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
- **WHEN** 18 of 1321 logged executor ticks in the trailing 24 h failed (success rate 98.64 %)
- **THEN** the command-success invariant passes, because 98.64 % ≥ 95 %

### Requirement: Alert on violation
The monitors SHALL raise a system alert (via the existing alert surface) when an invariant transitions from pass to violation, including the invariant name, the evidence (offending values/slots), and the evaluation time. Repeated evaluation of an already-alerted, still-violated invariant SHALL NOT produce duplicate alerts.

#### Scenario: Alert raised once per violation episode
- **WHEN** the command-success invariant is violated for three consecutive evaluation cycles
- **THEN** exactly one alert exists for the episode, and it reflects the first detection time

#### Scenario: Recovery clears the alert state
- **WHEN** a previously violated invariant evaluates to pass
- **THEN** the active alert for that invariant is cleared and a subsequent new violation raises a new alert

### Requirement: Failure isolation
A defect or crash inside the monitors SHALL NOT degrade or interrupt the planner, executor, recorder, or ML training. Monitor errors SHALL be logged and surfaced as a monitor-health status, and evaluation SHALL resume at the next cycle.

#### Scenario: Monitor exception does not affect control
- **WHEN** an invariant evaluation raises an unhandled exception
- **THEN** the executor tick, recorder cycle, and planner run proceed unaffected, the error is logged, and the monitor reports itself unhealthy instead of silently stopping

### Requirement: Monitor status is observable
The system SHALL expose the latest evaluation results (per-invariant status, last evaluation time, monitor health) through the existing health/status API surface so the dashboard and the operator can see them without reading logs.

#### Scenario: Status visible via API
- **WHEN** a client requests system health after at least one evaluation cycle
- **THEN** the response includes each invariant's latest status and the overall monitor health
