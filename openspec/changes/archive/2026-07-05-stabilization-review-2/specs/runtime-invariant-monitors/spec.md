## ADDED Requirements

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
5. **Command success** — the executor's recent tick success rate (from `execution_log.success`) stays above threshold.
6. **Forecast sanity** — the active PV forecast never exceeds the physical system ceiling.
7. **Data quality** — the most recent `data_quality_daily` status is not in a failed state.

#### Scenario: Violated invariant is detected
- **WHEN** the trailing-24 h observation data contains a missing 15-minute slot
- **THEN** the slot-continuity invariant evaluates to violation, identifying the missing slot(s)

#### Scenario: Healthy system evaluates green
- **WHEN** all catalog invariants hold over the evaluation window
- **THEN** every invariant reports pass and no alert is raised

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
