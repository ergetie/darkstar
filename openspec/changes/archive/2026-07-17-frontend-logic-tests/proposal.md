# Proposal: frontend-logic-tests

## Why

The frontend's dashboard/chart/power-flow/EV data logic has zero unit tests — every existing logic-level test lives in the settings module. Darkstar has multiple users running configurations the maintainer does not (no battery, no EV charger, several chargers, no water heater), and the investigation (2026-07-13) found the risk profile is not crashes (the code guards defensively) but *silently wrong output* on those configs — e.g. the power-flow diagram silently drops the EV node when no system config is passed, and the chart's 48h data builder has never been exercised without battery fields. Manual pre-release review only covers the maintainer's own config; pure-logic tests with explicit config-variation cases are the agreed protection (decided with the user 2026-07-13: NO new component/E2E tests — logic tests only).

Premise correction baked in: the old backlog claim of "~2 frontend tests" was stale — there are 89 passing tests in 15 files, and Vitest/jsdom/RTL infrastructure is fully configured. This change adds **zero plumbing**; it adds logic tests and the minimal `export`/extraction refactors needed to reach the logic.

## What Changes

- Add unit tests for 13 investigated logic targets (chart data builder, timezone/slot math, power-flow partitioning and node enablement, battery strategy messaging, node registry accessors, dashboard day summary, price breakdown, cost drift, sparkline/bar normalization, load-balancer formatters, date-range helpers, EV card date/status logic), each including at least one "other user's config" case where applicable (no battery / no EV / zero or multiple chargers / empty data).
- Minimal enabling refactors, strictly behavior-preserving: add `export` to already-pure module-level functions; extract component-buried pure logic into named functions taking explicit parameters. No component behavior changes.
- One deliberate dedupe: the price-breakdown formula exists twice in `ChartCard.tsx` (tooltip + selected-slot panel) — extract once as a shared pure function and point both call sites at it.
- Pin surprising-but-current behaviors with tests (notably: null `systemConfig` → power-flow falls back to solar/battery/water only, excluding EV) so future changes to them are conscious decisions.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `test-hygiene`: ADDED requirement — frontend data-transform logic SHALL be unit-tested as pure functions, including config-variation cases for hardware setups the maintainer does not run.

## Impact

- **Frontend only.** New test files under `frontend/src/**`; `export` additions and pure-function extractions in: `ChartCard.tsx`, `PowerFlowCard.tsx`, `PowerFlowRegistry.ts` (no change needed — already exported), `lib/time.ts` (no change needed), `Dashboard.tsx`, `KPIStrip.tsx`, `MiniBarGraph.tsx`, `BatteryStrategyCard.tsx`, `LoadBalancerStatusCard.tsx`, `CommandDomains.tsx`, `EVChargingCard.tsx`.
- **No backend/API/DB changes. No runtime behavior change** — the compiled app must behave identically; extraction diffs must show only moved/exported code plus tests.
- **Sequencing note:** touches `ChartCard.tsx`, `CommandDomains.tsx`, `EVChargingCard.tsx`, `Dashboard.tsx` — the same files as the pending `keep-on-slot-flag` and `ev-dashboard-typing` changes. Implement these three changes sequentially (any order), never in parallel worktrees.
- **Test count:** roughly 40-50 new test cases across ~10 new test files; suite runtime impact negligible (pure functions).
