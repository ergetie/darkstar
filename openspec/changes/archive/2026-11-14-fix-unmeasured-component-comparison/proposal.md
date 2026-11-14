## Why

In the cmon89 diagnostics bundle, the EV sensor `sensor.myenergi_vadstena_924a_power_charging_2` gave no usable history for 105 slots (2026-11-09 10:00 to 2026-11-10 12:15 local). The recorder fell back to the live power snapshot. `power_results.get(...) or 0.0` turned the missing snapshot into a fake 0 kWh, tagged `ev=snapshot` and `load=mixed`. The grid-only comparison drops `snapshot` and `mixed` components as `estimated_component`, so all 105 slots were excluded and the Grid & Financial chart line ended mid-day.

Commit 7765cda4 fixed this pattern for water only (method `unknown`, `allow_unmeasured_water`, hatched spans and notes). It was not generalised to EV or to other device components. A missing device sensor must never become a fake measured zero, and must not make a slot with measured grid flows disappear from the comparison.

## What Changes

- Recorder: a device sensor with no integrated history and no live snapshot is recorded as unknown (EV per charger, water, any other device component), not as a fake 0 kWh or a fake `snapshot`. Numeric columns keep 0 as placeholder; no schema change. A snapshot that really exists stays `snapshot`.
- Grid-only comparison: a slot with measured import and export (and battery flows when a battery is present) is kept. Unknown, snapshot or mixed device or load components make it partial with a reason instead of excluded. Slots stay excluded only when import, export or battery (when present) is not measured, or for the existing integrity reasons.
- API and UI: partial slots keep the chart line unbroken. The Grid & Financial card shows a note such as "EV not measured for 26 h (Nov 9 10:00-Nov 10 12:15)" using the existing exclusion-notes and hatched-band machinery.
- Load forecast training (and every other ML consumer of slot load) drops slots whose load contains an unknown device component, so models never learn from fake data.
- Other consumers of device kWh (energy API, monitors, schedule router, benchmark, backfill, validation, comparison_history) are reviewed; the ones needing changes are specified in design.md.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `energy-recording`: unknown provenance for every unavailable device sensor; no fake zero.
- `grid-only-comparison`: partial-slot rule, partial reasons and coverage fields.
- `grid-financial-wear-display`: partial-slot note and span styling on the cost chart.
- `load-training-data-quality`: training drops slots with unknown device components.

## Impact

- Backend: `backend/recorder.py`, `backend/grid_only_comparison.py`, `backend/validation.py`, `backend/learning/backfill.py`, `backend/learning/store.py`, `backend/battery_benchmark.py`, `backend/monitors.py`, `backend/api/routers/schedule.py`, `backend/api/routers/energy.py`, `ml/train.py`, `ml/load_clean.py`.
- Frontend: `frontend/src/lib/api.ts`, `frontend/src/lib/costExclusion.ts`, `frontend/src/components/CostSeriesChart.tsx`, design system doc line.
- Tests across backend, ml and frontend.
- No DB schema change, no config change, no new dependency.
- Non-goals: unrelated backlog work, re-writing historical rows, new sensors.
