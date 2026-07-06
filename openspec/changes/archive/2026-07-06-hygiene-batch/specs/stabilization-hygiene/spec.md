## ADDED Requirements

### Requirement: Dead `schedule_planned` table and model are removed

The system SHALL NOT define or retain the `schedule_planned` table or its `SchedulePlanned` ORM model. All plan-of-record reads and writes use `slot_plans`.

#### Scenario: Model no longer defined
- **WHEN** the codebase is searched for `SchedulePlanned` or `schedule_planned`
- **THEN** no ORM model, index, or reader/writer references it (test fixtures aside)

#### Scenario: Migration drops the table
- **WHEN** `alembic upgrade head` runs against a database that still contains `schedule_planned`
- **THEN** the table is dropped
- **AND** `alembic downgrade -1` recreates the (empty) table for rollback parity

### Requirement: No dead or duplicated configuration keys mislead the operator

Configuration SHALL NOT contain keys that are read by no code, and effective constants SHALL have a single source so two config locations cannot silently diverge.

#### Scenario: Dead AC-limit key removed
- **WHEN** the shipped `config.yaml` / `config.default.yaml` are inspected
- **THEN** `executor.controller.inverter_ac_limit_kw` is absent
- **AND** the live AC limit remains `system.inverter.max_ac_power_kw`

#### Scenario: Charge efficiency is single-sourced
- **WHEN** the executor controller config loads and `battery.charge_efficiency` is present
- **THEN** the executor's effective `charge_efficiency` equals `battery.charge_efficiency`
- **AND** the duplicate `executor.controller.charge_efficiency` key is not present in shipped config

#### Scenario: Current configuration behavior is preserved
- **WHEN** the change is applied against this instance's config (`battery.charge_efficiency = 0.92`)
- **THEN** the executor's resolved charge efficiency is still `0.92`

### Requirement: Cumulative meter deltas have a plausibility ceiling

The recorder SHALL reject a computed meter delta that exceeds a configurable per-slot ceiling (`recorder.max_meter_delta_kwh`, default 50 kWh), so a physically impossible spike is not recorded as energy.

#### Scenario: Implausible spike rejected without double-counting
- **WHEN** a cumulative meter jumps by more than the ceiling between two readings
- **THEN** `get_delta` returns `(None, False)` and logs a warning
- **AND** the stored baseline advances to the current reading so the next delta is computed correctly

#### Scenario: Normal delta unaffected
- **WHEN** a meter delta is within the ceiling
- **THEN** it is returned unchanged (subject to existing time-proportional scaling)

### Requirement: A schedule with no parseable `generated_at` is treated as stale

The executor SHALL treat a loaded schedule whose `meta.generated_at` is missing or unparseable as stale and hold (fall back), rather than dispatching against it.

#### Scenario: Missing generated_at holds
- **WHEN** the executor loads a schedule whose `meta` lacks a parseable `generated_at`
- **THEN** `_load_current_slot` sets a stale-schedule warning and returns no slot
- **AND** the executor holds / uses fallback instead of dispatching

#### Scenario: Fresh schedule with generated_at still dispatches
- **WHEN** the executor loads a schedule with a valid recent `generated_at`
- **THEN** the current slot is resolved and dispatched as before

### Requirement: Enabled devices targeting mock/test entities warn at startup

On startup the system SHALL log a warning (non-blocking) for each enabled device whose target entity id matches a mock/test pattern, so a production instance never silently plans around a phantom device.

#### Scenario: Enabled device on a mock entity warns
- **WHEN** an enabled device (EV, water heater, or inverter) targets an entity id containing `mock` or `test` (case-insensitive)
- **THEN** a single startup WARNING names the device and the entity id
- **AND** startup is not blocked

#### Scenario: Disabled device or real entity is silent
- **WHEN** a device is disabled, or an enabled device targets a non-mock entity
- **THEN** no mock-entity warning is emitted for it
