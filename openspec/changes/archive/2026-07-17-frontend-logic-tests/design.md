# Design: frontend-logic-tests

## Context

Full investigation 2026-07-13 (also condensed in project memory `project-real-fixes-investigations`). Facts the implementer needs:

- **Infrastructure exists and works:** Vitest 4 + jsdom + RTL configured (`frontend/vitest.config.ts` with `globals: true`, `setupFiles: './src/test/setup.ts'`, include pattern `src/**/*.test.{ts,tsx}`); `pnpm test` runs `vitest run`; 89 existing tests in 15 files all pass. Add nothing here.
- **Pattern to imitate:** `frontend/src/pages/settings/__tests__/utils.test.ts` and `logic.test.ts` — plain pure-function tests, no rendering.
- **Strategy (user-decided):** pure-logic tests only. No new component render tests, no E2E. Config-variation cases are the point: other users run no-battery / no-EV / multi-charger / no-water setups the maintainer never sees.
- **Target inventory with locations** (from the investigation; line numbers approximate):

| # | Target | Location | Extraction |
|---|---|---|---|
| 1 | `buildLiveData()` 48h chart data builder | `ChartCard.tsx:1575-1820` (module-level, no closure) | add `export` |
| 2 | `clampTo48hISO`, `isoToLocal`, `ymdLocal`, `isToday`, `isTomorrow`, `formatHour`, `filterSlotsByDay` | `lib/time.ts:1-49` | none (exported) |
| 3 | `partitionFlow`, `cxFor`, `exitYFor`, `toPathD` | `PowerFlowCard.tsx:63-98` (module-level) | add `export` |
| 4 | `enabledNodes` config filter + `flatten()` | `PowerFlowCard.tsx:217-249` (inside `useMemo`) | extract `computeEnabledNodes(configMap, data)` |
| 5 | `NODE_REGISTRY` accessors + `fmtKw`/`fmtKwh` | `PowerFlowRegistry.ts:41-120` | none (exported) |
| 6 | `todaySummary` phase-merge | `Dashboard.tsx:487-542` (IIFE in render) | extract fn taking `slots` param |
| 7 | Price-breakdown formula (duplicated) | `ChartCard.tsx:90-117` and `:980-989` | extract shared `splitPriceBreakdown(value, pricing)`, dedupe both sites |
| 8 | Cost-drift aggregation | `KPIStrip.tsx:16-31` (render body) | extract `computeCostDrift(costSeries)` |
| 9 | Bar normalization | `MiniBarGraph.tsx:20-30` (`useMemo`) | extract pure fn |
| 10 | `renderSocContext` strategy sentence + sparkline normalization | `BatteryStrategyCard.tsx:138-206`, `:62-75` | extract pure fns of explicit params |
| 11 | `phaseColor`, `chargerSetpointText`, `formatAge` | `LoadBalancerStatusCard.tsx:39-51,88-92` (module-level) | add `export` |
| 12 | `getDefaultDatesForPeriod`, `validateDateRange` | `CommandDomains.tsx:80-144` (inner fns; validate mixes in `setDateError`) | extract; split pure predicate from state-setting wrapper |
| 13 | EV date helpers + progress/status derivation | `EVChargingCard.tsx:12-30` (module-level) and `:152-175` (inline) | export helpers; extract `deriveChargerStatus(charger, balancerEv)` + progress fn |

- **Behaviors to pin (currently surprising but correct-by-decision):** null `systemConfig` → power-flow shows only `['solar','battery','water']`, silently excluding EV (`PowerFlowCard.tsx:235-249`); `vat = -100` guard in price breakdown; `range = max - min || 1` div-by-zero guards; `progressPercent` returns 0 when `required_kwh` is 0.

## Goals / Non-Goals

**Goals:**
- Unit tests for all 13 targets, each with the config-variation cases listed in tasks; roughly 40-50 cases total.
- All extractions strictly behavior-preserving; the app's compiled behavior is identical.
- The two duplicated price-breakdown implementations become one shared function.

**Non-Goals:**
- No new component/render tests, no E2E, no snapshot tests.
- No fixing of behaviors the tests reveal as *questionable* (e.g. the EV-excluding null-config fallback) — pin current behavior, flag findings to the user; changing them is a separate decision.
- No test-coverage tooling/thresholds (no coverage gates in CI) — this change adds tests, not policy.
- No touching the settings module's existing tests.

## Decisions

### D1: Extract by `export`, not by moving files

Targets that are already module-level pure functions just get `export` added in place. Component-buried logic is extracted to a named function *in the same file* (or `lib/` only when shared across files — the price breakdown is the single such case: it goes to a new small module, e.g. `frontend/src/lib/price.ts`, because two components-worth of call sites use it... it has one file today but two call sites; keep it in `ChartCard.tsx` as an exported function unless a second file needs it — implementer's judgment, bias to same-file). Rationale: minimal diff, no import-churn across the app, easy review against the "no behavior change" rule.

### D2: Test files live next to their subject, following the repo's existing mixed convention

Existing tests use both `X.test.tsx` beside the component and `__tests__/` folders. Use `X.test.ts` beside the file under test (matches `lib/hooks.test.ts`, `logic.test.ts`). Pure `.ts` extension — these tests import functions, never render.

### D3: Config-variation cases are mandatory per target, not a separate suite

Each target's test file includes its "other user's config" cases inline (no-battery, no-EV, zero/multiple chargers, empty arrays, missing optional fields) rather than a separate "config matrix" suite. Rationale: keeps each behavior and its edge cases in one place; a future edit to the function sees all its contracts together.

### D4: Time-dependent logic is tested with injected/fixed time

`lib/time.ts` and date-range helpers depend on "now". Use vitest fake timers (`vi.setSystemTime`) with fixed instants — including one instant near UTC midnight and one across a Europe/Stockholm DST boundary (the TZ is hardcoded in `time.ts`). No test may depend on the wall clock of the machine running it (that is how flaky tests are born).

### D5: `todaySummary` and `renderSocContext` return values, not JSX, where feasible

Extraction should shape these as data-returning functions (string/struct) with the component doing only presentation. Where the existing code builds a plain string already (both cases do), this is natural; do not convert JSX-producing code into string-producing code if behavior would change — in that case extract the decision logic only.

## Risks / Trade-offs

- [Behavior drift during extraction] Moving logic out of `useMemo`/IIFE can subtly change evaluation timing → all extractions keep the `useMemo`/call-site wrapper; only the function body moves. Diff review rule: extraction commits show moved code + `export` + tests, nothing else.
- [Pinning wrong behavior] Tests encode current behavior including the surprising null-config EV exclusion → deliberate (D3/Non-Goals): pinning makes future change conscious; the change notes must list every pinned surprise so the user can decide separately.
- [File-collision with pending changes] Same files as `keep-on-slot-flag` and `ev-dashboard-typing` → sequencing rule in proposal Impact; whichever change lands last rebases trivially (tests + exports rarely conflict semantically with those diffs).
- [Fake-timer leakage] `vi.setSystemTime` without restore can poison other tests → `afterEach(() => vi.useRealTimers())` in every file using fake timers.

## Migration Plan

None — additive tests + behavior-preserving refactors, ships with the normal build. Rollback = `git revert`.

## Open Questions

_None — strategy, scope, and targets decided with the user 2026-07-13._
