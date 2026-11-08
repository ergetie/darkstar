# Proposal

## Why

On the mobile PWA, after iOS suspended the app, the dashboard chart showed the fresh plan but the EV card kept a stale `/api/ev/chargers` response (old day chips, Tesla at 31% SoC instead of 75%, 5.4 kWh delivered instead of current values). Only force-quitting fixed it.

Root cause: on socket reconnect `Dashboard.tsx` runs `fetchAllData()` (bundle, history, schedule, deferred data) but never refreshes EV chargers. `useEvChargers` fetches only on mount and on socket events (`ev_manual_charge_updated`, `ev_schedule_changed`, `schedule_updated`, `planner_error`), so events missed while suspended are never replayed. There is no service worker, so this is not a caching issue.

## What Changes

- `useEvChargers` refetches `/api/ev/chargers` when the socket reconnects after a drop (not on the initial connect).
- `EVTabContent` (the EV card on the dashboard's Energy Resources EV tab) drops its own fetch logic and socket handlers and uses `useEvChargers`, so it gets the same reconnect refetch from a single data source.
- `useEvChargers` additionally exposes `loading` and `error` (additive) so the tab keeps its loading and error UI.
- Vitest coverage proving a reconnect triggers a refetch, for the hook and for the EV tab.
- Audit of other socket-only data hooks for the same gap (findings recorded as notes only, no fixes).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `dashboard-connection-resilience`: reconnect reconciliation also covers the EV charger state.

## Impact

- `frontend/src/lib/useEvChargers.ts` (behaviour)
- `frontend/src/lib/useEvChargers.test.tsx` (new tests)
- `frontend/src/components/CommandDomains.tsx` (`EVTabContent` migrated to the hook)
- `frontend/src/components/CommandDomains.test.tsx` (EV tab reconnect test)
- No backend, API, or schema changes. `Dashboard.tsx` is unchanged.
- The separate `live_metrics` load-balancer fetch in `EVTabContent` is left as is.
