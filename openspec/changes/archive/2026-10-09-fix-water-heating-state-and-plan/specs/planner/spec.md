## MODIFIED Requirements

### Requirement: Pipeline tracks per-device today's heated energy
The production initial-state, forecast, pipeline and adapter path SHALL calculate and propagate `heated_today_kwh` per water heater from attributable recorded active energy and non-overlapping recent power history. The legacy field SHALL represent pre-horizon progress in the first active quota bucket, using the same local-time boundaries as the solver. Each heater's value SHALL reflect only that heater's contribution. Available contributions SHALL be retained when coverage is incomplete; source and missing coverage SHALL be distinguishable from a measured zero. Control type SHALL NOT change electrical-energy accounting.

#### Scenario: Two heaters with different today progress
- **WHEN** heater A has heated 4.0 kWh today and heater B has heated 2.0 kWh today
- **THEN** heater A's `heated_today_kwh` SHALL be 4.0
- **AND** heater B's `heated_today_kwh` SHALL be 2.0

#### Scenario: Production wiring consumes recorded progress
- **WHEN** 4 kWh of active heating is written through the real observation store for a heater with a 4 kWh minimum and a new production planning state is built
- **THEN** that heater's first-bucket input SHALL credit 4 kWh rather than the initial-state placeholder zero
- **AND** the first-bucket daily-quota constraint SHALL have no outstanding energy requirement
- **AND** this SHALL hold for switch and temperature control

#### Scenario: Recording lag and repeated replans
- **WHEN** a completed slot before the solver horizon has not yet been stored, or a replan occurs within the current solver slot
- **THEN** available power history SHALL contribute only previously uncounted energy before the first solver slot's start
- **AND** measurements within that solver slot SHALL NOT also be credited against its full planned slot energy
- **AND** repeated replans, horizon advancement and later recording SHALL NOT count the same interval twice

#### Scenario: Unavailable measurement does not certify zero
- **WHEN** a heater has no power sensor or part of its history is unavailable
- **THEN** known attributable progress SHALL be retained and missing coverage SHALL be identified
- **AND** missing intervals SHALL receive no fabricated energy credit
- **AND** an ON command or temperature target alone SHALL NOT count as delivered heating
- **AND** the heater SHALL remain controllable under its existing control contract

#### Scenario: Quota rollover does not carry progress forward
- **WHEN** a plan spans the configured quota boundary
- **THEN** only measured energy belonging to the first active bucket SHALL reduce that bucket's quota
- **AND** later buckets SHALL retain their own daily minimum

## ADDED Requirements

### Requirement: Replanning distinguishes delivered heating from continuity
Replanning SHALL deduct delivered active energy before computing outstanding quota demand. It SHALL preserve existing per-device active-block continuity and allow retries when energy remains undelivered. Quota completion SHALL NOT constitute a hard heating cap or disable independently enabled comfort top-ups. Activity detection SHALL use the configured active-power cutoff.

#### Scenario: Partial delivery remains retryable
- **WHEN** only 2 kWh of a 4 kWh minimum has been delivered because earlier planned heating was missed
- **THEN** replanning SHALL retain the outstanding 2 kWh requirement subject to the existing soft shortfall penalty
- **AND** it SHALL NOT credit the missed planned energy as delivered

#### Scenario: Complete quota without other demand
- **WHEN** the active quota is met, no active block is locked and top-ups are disabled
- **THEN** replanning SHALL NOT request another full daily quota for that bucket

#### Scenario: Active block and comfort remain independent
- **WHEN** quota progress is complete but the heater has a genuine active block or enabled gap-comfort demand
- **THEN** existing continuity constraints or soft comfort penalties SHALL remain applicable
- **AND** idle power below the configured cutoff SHALL NOT create a mid-block lock
