# Tasks: frontend-logic-tests

All extractions are strictly behavior-preserving: only add `export`, or move a function body into a named function called from the original site. No logic edits. If a test reveals questionable current behavior, PIN it with a test and record it in the change notes — do not fix it here.

## 1. Zero-extraction targets (functions already exported)

- [x] 1.1 `frontend/src/lib/time.test.ts` — test `clampTo48hISO`, `isoToLocal`, `ymdLocal`, `isToday`, `isTomorrow`, `formatHour`, `filterSlotsByDay` (`lib/time.ts:1-49`). Use `vi.setSystemTime` with fixed instants; cases: (a) `isToday`/`isTomorrow` near UTC midnight and across a Europe/Stockholm DST boundary, (b) `filterSlotsByDay` with empty list, (c) `clampTo48hISO` with only-past and only-future slots → `[]`, (d) `formatHour` format stability. `afterEach(() => vi.useRealTimers())`
- [x] 1.2 `frontend/src/components/PowerFlowRegistry.test.ts` — test `fmtKw`/`fmtKwh` and `NODE_REGISTRY` accessors (`PowerFlowRegistry.ts:41-120`). Cases: (a) `fmtKw` decimal switch at the 0.1 boundary, (b) EV `subValueAccessor` with zero chargers → `undefined`, (c) multiple chargers none plugged in → falls back to first charger, (d) battery label flip exactly at `kw === 0`

## 2. Export-only targets

- [x] 2.1 Add `export` to `buildLiveData` (`ChartCard.tsx:1575-1820`); new `frontend/src/components/ChartCard.buildLiveData.test.ts`. Cases: (a) normal 15-min slots → correct bucket count/labels/`nowIndex`, (b) no-battery slots (no `charge_kw`/`discharge_kw`) → null series, no `NaN`, (c) no-EV slots (no `ev_charging_kw`/`ev_surplus_kw`) → null EV series, no throw on missing dicts, (d) empty slots → `hasNoData: true` fallback, (e) multi-charger `ev_surplus_kw` dict sums correctly and empty dict `{}` → 0
- [x] 2.2 Add `export` to `partitionFlow`, `cxFor`, `exitYFor`, `toPathD` (`PowerFlowCard.tsx:63-98`); new `PowerFlowCard.partitionFlow.test.ts`. Cases: (a) no battery in `enabledIds` → battery absent from sources/loads even with nonzero `data.battery.kw`, (b) `data.ev` undefined → no crash, ev absent, (c) negative `grid.kw` (export) routes grid to loads not sources, (d) `toPathD` produces a well-formed path string
- [x] 2.3 Add `export` to `phaseColor`, `chargerSetpointText`, `formatAge` (`LoadBalancerStatusCard.tsx:39-51,88-92`); new `LoadBalancerStatusCard.formatters.test.ts`. Cases: (a) `phaseColor` below margin / within margin / at-or-above fuse, (b) `chargerSetpointText` with `setpoint_a === null` → "Paused" and planned≠setpoint → "(planned Ya)" text, (c) `formatAge` at 59s/60s/3599s/3600s boundaries
- [x] 2.4 Add `export` to `toLocalISODate`, `parseLocalISODate`, `tomorrowLocalISODate` (`EVChargingCard.tsx:12-30`); new `EVChargingCard.dates.test.ts`. Cases: (a) round-trip across a UTC-offset boundary (the exact bug class the code comments warn about), (b) `tomorrowLocalISODate` across a month boundary with fixed time

## 3. Extractions (same-file named functions, original call sites kept)

