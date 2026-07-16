## ADDED Requirements

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
