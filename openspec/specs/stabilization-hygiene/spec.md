# Stabilization Hygiene

## Purpose
This specification defines hygiene and defensive-guard requirements that remove dead data/config surface area and guard against silent misbehavior: dead schedule data, misleading configuration, implausible meter deltas, bypassable schedule-staleness checks, and mock/test entities left enabled in a production instance.

## Requirements

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

### Requirement: EV dashboard data flow is explicitly typed

The EV dashboard data flow SHALL NOT use `any`: `frontend/src/components/CommandDomains.tsx` and `frontend/src/components/EVChargingCard.tsx` SHALL contain no explicit `any` types and no file-wide `@typescript-eslint/no-explicit-any` disable headers. The `config` and `loadBalancing` values SHALL carry their real types (`ConfigResponse`, `LoadBalancerStatusResponse`) from their `useState` declarations through all component props. `ConfigResponse` in `frontend/src/lib/api.ts` SHALL declare the `executor` config section (at minimum the `excess_pv.priority` and `excess_pv.custom_entity` shapes the frontend consumes), since the backend sends it as a required config section.

#### Scenario: No explicit any remains in the EV components
- **WHEN** eslint runs with `@typescript-eslint/no-explicit-any` active on `CommandDomains.tsx` and `EVChargingCard.tsx`
- **THEN** no violations and no file-wide disable headers are present

#### Scenario: Config type flows from fetch to leaf component
- **WHEN** the dashboard fetches config via `Api.config()` or `Api.dashboardBundle()`
- **THEN** the config state, the `CommandDomains` prop, and the `EVChargingCard` prop are all typed `ConfigResponse | null` (or narrower)
- **AND** `config.executor.excess_pv.priority` type-checks without casts

#### Scenario: Load balancer data typed from both sources
- **WHEN** load-balancer status arrives via REST (`Api.executor.loadBalancerStatus()`) or the `live_metrics` socket event
- **THEN** both assign into state typed `LoadBalancerStatusResponse | null`
- **AND** per-charger entries are accessed as `LoadBalancerEvStatus` without `any` callbacks

#### Scenario: Executor-config casts removed from adjacent components
- **WHEN** `ChartCard.tsx` and `PowerFlowCard.tsx` read executor excess-PV config values
- **THEN** they do so through the typed `ConfigResponse.executor` field, not `as any` casts
