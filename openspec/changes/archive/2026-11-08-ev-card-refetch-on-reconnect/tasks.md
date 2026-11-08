## 1. Implementation

- [x] 1.1 In `frontend/src/lib/useEvChargers.ts`, import `useSocketStatus` from `./hooks` and add a `wasConnectedRef`
- [x] 1.2 Add an effect on the socket status that calls `refresh()` when status becomes `connected` and `wasConnectedRef.current` is already true, then sets the ref to true
- [x] 1.3 Update the hook's doc comment to mention reconnect refetch

## 2. Tests

- [x] 2.1 Create `frontend/src/lib/useEvChargers.test.tsx` (vitest, mock `Api.ev.chargers` and `useSocketStatus`): initial connect causes exactly one `/api/ev/chargers` fetch
- [x] 2.2 Test: `connected` -> `connecting`/`offline` -> `connected` triggers exactly one extra fetch and the returned chargers update to the new response
- [x] 2.3 Test: with `enabled=false`, reconnect triggers no fetch
- [x] 2.4 Run `cd frontend && pnpm vitest run src/lib/useEvChargers.test.tsx` and `./scripts/lint.sh`

## 3. Widen scope: EV tab card

- [x] 3.1 Extend `useEvChargers` with `loading` and `error` (additive, other consumers unchanged)
- [x] 3.2 Migrate `EVTabContent` in `frontend/src/components/CommandDomains.tsx` to `useEvChargers(enabled)`; remove its duplicate fetch and socket handlers; pass `refresh` as `onRefresh`; keep the `live_metrics` fetch
- [x] 3.3 Add an EV tab reconnect test in `frontend/src/components/CommandDomains.test.tsx` and keep existing tests passing
- [x] 3.4 Record the enabled and shared-instance decisions in `design.md`

## 4. Audit (notes only, no fixes)

- [x] 4.1 Check every `useSocket(...)` consumer that fetches only on mount plus socket events, starting with `frontend/src/components/EVChargingCard.tsx`, `CommandDomains.tsx`, `PowerFlowTabs.tsx`, `LoadBalancerStatusCard.tsx`, `aurora/ModelTrainingCard.tsx`, `Sidebar.tsx` and `frontend/src/pages/Executor.tsx`, for the same reconnect gap
- [x] 4.2 Record findings as notes in this change's `design.md` under "Audit notes"; do not fix them here
