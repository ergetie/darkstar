## Context

Five independent fixes, each small. The only one with a real design choice is how a failed plan save becomes visible.

- **Plan save**: `planner/pipeline.py` wraps `LearningStore.store_plan` in `try/except Exception` and only logs a warning. `schedule.json` is already written, the run exits 0, `PlannerService._execute` calls `_on_success()` (which clears `last_error_code`) and emits "schedule updated". The only thing that notices a stale `slot_plans` is the `plan_freshness` monitor, after 3 h. The existing `is_warning_only` codes in `planner/errors.py` are only logged by `planner/preflight.py`; nothing surfaces them to the UI.
- **Export floor**: the planner reads `export.export_floor_soc_percent` (`planner/solver/adapter.py:583`). The Settings field still targets `executor.override.low_soc_export_floor`. `_migrate_export_floor` (`backend/config_migration.py:843`) copies the old value only when the new key is absent, then deletes the old key, so a UI save is both unread by the planner and removed on the next startup.
- **Chart selection**: `Dashboard.tsx:520-527` builds `slotsOverride` with `.filter()` and spread on every render. `Dashboard` re-renders on each `live_metrics` socket event (`setLivePower`). `ChartCard`'s data effect depends on `slotsOverride`, so it re-runs and calls `setSelectedIndex(null)` (`ChartCard.tsx:1486`) and `chart.update()`.
- **Cycle cost**: `backend/api/routers/analyst.py:186` warns above 0.15 SEK/kWh while `config.default.yaml` ships 0.2.
- **Chart hour labels**: the `ChartCard` x tick callback labels every full hour with `autoSkip: false`; over 48 h in a ~350 px card the labels overlap.

## Goals / Non-Goals

**Goals:**
- A saved Export Prevention Floor changes the planner input, and the field shows the value actually in use.
- A failed plan save is reported to the user on the next health poll, not after 3 h.
- A mobile slot selection stays until the user dismisses it; live updates do not clear it.
- Default installs get no cycle cost advice.
- Chart hour labels never overlap; narrow charts label every third hour and keep hourly marks.

