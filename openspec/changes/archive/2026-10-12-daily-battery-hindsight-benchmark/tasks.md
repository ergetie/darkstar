## 1. Benchmark core

- [x] 1.1 Add a benchmark option to Kepler (`planner/solver/`): zero policy penalties, fixed-zero curtailment and slacks, terminal stored-energy equality, binary no simultaneous charge/discharge, no discharge in EV slots, floor = min(min SoC, start, end). Default off.
- [x] 1.2 Add a pure module (`backend/battery_benchmark.py`) that builds a day from `slot_observations` rows: eligibility (design §3), meter-derived flows, start/end stored energy, capacity check (§4), cost of actual / ideal / no-battery (§1), result record.
- [x] 1.3 Tests: missed/score arithmetic, gross vs net slot pricing, matched end stock, eligibility reasons (missing slot, snapshot, legacy row, today/future, out-of-range stock), DST 92/100 slots, capacity mismatch, small known optimum, live Kepler output unchanged with option off.

## 2. Service and storage

- [x] 2.1 `BenchmarkService` in `backend/services/`: 00:10 local + once after start, last 14 days not stored, outdated or failed (failed days are retried every run), oldest first, one solve at a time via `asyncio.to_thread`; started/stopped in `backend/main.py` lifespan.
- [x] 2.2 Store/read results in `system_state` key `battery_benchmark:<date>` through `LearningStore`, with a version constant.
- [x] 2.3 Tests: restart idempotence, version bump recompute, failed solve stored and retried, no schedule/HA/observation writes.

## 3. API and UI

- [x] 3.1 `GET /api/energy/battery-benchmark` in `backend/api/routers/energy.py` with date validation and totals (design §6).
- [x] 3.2 Typed client in `frontend/src/lib/api.ts`; "DS vs hindsight" row with ⓘ popover under "DS vs grid-only" in `CommandDomains.tsx`, following `docs/design-system/AI_GUIDELINES.md`; hidden for Today; empty/excluded states.
- [x] 3.3 `CostSeriesChart.tsx`: cumulative "Hindsight" line (gold dashed token) below DS with shaded area, day-end points = DS cumulative − cumulative missed, gaps on excluded days, legend entry, not in hourly views; extend `computeCostChartGeometry` and its tests.
- [x] 3.4 Tests: range validation, totals over scored days only, null score, no solve on read, chart geometry; visual check of every page using `CostSeriesChart` and the shared `api.ts`.

## 4. Acceptance

- [x] 4.1 Run the service logic read-only on a fresh prod DB copy for all eligible days; compare with the investigation figures for overlapping days (expect within ~1 SEK/day of the 15-min method c results).
- [x] 4.2 `./scripts/lint.sh` and focused backend/frontend tests pass.