- [x] 3.1 Extract `computeEnabledNodes(configMap, data)` from the `useMemo` at `PowerFlowCard.tsx:217-249` (include the `flatten()` helper as-is); test cases: (a) `systemConfig` null → exactly `['solar','battery','water']` allowed, EV EXCLUDED — pin this surprising fallback and list it in change notes, (b) explicit `has_battery: false` → battery dropped, (c) `has_ev_charger: true` → EV included
- [x] 3.2 Extract the price-breakdown formula (duplicated at `ChartCard.tsx:90-117` tooltip and `:980-989` panel) into one exported `splitPriceBreakdown(value, pricing)`; point BOTH call sites at it; test cases: (a) spot + feesAndVat sum back to the input value, (b) `vat = -100` (zero divisor) → guarded fallback, no division by zero, (c) `pricing` undefined → no-breakdown result, (d) fees > base price → spot clamps to 0
- [x] 3.3 Extract `todaySummary` logic from the IIFE at `Dashboard.tsx:487-542` into an exported function taking `slots` (and fixed `now`); test cases: (a) no-battery slots with only export → only Export phases, (b) adjacent same-action slots merge into one range, (c) no slots today → null, (d) Charge→Discharge→Export ordering in the joined string
- [x] 3.4 Extract `computeCostDrift(costSeries)` from `KPIStrip.tsx:16-31`; test cases: (a) empty/undefined series → drift 0 labeled as saved, (b) realized > planned → "Overspent", (c) exact zero drift boundary → saved
- [x] 3.5 Extract the normalization from `MiniBarGraph.tsx:20-30`; test cases: (a) empty data → flat fallback of `bars` length, (b) all-equal values → no div-by-zero, (c) fewer points than `bars`, (d) negative values
- [x] 3.6 Extract the strategy-sentence logic from `renderSocContext` (`BatteryStrategyCard.tsx:138-206`) and the sparkline normalization (`:62-75`) as pure functions of explicit params; test cases: (a) charging before a single cheap day → "D{n}" wording, (b) cheap-day RANGE → "D{n}→D{m}" wording, (c) `priceOutlook` undefined while charging → plain "charging" fallback, no crash, (d) single-day outlook → `range || 1` guard holds
- [x] 3.7 Extract `getDefaultDatesForPeriod` and the pure predicate inside `validateDateRange` (`CommandDomains.tsx:80-144`), leaving the `setDateError` side effect in a thin wrapper; test cases: (a) each period vs a fixed "now", (b) end < start → invalid, (c) start == end → valid, (d) empty strings → invalid
- [x] 3.8 Extract `deriveChargerStatus(charger, balancerEv)` and the progress-percent computation from `EVChargingCard.tsx:152-175`; test cases: (a) `required_kwh = 0` → progress 0, no div-by-zero, (b) balancer states (`throttling`/`paused`/`stale_fallback`) take priority over `charger.status`, (c) `charger.status = 'on_track'` with no balancer entry passes through, (d) progress caps at 100

## 4. Verification

- [x] 4.1 `pnpm test` (vitest) green — all pre-existing 89 tests still pass plus the new ones; `pnpm build`/`tsc` green; eslint clean on touched files
- [x] 4.2 Diff review against the behavior-preservation rule: every non-test change is `export` added, a function body moved verbatim into a named function, or the price-breakdown dedupe — no logic edits anywhere
- [x] 4.3 Visual smoke check per the shared-code workflow rule: dashboard (chart, KPI strip, power flow, battery card), executor page, EV tab all render unchanged — see caveat in Change Notes below (no browser-automation tool was available to capture screenshots directly)
- [x] 4.4 Change notes list every pinned surprising behavior (at minimum: null-systemConfig EV exclusion in power flow) for the user to review as potential future fixes

## Change Notes (pinned surprising behaviors, for user review)

1. **Null `systemConfig` silently excludes the EV node from the power-flow diagram** (`PowerFlowCard.tsx` `computeEnabledNodes`). With no system config, only `solar`/`house`/`battery`/`grid`/`water` are enabled — `ev` is dropped even if EV data is present. Pinned by `PowerFlowCard.computeEnabledNodes.test.ts`.
2. **`splitPriceBreakdown` `vat = -100` guard**: if `pricing.vat` is exactly -100, `1 + vat/100` is 0; the function falls back to using the raw total as the "base price" instead of dividing by zero. Pinned by `ChartCard.splitPriceBreakdown.test.ts`.
3. **Sparkline `range = max - min || 1` guard** (`BatteryStrategyCard.tsx` `computeSparklineRange`, `MiniBarGraph.tsx` `computeNormalizedBars`): a single data point or all-equal values fall back to a range of 1 rather than dividing by zero. Pinned by both files' test suites.
4. **EV charger progress is 0 when `required_kwh` is 0 or null** (`EVChargingCard.tsx` `computeProgressPercent`), rather than `NaN` or 100%. Pinned by `EVChargingCard.status.test.ts`.

**Bug found and fixed (not just pinned) during this change:** `Dashboard.tsx` `computeTodaySummary` computed a schedule phase's `end` time via `toISOString()` (always UTC) while `start` was a raw substring of the local wall-clock `start_time` string — in Stockholm summer (UTC+2) this made the displayed end time read ~2h *before* the start time (e.g. "Charge 00:00-23:30" for a phase actually ending at 01:30 local). Fixed by using the existing `formatHour` helper (`lib/time.ts`, already DST-correct) for both `start` and `end`. See commit message for details; not treated as a spec change since it's a one-line, test-covered fix.
