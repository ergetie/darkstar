# PowerFlow Load-Balancer Tab

## Why

The load balancer protects the main fuse (shedding loads, throttling EV charging, stale-sensor fallback), but its live status is only visible on the Executor page. The Dashboard — the page people actually look at — gives no indication of phase loading or that an intervention is happening right now. The dashboard is already full, so this must not add a new card.

## What Changes

- The PowerFlow card on the Dashboard becomes a tabbed card, in the same style as the Energy Resources card (`ResourcesDomain` in `CommandDomains.tsx`): tabs **Flow** and **Load Balancer**.
- The **Load Balancer tab** shows a compact live view: L1/L2/L3 phase-current bars vs main fuse rating (color-coded), current state (idle / throttling / shedding / paused / stale-sensor fallback) with its reason, and active EV-throttle / shed details.
- The Load Balancer tab is only shown when load balancing is enabled; otherwise the card renders exactly as today (no tab strip needed with a single view).
- **Auto-switch on intervention:** when the balancer transitions into an active intervention state (throttling, shedding, stale fallback), the card switches to the Load Balancer tab once, at the transition. The user can freely switch back; the card does not force them again for the same episode.
- **Warning indicator:** while an intervention is active and the Flow tab is selected, the Load Balancer tab label shows a warning dot.
- Tab choice persists (localStorage), same as the Resources card.
- No bypass/override control (explicitly decided against). The Executor page's full `LoadBalancerStatusCard` stays exactly as is.

Out of scope: any backend change (data already arrives via the `live_metrics` WebSocket payload's `load_balancing` key and `/api/executor/load-balancer/status`), changes to the Executor page, manual override controls.

## Capabilities

### New Capabilities

- `powerflow-load-balancer-tab`: Tabbed PowerFlow card on the Dashboard with a live load-balancer view — tab visibility rules, compact status content, auto-switch-once behavior, and warning indicator.

### Modified Capabilities

<!-- None. `dashboard-layout` grid requirements are unchanged (same cell, same grid); `phase-load-balancing` backend behavior is untouched. -->

## Impact

- **Frontend only.**
  - `frontend/src/pages/Dashboard.tsx`: PowerFlow cell (row 3, col 2) gets the tabbed wrapper and the load-balancer data subscription.
  - New compact load-balancer view component (reusing display helpers from `LoadBalancerStatusCard.tsx`, e.g. `phaseColor`, without changing that card).
  - Tab pattern copied from `ResourcesDomain` in `CommandDomains.tsx` (localStorage persistence, conditional tab).
- Data sources already exist: `Api.executor.loadBalancerStatus()` for initial state + `useSocket('live_metrics')` for live updates — the same pair `LoadBalancerStatusCard` uses.
- Verification must cover configs with load balancing disabled (card must look unchanged) per the backlog rule about other users' configs.
