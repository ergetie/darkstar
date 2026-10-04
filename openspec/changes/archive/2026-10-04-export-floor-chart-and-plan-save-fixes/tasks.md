## 1. Export Prevention Floor setting

- [x] 1.1 Add a test that a Settings save of the export floor ends up in `export.export_floor_soc_percent` and reaches `KeplerConfig.export_floor_soc_percent` through the adapter (and that the legacy key is not written)
- [x] 1.2 Repoint the field in `frontend/src/pages/settings/types.ts` to `export.export_floor_soc_percent` (`path: ['export', 'export_floor_soc_percent']`)
- [x] 1.3 Update the keys in `frontend/src/pages/settings/search/guides.ts` (both entries) and `aliases.ts`
- [x] 1.4 Verify in the running app that the field shows the effective value (20 by default) and that a saved change lands in `config.yaml` under `export` (covered by tests only, not verified in a browser)

## 2. Plan save failure visibility

- [x] 2.1 Add `planner/plan_store_status.py` holding the last plan save failure (summary and time) with set, clear and get functions
- [x] 2.2 Add `PlannerErrorCode.PLAN_STORE_FAILED` to `planner/errors.py` with a user message and fix hint, and include it in `is_warning_only`
- [x] 2.3 In `planner/pipeline.py`, on `store_plan` failure log with `logger.exception` and record the failure; clear the recorded failure after a successful save; keep writing `schedule.json` and keep the run successful
- [x] 2.4 In `backend/health.py` `check_planner`, append a warning `HealthIssue` with `code="PLAN_STORE_FAILED"` while a failure is recorded, independent of the planner service's last error state
- [x] 2.5 Check that the frontend health banner (`SystemAlert`) renders an issue with this code from its message and guidance, with no code-specific handling needed
- [x] 2.6 Add tests: failure recorded and health warning returned; run still succeeds and `consecutive_failures` stays 0; next successful save clears the warning; `PLAN_STORE_FAILED` is warning-only

## 3. Chart selection persistence

- [x] 3.1 Memoize `slotsOverride` in `frontend/src/pages/Dashboard.tsx` so a `live_metrics` re-render keeps the same array
- [x] 3.2 In `frontend/src/components/ChartCard.tsx`, remove the unconditional `setSelectedIndex(null)` from the data effect; clear the selection only when the index is outside the new data length
- [x] 3.3 Add a frontend test: with a slot selected, a parent re-render with equal schedule data keeps the selection; shorter data clears it
- [x] 3.4 Verify in a browser (mobile viewport) that a tapped slot stays selected through live updates and clears on a tap outside the card (covered by tests only, not verified in a browser)
- [x] 3.5 Verify in a browser (desktop) that the hover tooltip is not reset by live updates; if it still resets on real data refreshes, add it to `docs/BACKLOG.md` after asking (verified by the user on desktop)
- [x] 3.6 Add the current calendar day to the `slotsOverride` memo dependencies (extracted as `useChartSlots`) so a dashboard left open past midnight re-splits today/tomorrow, with a fake-timer test: same array within a day, recomputed after midnight

## 4. Cycle cost advice threshold

- [x] 4.1 In `backend/api/routers/analyst.py`, add `HIGH_CYCLE_COST_SEK_KWH = 0.5` next to the price advice thresholds and use it in the battery wear check
- [x] 4.2 Add or update a test: no warning at the default 0.2, no warning at 0.5, warning above 0.5
- [x] 4.3 Check existing tests and docs for references to the old 0.15 cycle cost threshold

## 5. Chart hour labels on narrow widths

- [x] 5.1 Add `frontend/src/lib/chartTicks.ts` with `hourLabelStep(widthPx, visibleHours)` (strides 1, 3, 6, 12; 16 px minimum per label) and `hourOfLabel`
- [x] 5.2 Use them in the `ChartCard` x tick callback with the scale width and the visible full-hour count; leave `dotGridPlugin` hourly dots unchanged
- [x] 5.3 Add unit tests for the label thinning: every hour at ~1200 px, every third hour at ~350 px, width-driven (narrow desktop window), minimum spacing never violated
- [ ] 5.4 Check the chart in a browser at ~350 px and ~1200 px widths (not done: no browser available to the implementing agent)

## 6. Verification

- [x] 6.1 Run `./scripts/lint.sh` and the affected backend and frontend tests; all pass
- [x] 6.2 Update `docs/BACKLOG.md` to remove the four handled items (ask first, `docs/` is ask-first)
