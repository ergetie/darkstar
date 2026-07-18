# Design: PowerFlow Load-Balancer Tab

## Context

- Dashboard row 3, cell 2 wraps `PowerFlowCard` in a plain `Card` (`Dashboard.tsx` ~line 757).
- The tab pattern to copy lives in `ResourcesDomain` (`CommandDomains.tsx` ~line 400): `useState` + localStorage persistence (`darkstar-resources-tab`), a conditional tab (`ev` only when `hasEvCharger`), and an `effectiveTab` guard so a persisted-but-unavailable tab falls back safely.
- Load-balancer data: `LoadBalancerStatusResponse` (`lib/api.ts:368`) with `enabled`, `state` (`disabled | idle | throttling | shedding | paused | stale_fallback`), `reason`, `main_fuse_a`, `phase_current_a`, `phase_headroom_a`, `ev[]`, `shed[]`. Delivered by `Api.executor.loadBalancerStatus()` (initial) and the `live_metrics` WebSocket payload's `load_balancing` key (live) — exactly how `LoadBalancerStatusCard` on the Executor page consumes it.
- `LoadBalancerStatusCard.tsx` exports reusable helpers (`phaseColor`, `formatAge`).

## Goals / Non-Goals

**Goals:**
- Live load-balancer visibility on the Dashboard without adding a card or growing the grid.
- Attention-grabbing exactly when the balancer intervenes; invisible cost when it doesn't.
- Zero backend changes; Executor page untouched.

**Non-Goals:**
- Manual bypass/override controls.
- Replacing or restyling the Executor page's detailed card.
- Any change to load-balancer behavior, API shape, or WebSocket payload.

## Decisions

1. **Tabbed wrapper around the PowerFlow cell, not inside `PowerFlowCard`.** A new component (e.g. `PowerFlowTabs`) owns the tab strip and renders either the existing `PowerFlowCard` (Flow) or the new compact LB view. `PowerFlowCard` itself is untouched. Rationale: `PowerFlowCard` is a visualization component; tab state and LB data are dashboard concerns.

2. **Tab strip only rendered when the LB tab is available** (`status.enabled && state !== 'disabled'`). With load balancing off, the component renders exactly today's card — single view, no tab strip. Determination uses the same status object as the tab content, so there is no separate config check to drift.

3. **Data subscription mirrors `LoadBalancerStatusCard`:** one initial `Api.executor.loadBalancerStatus()` fetch + `useSocket('live_metrics')` updates, held in the new wrapper. No new polling. The Dashboard already has a live-metrics subscription for power flows; the LB subscription lives in the wrapper to keep `Dashboard.tsx` changes minimal.

4. **Compact LB view is a new small component, reusing exported helpers** (`phaseColor`) from `LoadBalancerStatusCard.tsx` rather than extracting/rewriting that card. Content: three phase bars (current vs fuse, color-coded), a one-line state row (state label + `reason`), and compact rows for active EV throttles and shed loads only (idle entries omitted — this is the "at a glance" view; details live on the Executor page, linked from the tab).

5. **Auto-switch-once semantics via edge detection.** Track the previous `state`; when it transitions from a non-intervening state (`idle`/`paused`/`disabled`) to an intervening one (`throttling`/`shedding`/`stale_fallback`), set the active tab to Load Balancer — once per episode. Transitions *between* intervening states (e.g. throttling → shedding) do not re-trigger. If the user switches back to Flow during an episode, nothing forces them again until the balancer has returned to non-intervening and a new episode starts. The auto-switch does not overwrite the persisted tab preference in localStorage — only explicit clicks persist.

6. **Warning dot on the tab label** whenever `state` is intervening and the LB tab is not active. Same visual language as existing status dots (e.g. the `bg-bad`/`bg-accent` dot idiom already used in the LB card).

7. **`localStorage` key `darkstar-powerflow-tab`**, same read/write-with-try/catch pattern as `darkstar-resources-tab`, with an `effectiveTab` guard: persisted "lb" renders Flow when the LB tab is unavailable.

8. **Addendum (post-implementation): `PowerFlowCard` was touched after all, for visual polish only.** Decision 1 said `PowerFlowCard` itself would be untouched. During review, two small unrelated cosmetic fixes were requested and applied directly to `PowerFlowCard.tsx`: the SVG background grid pattern was removed, and the canvas height grew (160→180) with `BUS_Y` anchored to a fixed value instead of `H / 2`, giving the bottom row more clearance from the card edge. Neither change touches layout logic, data flow, or the tab/LB behavior described above — they're pure rendering tweaks to the existing Flow view, made because the tabbed card made the old spacing more noticeable.

## Risks / Trade-offs

- [Auto-switch could interrupt someone reading the Flow view] → It fires only on the edge into an intervention (rare, and precisely the moment it matters); user can switch back and is not re-forced within the episode.
- [State flapping at the intervention boundary (idle ↔ throttling each tick) would re-trigger switches] → Episode logic treats a new intervention edge as a new episode; if flapping is observed in practice, add a short cooldown (e.g. ignore edges within N seconds of the user manually leaving the tab). Keep simple first.
- [WebSocket gap: `live_metrics` may not arrive (executor down)] → Same behavior as the Executor card: initial REST fetch gives a snapshot; the compact view shows the state it has. No new staleness machinery in v1.
- [Dashboard.tsx is large and busy] → Keep the diff surgical: replace the cell's inner content with the wrapper component; all new logic lives in new files.
- [Other users run without load balancing] → Verification must include the disabled config: card must render pixel-identical to today (no tab strip).
