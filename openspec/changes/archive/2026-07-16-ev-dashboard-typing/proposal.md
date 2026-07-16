# Proposal: ev-dashboard-typing

## Why

The EV dashboard data flow runs on `any`: `CommandDomains.tsx` and `EVChargingCard.tsx` carry file-wide `eslint-disable @typescript-eslint/no-explicit-any` headers, and the `config`/`loadBalancing` props are untyped end-to-end. The `'throttled'` vs `'throttling'` dead-check bug (post-merge review of price-forecasting-module-5, 2026-07-09) shipped exactly where typing would have caught it at compile time. Investigation (2026-07-11) found the types already exist and match the backend — they are simply dropped at two `useState<any>` declarations — plus one genuine gap: the frontend's `ConfigResponse` type is missing the `executor` section that the backend demonstrably sends.

## What Changes

- Extend `ConfigResponse` in `frontend/src/lib/api.ts` with the `executor` section (at minimum `excess_pv.priority: {type, charger_id}[]` and `excess_pv.custom_entity`), closing the one real frontend/backend type gap.
- Fix the type-loss origin: `Dashboard.tsx`'s `useState<any>(null)` for config becomes `ConfigResponse | null` (the fetch calls are already typed; the state discards it).
- De-`any` `CommandDomains.tsx`: `config` props/params, `loadBalancing` state (→ `LoadBalancerStatusResponse | null`), socket handler payload (typed cast, same pattern as `LoadBalancerStatusCard.tsx`).
- De-`any` `EVChargingCard.tsx`: `config`/`loadBalancing` props, `.find()`/`.some()` callback params (→ `LoadBalancerEvStatus` / priority-entry type), `catch (err: any)` → `unknown` with `instanceof Error` narrowing, remove the redundant `[string, any]` annotation on `quota_schedule` entries (it widens an already-correct `Record<string, number>`).
- Remove the file-wide `eslint-disable @typescript-eslint/no-explicit-any` headers from both components.
- Let `ChartCard.tsx` and `PowerFlowCard.tsx` drop their line-level `(config as any).executor...` casts, now nearly free with the extended `ConfigResponse`.
- Out of scope: full `any` cleanups of `CommandBar.tsx` and `Executor.tsx` (same disease, separate backlog concern); any runtime behavior change (this change is type-only — compiled output behavior must be identical except where types reveal actual bugs, which get reported, not silently fixed).

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `stabilization-hygiene`: ADDED requirement — the EV dashboard data flow SHALL be explicitly typed (no `any`), and `ConfigResponse` SHALL declare the `executor` config section the backend sends.

## Impact

- **Frontend only:** `frontend/src/lib/api.ts`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/CommandDomains.tsx`, `frontend/src/components/EVChargingCard.tsx`, `frontend/src/components/ChartCard.tsx`, `frontend/src/components/PowerFlowCard.tsx`.
- **No backend, DB, or API changes.** No runtime behavior change intended; `tsc`/eslint/build are the primary gates.
- **Risk surface:** typing may surface latent mismatches — per project rules those are findings to report, not to fix silently in this change.
