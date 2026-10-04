## Why

Four small, user-reported defects are open in the backlog, and the dashboard chart's hour labels overlap on narrow screens. Each is a case where the UI or the planner quietly does something other than what the user sees or expects: a saved Settings value is ignored, a chart selection vanishes, a plan-save failure is hidden behind a successful run, and every default install gets a bogus battery warning. They are cheap to fix together and none needs a design session.

## What Changes

- **Export Prevention Floor setting**: the Settings field writes `export.export_floor_soc_percent`, the key the planner reads, instead of the removed `executor.override.low_soc_export_floor`. Today a UI save has no effect on the planner and the old key is discarded at the next startup migration. The field's search entries (`guides.ts`, `aliases.ts`) move to the new key.
- **Plan save failure is visible**: when storing the plan to `slot_plans` fails, the failure is logged as an error and surfaced as a planner health warning (`PLAN_STORE_FAILED`) until a later save succeeds. `schedule.json` is still written and the run still counts as successful, so the executor keeps working. Not confirmed as the cause of the Discord `INVARIANT_PLAN_FRESHNESS` report; this closes the silent-failure gap either way.
- **Dashboard chart selection persists**: on mobile, the tapped slot stays selected until the user taps outside the chart card or taps the slot again. Live metric updates no longer clear it. The cause is that `Dashboard` builds `slotsOverride` as a new array on every render (and re-renders on each `live_metrics` event), which re-runs the chart data effect, and that effect resets the selection. The desktop hover tooltip is checked for the same re-run and fixed if affected.
- **Cycle cost advice threshold**: the "High battery cycle cost" analyst warning fires above 0.5 SEK/kWh instead of 0.15, so the shipped default of 0.2 no longer triggers it.
- **Dashboard chart day split at midnight**: the memoized `slotsOverride` also depends on the current calendar day, so a dashboard left open past midnight re-splits today and tomorrow on the next render.
- **Readable chart hour labels on narrow widths**: when a label per hour does not fit the chart width (mobile, narrow desktop windows), the x axis shows text only every third hour (00, 03, 06, ...) while the hourly dot marks stay. Wide layouts keep a label per hour. The decision uses the chart's actual width, not the mobile flag.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `export-floor-constraint`: adds the requirement that the Settings field for the export floor reads and writes the key the planner consumes, so a saved value changes the planner input.
- `planner-diagnostics`: adds the requirement that a failed plan save is reported as a warning-level planner health issue without failing the run.
- `dashboard-layout`: adds the requirement that the mobile slot selection survives live data refreshes, and the requirement that chart hour labels are thinned to fit the available width.

The cycle cost threshold has no existing spec text, so it needs no delta spec.

## Impact

- `frontend/src/pages/settings/types.ts`, `frontend/src/pages/settings/search/guides.ts`, `frontend/src/pages/settings/search/aliases.ts`
- `planner/pipeline.py`, `planner/errors.py`, `backend/health.py` (plus the frontend health banner if it needs the new code)
- `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/ChartCard.tsx`, new `frontend/src/lib/chartTicks.ts`
- `backend/api/routers/analyst.py`
- No database schema change, no new dependencies, no config key added or removed.
