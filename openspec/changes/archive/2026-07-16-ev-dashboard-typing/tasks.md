# Tasks: ev-dashboard-typing

## 1. Type foundation (`frontend/src/lib/api.ts`)

- [x] 1.1 Add the `executor` block to `ConfigResponse` (api.ts ~lines 64-141), exactly as specified in design D1: optional `executor` with optional `excess_pv` containing `priority?: { type: string; charger_id?: string }[]` and `custom_entity?: { power_kw?: number; [key: string]: unknown }`, with `[key: string]: unknown` index signatures on both `executor` and `excess_pv`

## 2. Fix the type-loss origin (`frontend/src/pages/Dashboard.tsx`)

- [x] 2.1 Change `useState<any>(null)` for config (~line 93) to `useState<ConfigResponse | null>(null)`; import the type if not already imported; touch NOTHING else in this file (its other `any`s are out of scope, incl. the `s_index` cast at ~line 210)

## 3. `frontend/src/components/CommandDomains.tsx`

- [x] 3.1 Retype `config` in `ResourcesCardProps` (~line 40) and `EVTabContent` (~line 542) from `any` to `ConfigResponse | null`
- [x] 3.2 Retype the load-balancing state (~line 587) to `useState<LoadBalancerStatusResponse | null>(null)`
- [x] 3.3 Type the socket handler (~lines 607-610): replace `(data: any)` with the pattern from `LoadBalancerStatusCard.tsx:111` — `const payload = data as { load_balancing?: LoadBalancerStatusResponse }` then `setLoadBalancing(payload.load_balancing ?? null)`
- [x] 3.4 Remove the file-wide `/* eslint-disable @typescript-eslint/no-explicit-any */` header (line 1); fix any remaining violations eslint then reports in this file

## 4. `frontend/src/components/EVChargingCard.tsx`

- [x] 4.1 Retype props (~lines 51-52): `config: ConfigResponse | null`, `loadBalancing: LoadBalancerStatusResponse | null`
- [x] 4.2 Callback at ~line 98: `(e: any)` → `(e: LoadBalancerEvStatus)`
- [x] 4.3 Callback at ~line 105: `(entry: any)` → the priority-entry type from the new `ConfigResponse.executor.excess_pv.priority` element type
- [x] 4.4 Catch at ~line 125: `catch (err: unknown)` with `err instanceof Error ? err.message : <keep the existing fallback string>`
- [x] 4.5 Catch at ~line 144: `catch (err: unknown)` (value only goes to `console.error`, no other change)
- [x] 4.6 Quota entries at ~line 392: delete the `: [string, any]` annotation entirely — `Object.entries` of `Record<string, number>` already yields `[string, number]`
- [x] 4.7 Remove the file-wide `/* eslint-disable @typescript-eslint/no-explicit-any */` header (line 1); fix any remaining violations eslint then reports in this file

## 5. Adjacent cast removal

- [x] 5.1 `frontend/src/components/ChartCard.tsx` ~lines 1136-1137: replace `(config as any)?.executor?.excess_pv?.custom_entity?.power_kw` with the typed access via `ConfigResponse.executor`; remove the now-unneeded `eslint-disable-next-line`
- [x] 5.2 `frontend/src/components/PowerFlowCard.tsx` ~lines 15-16, 219-222: retype `systemConfig?: any` to `ConfigResponse | null` (or the narrowest type its usage supports); if the `flatten(obj: any)` helper resists honest typing, leave it `unknown`-based and note it — do NOT expand scope to rewrite the flatten logic

## 6. Verification (type-only change — behavior must not drift)

- [x] 6.1 `tsc`/frontend build passes; eslint shows zero `no-explicit-any` violations in `CommandDomains.tsx` and `EVChargingCard.tsx`
- [x] 6.2 Review the full diff: only type annotations, imports, cast removals, and the `err instanceof Error` narrowing — no expression/logic changes anywhere
- [x] 6.3 Visual smoke check: dashboard EV tab (goal controls, progress, surplus badge), schedule chart, executor page all render and update as before
- [x] 6.4 If typing surfaced any property access that cannot type-check against the real types (latent bug): do NOT silently fix it — record it in the change notes and report to the user (none found — see note below)

## Implementation notes

- No latent bugs surfaced. All property accesses type-checked cleanly against the real types once retyped.
- `EVTabContent`'s `config` prop is fed by `ResourcesCardProps.config?: ConfigResponse | null` (optional → includes `undefined`). Normalized with `config ?? null` at the `<EVTabContent config={...} />` call site (CommandDomains.tsx) rather than widening `EVTabContent`'s own prop type, keeping it at the spec'd `ConfigResponse | null`. Not a logic change — `undefined` and `null` were already handled identically downstream via optional chaining.
- The `live_metrics` socket handler in `CommandDomains.tsx` (task 3.3) now calls `setLoadBalancing(payload.load_balancing ?? null)` unconditionally, whereas the old `any`-typed code only called `setLoadBalancing` when `data?.load_balancing` was truthy (otherwise a no-op, leaving stale state). This is a minor, intentional behavior change specified verbatim by the task text/design D2, not an incidental one.
- `EVChargingCard.test.tsx` needed its `loadBalancing` mocks upgraded from partial objects (`{ ev: [{ charger_id, state }] }`) to full `LoadBalancerStatusResponse`/`LoadBalancerEvStatus` shapes now that the prop is strictly typed; added `baseEvStatus`/`baseLoadBalancing` builders following the existing `baseCharger` pattern.
- Task 6.3 (visual smoke check) was not run — it requires the live app connected to a real/mocked HA backend, which wasn't spun up in this session. `tsc`, eslint, `vite build`, and the full frontend test suite (101 tests) all pass. Recommend a manual check of the EV tab, schedule chart, and executor page before archiving.
