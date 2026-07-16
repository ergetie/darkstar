# Design: ev-dashboard-typing

## Context

Full `any` inventory and type cross-check done 2026-07-11 (also in project memory `project-real-fixes-investigations`):

**Where typing is lost (data-flow origin):**
- `config`: `Api.config()` / `Api.dashboardBundle()` are properly typed (`ConfigResponse`) → dumped into `useState<any>(null)` at `Dashboard.tsx:93` → flows as `any` through `Dashboard.tsx:825` → `CommandDomains.tsx:40` (`ResourcesCardProps.config`) → `EVTabContent` (`:542`) → `EVChargingCard` (`:51`).
- `loadBalancing`: `Api.executor.loadBalancerStatus()` is typed (`LoadBalancerStatusResponse`) but lands in `useState<any>(null)` at `CommandDomains.tsx:587`, and is also overwritten by the untyped socket handler `useSocket('live_metrics', (data: any) => ...)` at `:607-610`. Passed as `any` to `EVChargingCard` (`:52`).
- `chargers`: already typed end-to-end (fixed by `ev-goal-charging-fixes`) — no work.

**`any` inventory in `EVChargingCard.tsx`:** props `config` (:51) and `loadBalancing` (:52); `(e: any)` in `loadBalancing?.ev?.find(...)` (:98, accesses `e.charger_id`); `(entry: any)` in the excess-PV priority `.some(...)` (:105, accesses `entry.type`, `entry.charger_id`); `catch (err: any)` (:125, uses `err.message`) and (:144, only `console.error`); `[dateStr, kwh]: [string, any]` (:392, `kwh.toFixed(1)`).

**Verified type facts:**
- `LoadBalancerStatusResponse` (api.ts:361-375) and `LoadBalancerEvStatus` (api.ts:339-352) match the backend response 1:1 — `executor/engine.py:2800 get_load_balancer_status()` builds exactly those keys, and both the REST endpoint (`backend/api/routers/executor.py:96-104`) and the `live_metrics` socket payload (`executor/engine.py:1486`) call that same method. `LoadBalancerStatusCard.tsx:95,111` already uses this type on the same socket data — the pattern to copy.
- `ConfigResponse` (api.ts:64-141) does NOT declare `executor`, but the backend requires and sends it (`backend/config_migration.py:749` lists it as a required section; `GET /api/config` returns the raw dict). The shape of `executor.excess_pv.priority` is `{type: string, charger_id?: string}[]` (confirmed via the settings UI schema, `frontend/src/pages/settings/types.ts:1411-1414`). Precedent for the gap: `Dashboard.tsx:210-211` already casts around the similarly-missing `s_index` key.
- `EVChargerState.quota_schedule` is already `Record<string, number> | null` — the `[string, any]` at :392 *widens* a correct type.
- Same-pattern casts elsewhere: `ChartCard.tsx:1136-1137` (`(config as any)?.executor?.excess_pv?.custom_entity?.power_kw`), `PowerFlowCard.tsx:15-16,219-222` (`systemConfig?: any` + `flatten(obj: any)` helper).

## Goals / Non-Goals

**Goals:**
- Zero explicit `any` in `CommandDomains.tsx` and `EVChargingCard.tsx`; file-wide eslint-disable headers removed.
- `ConfigResponse` declares the `executor` section; `Dashboard.tsx` config state is typed so the fix holds at the source.
- `ChartCard.tsx`/`PowerFlowCard.tsx` drop their `executor`-related `as any` casts.

**Non-Goals:**
- No runtime behavior changes — this is a type-only change; the built bundle should behave identically.
- No full cleanup of `CommandBar.tsx`/`Executor.tsx`/`Dashboard.tsx` beyond the config state line (their other `any`s stay; separate concern).
- No fixing of latent bugs typing may reveal — those are reported to the user as findings (per project rule: never assume; surface, don't silently change).
- Not adding `s_index` or other missing `ConfigResponse` keys beyond `executor` — scope stays on the EV data flow (the `s_index` cast at Dashboard.tsx:210 remains).

## Decisions

### D1: Extend `ConfigResponse` with a typed `executor` block (not a local narrow type)

Add to `ConfigResponse`:

```ts
executor?: {
  excess_pv?: {
    priority?: { type: string; charger_id?: string }[]
    custom_entity?: { power_kw?: number; [key: string]: unknown }
    [key: string]: unknown
  }
  [key: string]: unknown
}
```

Optional keys + index signatures because the executor config section has many more keys the frontend doesn't consume; declaring only what's read keeps the type honest without maintaining a full mirror. Alternative rejected: a purpose-built `Pick`-style local type in the components — fixes the two cards but leaves `ChartCard`/`PowerFlowCard` casting, and the next consumer reinvents it.

### D2: Type the state, cast the socket payload once

- `Dashboard.tsx:93`: `useState<ConfigResponse | null>(null)`.
- `CommandDomains.tsx:587`: `useState<LoadBalancerStatusResponse | null>(null)`.
- `CommandDomains.tsx:607-610`: type the socket handler payload with the exact existing pattern from `LoadBalancerStatusCard.tsx:111`: `const payload = data as { load_balancing?: LoadBalancerStatusResponse }` — one cast at the untyped socket boundary, typed everywhere after.

### D3: Catch blocks go to `unknown` with narrowing

`catch (err: unknown)` + `err instanceof Error ? err.message : <existing fallback string>` at :125; plain `unknown` at :144 (value only passed to `console.error`). This matches the strictest lint rule and changes no behavior.

### D4: Verification is compile + lint + visual, no new tests

Type-only change: gates are `tsc` (build), eslint (no `no-explicit-any` violations remain in the two files), and a visual smoke check of the EV tab + dashboard chart + executor page. The ~2-test frontend suite has nothing meaningful to add here (frontend coverage is its own backlog item).

## Risks / Trade-offs

- [Latent mismatch surfaces] Typing may reveal property accesses that never worked (that's the point) → rule: report as finding, don't silently fix; if it blocks compilation, prefer the narrowest honest type fix and flag it in the change notes.
- [Index-signature looseness] `[key: string]: unknown` in the executor block means typos in *undeclared* keys still compile → acceptable: declared keys (`priority`, `custom_entity`) are the ones actually consumed; full mirroring is unmaintainable by hand.
- [Behavior drift] Any accidental logic edit while retyping → diff review discipline: the change should show type annotations, casts removed, and narrowing only; no expression changes except `err.message` narrowing.

## Migration Plan

Frontend-only, ships with the normal build. No migration, no rollback concerns beyond `git revert`.

## Open Questions

_None._
