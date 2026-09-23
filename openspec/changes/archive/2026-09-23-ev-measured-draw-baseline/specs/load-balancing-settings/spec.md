## MODIFIED Requirements

### Requirement: Live per-phase status
The system SHALL expose live balancer status — per-phase measured current, fuse rating, headroom, and the balancer's current action — via the existing live-metrics WebSocket emission and a REST status endpoint. The status SHALL include one named entry per dynamically-throttled EV charger (charger name, state — idle/throttling/paused/stale-fallback, current setpoint vs. planned target, and the measured draw in amps per phase or null when unavailable) rather than a single unnamed summary line, plus the shed-entry state (which loads are shed, with reason). The frontend SHALL render a status view with per-phase load bars against the fuse limit, a per-charger row for each dynamically-throttled charger (showing measured draw when available), and the active shed state with its reason.

The status view SHALL additionally display a data-freshness indicator derived from the latest received payload's timestamp (e.g. "updated 3 s ago"), updating continuously, and SHALL visually flag staleness when the age materially exceeds the executor tick interval — so a system whose measured currents are legitimately near zero (e.g. a zero-export inverter covering the house load) remains distinguishable from a frozen or disconnected one.

#### Scenario: User watches the balancer act
- **WHEN** the balancer reduces the EV from 16 A to 10 A because L1 is near the fuse limit
- **THEN** the status view SHALL show L1 near its limit and a row for that charger stating it's limited to 10 A (planned 16 A) because of L1

#### Scenario: Measured draw shown
- **WHEN** a charger's setpoint is 16 A and its measured draw is 10 A
- **THEN** its status row SHALL show the 10 A measured draw alongside the 16 A setpoint

#### Scenario: Feature disabled
- **WHEN** `load_balancing.enabled` is false
- **THEN** the status view SHALL state the feature is disabled instead of showing empty bars

#### Scenario: Multiple dynamically-throttled chargers are individually visible
- **WHEN** two `type: current` EV chargers are configured and one is being throttled while the other charges at its planned target
- **THEN** the status view SHALL show two distinct named rows, one per charger, each reflecting its own state

#### Scenario: Quiet zero-export home still reads as live
- **WHEN** measured phase currents sit near 0 A for hours while the balancer runs normally
- **THEN** the freshness indicator SHALL keep showing a recent update age
- **AND** the view SHALL NOT be visually indistinguishable from a stalled data feed

#### Scenario: Stalled feed is flagged
- **WHEN** no live-metrics payload has arrived for materially longer than the executor tick interval
- **THEN** the status view SHALL visually flag the data as stale
