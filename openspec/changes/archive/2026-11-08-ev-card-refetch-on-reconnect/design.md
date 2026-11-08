# Design

## Decision

Refetch inside `useEvChargers` using `useSocketStatus()` (from `frontend/src/lib/hooks.ts`), rather than calling `refreshEvChargers` from the Dashboard reconnect effect.

Implementation sketch: track a `wasConnected` ref; when status becomes `connected` and `wasConnected` is already true, call `refresh()`; then set it true. This mirrors the existing pattern in `Dashboard.tsx` (~lines 450-466).

## Rationale

- The hook already owns every other refetch trigger (mount and four socket events), so reconnect belongs with them. Any future consumer gets correct behaviour without remembering to wire it.
- Dashboard's effect stays untouched and `onEvRefresh` keeps working, so there is no double fetch: `fetchAllData()` does not fetch chargers, and only the hook's effect does on reconnect.
- Skipping the first `connected` avoids duplicating the mount fetch.
- The hook's `seqRef` already discards stale responses, so overlapping fetches are safe.
- `refresh` is a no-op when `enabled` is false, which satisfies the EV-disabled scenario.

## Decision: migrate EVTabContent to the hook (scope widened)

The EV card the user actually sees is `EVTabContent` in `CommandDomains.tsx`, which had a duplicate `fetchChargers` plus the same four socket handlers and no reconnect refetch. It now calls `useEvChargers(enabled)` and passes `refresh` down as `onRefresh`.

- Hook extended additively with `loading` and `error` (same semantics the tab had: `loading` while a fetch is in flight, `error` set on failure and cleared on the next success, stale responses discarded via `seqRef`). Existing consumers (Dashboard, command bar, power-flow EV node) destructure only `chargers` and `refresh`, so they are unaffected. When `enabled` goes false, the hook also invalidates in-flight requests and resets `loading` and `error`.
- `plan_pending` handling and the `planner_error` refetch are covered by the hook's existing handlers; the tab's UI states (loading, error, empty) remain local in `EVTabContent`.
- `enabled`: `EVTabContent` takes an `enabled` prop set from `hasEvCharger`, the same flag the Dashboard passes to its own hook instance. The tab is only reachable when `hasEvCharger` is true, so this is equivalent to always-on today and stays correct if that changes.
- The `live_metrics` load-balancer fetch stays as is (self-heals on the next tick).
- Shared instance rejected: the Dashboard and the tab each run their own hook, so each event causes two cheap GETs. Sharing would need a context provider or module-level store threaded through `ResourcesDomain` props or a new provider, which is a larger change than this fix warrants; the `seqRef` guard keeps each instance consistent.

## Alternative rejected

Calling `refreshEvChargers` in the Dashboard reconnect effect: works, but couples correctness to one caller and adds `refreshEvChargers` to that effect's dependencies, which risks re-triggering `fetchAllData` when `enabled` changes.

## Risks

Reconnect flapping causes extra GETs. The endpoint is cheap, and Socket.IO reconnect backoff is already capped.

## Audit notes

Audit of `useSocket(...)` consumers for the reconnect gap (notes only, nothing fixed here). "Gap" means state fetched on mount and updated via socket events, with no refetch after a reconnect.

- `components/CommandDomains.tsx` `EVTabContent` (rendered by `ResourcesDomain`, the EV tab card): HIGH, and in scope. It kept its own `fetchChargers` with mount plus the same four socket events and no reconnect refetch, so it showed the stale data from the bug report. Fixed here by migrating it to `useEvChargers` (see the decision above). Its `loadBalancerStatus` gap is mild (see below) and left as is.
- `components/EVChargingCard.tsx`: no gap. It receives the charger as props and its only `useSocket` (`planner_error`) is a UI reset, with no fetch.
- `components/CommandDomains.tsx` load balancer status in `EVTabContent`: mild gap. It fetches on mount and updates on `live_metrics`, which is pushed continuously, so it self-heals on the next tick.
- `components/PowerFlowTabs.tsx` and `components/LoadBalancerStatusCard.tsx`: same pattern, mount fetch plus `live_metrics`. They self-heal on the next `live_metrics` tick after reconnect, so the gap is negligible.
- `components/aurora/ModelTrainingCard.tsx`: no meaningful gap. It polls status every 5 s while mounted. A `training_progress` completion event missed while suspended is only reconciled by the poll of status, not of history, so the history list may stay stale until remount.
- `components/Sidebar.tsx`: no gap. It only uses `useSocketStatus` for the indicator and fetches the version once, which is static.
- `pages/Executor.tsx`: no gap. `fetchAll` polls every 30 s as a backup to `executor_status`.
- `components/CommandBar.tsx`: no gap. Its socket handlers only drive transient UI state (progress, errors, boost), and `schedule_updated` and `water_boost_updated` handlers do not own fetched data.
- `pages/Dashboard.tsx`: reconnect already calls `fetchAllData()`. Note its effect depends on `fetchAllData` identity, so identity changes while connected would refetch (not changed here).