**Non-Goals:**
- Finding the cause of the Discord `INVARIANT_PLAN_FRESHNESS` report (needs the reporter's logs).
- Making a failed plan save fail the planner run or block `schedule.json`.
- Retrying the save, or changing `plan_freshness` monitor thresholds or wording.
- Changing the migration's handling of an old key already present in user configs.

## Decisions

### D1: Plan save failure is a separate status, surfaced as a health warning

A new module `planner/plan_store_status.py` holds the last plan save outcome (error summary and time, or none). The pipeline sets it in the `except` branch (and logs at `ERROR` with traceback via `logger.exception`) and clears it after a successful save. `HealthChecker.check_planner` appends a `HealthIssue(category="planner", severity="warning", code="PLAN_STORE_FAILED")` while it is set. A new `PlannerErrorCode.PLAN_STORE_FAILED` supplies the user message and fix hint, and is marked warning-only so it never counts as a failed run or changes retry cadence.

Alternatives considered:
- *Raise from the pipeline so the run fails*: rejected. The executor only needs `schedule.json`; a database problem would stop all planning and trigger retries that hit the same fault.
- *Set `PlannerService._last_error_code` after a successful run*: rejected. `_on_success` clears it, `check_planner` treats a non-empty code as a failed run, and the pipeline has no handle to the service (only an exit code returns through `bin/run_planner.py`).
- *Rely on the `plan_freshness` monitor*: rejected as the only signal. It fires after 3 h and its message points at developer artifacts.

The status lives in process memory. It is cleared on the next successful save and on restart, which is acceptable: the next planner run re-establishes it if the fault persists.

### D2: Export floor field repointed, no new migration

Change the field `key` and `path` in `frontend/src/pages/settings/types.ts` to `export.export_floor_soc_percent` / `['export', 'export_floor_soc_percent']`, and the keys in `guides.ts` and `aliases.ts`. The shipped default (`config.default.yaml`) already carries the new key, and the migration has already moved any old value, so the field has a value to show on every install. `_migrate_export_floor` stays as is for configs that still carry the old key.

Alternative considered: make the backend save accept the old key and translate it. Rejected: it keeps a dead key alive in the UI contract for no benefit.

### D3: Stabilise `slotsOverride` and stop clearing selection on refresh

Two changes, both needed:
- Memoize `slotsOverride` in `Dashboard` (`useMemo` on `localSchedule`, `historySlots`) so a live metric render keeps the same array and the chart data effect does not re-run.
- Remove the unconditional `setSelectedIndex(null)` from the data effect. Instead keep the selection while it is still valid for the new data (index within the new `labels` length); the existing click-away handler and re-tap toggle remain the way to dismiss it. When the data really changes (new plan, day change), a still-valid index stays selected and the panel re-reads the new values.

The memo also depends on the current calendar day (`ymdLocal(new Date())`, computed each render). The body filters with `isToday`/`isTomorrow`, so without it a dashboard left open past midnight would keep the previous day split until the schedule or history changed. Because the day string is recomputed on every render, the first `live_metrics` render after midnight picks up the rollover; within a day it is stable and the array identity is kept. The memo is extracted as `useChartSlots` so it can be tested with fake timers.

Alternative considered: only memoize. Rejected: a real data refresh (new schedule every 30 min, day switch) would still drop the selection, and the effect has other triggers (`overlays`, `pricingConfig`).

Desktop: the same effect re-run calls `chart.update()`, which can reset the Chart.js hover tooltip. After D3 the re-run only happens on real data changes. The task list includes verifying this in a browser; if the tooltip still resets on a real refresh, that is out of scope for this change and noted back in the backlog.

### D4: Cycle cost threshold 0.5

Replace the literal 0.15 with a named module constant (`HIGH_CYCLE_COST_SEK_KWH = 0.5`) next to the existing price advice thresholds, and use it in the message check. No spec text exists for this advice, so no delta spec.

### D5: Thin x-axis hour labels by available width

The `ChartCard` x axis is a category scale with `autoSkip: false`; its tick callback returns `HH` for every full-hour slot. At 48 h in a ~350 px card that is ~6 px per label and the text overlaps. The tick callback now computes a label stride from the scale's own width and the number of full-hour ticks in the visible range: `hourLabelStep` (in `frontend/src/lib/chartTicks.ts`) picks the smallest of 1, 3, 6, 12 hours that gives each label at least 16 px ("00" in 10 px monospace is ~12 px, plus a 4 px gap). Only hours divisible by the stride get text, so labels stay aligned to 00, 03, 06, ... The full-hour count is cached per tick array so the callback stays O(1) per tick. Chart.js sets the scale width before generating tick labels, and re-runs the callback on resize and zoom, so narrow desktop windows and zoomed-in views are handled the same way. At ~1200 px the stride stays 1, so wide layouts look unchanged. The hourly marks come from `dotGridPlugin`, which already draws a dot column every hour when zoomed out; it is unchanged. Fonts and colors are unchanged.

Alternatives considered:
- *Switch on `isMobile`*: rejected. A narrow desktop window has the same overlap, and the flag says nothing about the actual width.
- *Chart.js `autoSkip`*: rejected. It skips by tick count, not by hour, so labels land on arbitrary hours (01, 05, ...) and the stride shifts while zooming.
- *Rotate labels*: rejected. Takes vertical space from a fixed-height card and is harder to read.
- *Enable Chart.js x grid lines for hourly marks*: not needed; the dot grid already gives the hourly marks, and adding lines would change the look.

## Risks / Trade-offs

- [The health warning may be hit by a one-off lock] → It clears on the next successful save (planner runs every 30 min), so a transient fault disappears on its own.
- [`PLAN_STORE_FAILED` shown by banner code that does not know the code] → The banner renders message and guidance from the issue; task 2.5 checks that the frontend handles an unknown planner code.
- [Keeping a selection across a data refresh can show stale values] → The panel memo recomputes from the new `liveChartData`, so values update in place.
- [Users with the old key still saved] → Unchanged: migration runs at startup as before; the field now reads the new key.

## Migration Plan

None. No schema, config key or data change. Rollback is a plain revert.

## Open Questions

None blocking. If the Cmon89 logs show a planner failure caused by settings changed during an update, that is a separate change.
