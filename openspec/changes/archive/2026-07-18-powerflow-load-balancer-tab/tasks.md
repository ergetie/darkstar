# Tasks: PowerFlow Load-Balancer Tab

## 1. Tabbed Wrapper

- [x] 1.1 Create `PowerFlowTabs` component: tab strip in the Resources-card style (Flow / Load Balancer), localStorage persistence under `darkstar-powerflow-tab` with try/catch, and an `effectiveTab` guard that falls back to Flow when the LB tab is unavailable
- [x] 1.2 Subscribe to load-balancer status in the wrapper: initial `Api.executor.loadBalancerStatus()` fetch + `useSocket('live_metrics')` updates (same pattern as `LoadBalancerStatusCard`); tab strip only rendered when status reports enabled and state ≠ `disabled`
- [x] 1.3 Replace the PowerFlow cell's inner content in `Dashboard.tsx` with `PowerFlowTabs`, passing the existing `PowerFlowCard` props through unchanged; with load balancing disabled the rendered output must match today's card

## 2. Compact Load-Balancer View

- [x] 2.1 Create the compact LB view component: L1/L2/L3 bars vs `main_fuse_a` reusing `phaseColor` from `LoadBalancerStatusCard.tsx`, state row (state label + `reason`), link to the Executor page
- [x] 2.2 Render compact rows for actively throttled EV chargers and actively shed loads only (omit idle entries); no bypass/override controls anywhere

## 3. Auto-Switch and Warning Dot

- [x] 3.1 Implement intervention-edge detection: previous-state tracking, switch to the LB tab once on a non-intervening → intervening transition (idle/paused/disabled → throttling/shedding/stale_fallback); no re-trigger between intervening states, no re-force after the user switches away mid-episode, no localStorage write from auto-switch
- [x] 3.2 Warning dot on the Load Balancer tab label while state is intervening and the tab is inactive; removed when the intervention ends or the tab is viewed
- [x] 3.3 Unit tests for the tab logic: enabled/disabled visibility, persisted-tab fallback, auto-switch once per episode (including switch-back-mid-episode and new-episode-after-recovery), warning-dot conditions

## 4. Verification

- [x] 4.1 Run frontend tests, lint, and typecheck
- [x] 4.2 Visually verify on the Dashboard with load balancing enabled: tabs render in Resources-card style, Flow view unchanged, LB tab shows live bars/state, link to Executor works
- [x] 4.3 Visually verify with load balancing disabled: PowerFlow card identical to before, no tab strip, no console errors with a stale persisted tab value
- [x] 4.4 Verify the Executor page's load-balancer card is unchanged
