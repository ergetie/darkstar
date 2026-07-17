## ADDED Requirements

### Requirement: Frontend data-transform logic is unit-tested as pure functions

Frontend logic that transforms data for display — chart series building, power-flow partitioning and node enablement, schedule/slot day math, price breakdown, cost aggregation, progress/status derivation, and value formatters with branching logic — SHALL be importable as pure functions (module-level, exported) and SHALL have unit tests. These tests SHALL include configuration-variation cases for hardware setups the maintainer does not run: absent battery, absent EV charger, zero and multiple chargers, absent water heater, and empty/missing optional data fields. Tests for time-dependent logic SHALL use injected/fixed time (fake timers), never the machine wall clock. New render/component tests and E2E tests are explicitly NOT required by this requirement.

#### Scenario: Chart data builder handles a battery-less config
- **WHEN** the 48h chart data builder receives schedule slots with no battery fields (no `charge_kw`/`discharge_kw`)
- **THEN** it SHALL produce null/empty charge and discharge series without `NaN` values or exceptions

#### Scenario: Power-flow logic handles absent EV data
- **WHEN** power-flow partitioning receives data with no `ev` entry, or node enablement receives a config with `has_battery: false`
- **THEN** the EV/battery nodes SHALL be absent from the computed output without error

#### Scenario: Aggregations survive empty inputs
- **WHEN** cost-drift, normalization, or summary logic receives an empty series/slot list
- **THEN** it SHALL return its documented empty-state value (zero drift, flat normalization, null summary) rather than `NaN` or a thrown error

#### Scenario: Time-dependent tests are wall-clock independent
- **WHEN** unit tests exercise "today"/"tomorrow"/date-range logic
- **THEN** they SHALL set a fixed system time (including DST-boundary and near-midnight instants) and restore real timers afterward

#### Scenario: Surprising current behavior is pinned
- **WHEN** logic has a deliberate but non-obvious fallback (e.g. null system config excluding the EV node from the power flow)
- **THEN** a test SHALL assert the current behavior explicitly, so any future change to it is a conscious, reviewed decision
