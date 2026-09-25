## Why

The Schedule Overview chart shows actual EV charging for past slots but not the planned EV charging. Every replan writes only current and future slots to `schedule.json`, and the durable per-slot plan table `slot_plans` has no EV column. So planned EV for past slots is lost as soon as the next plan runs. Battery, water, and SoC survive because the history endpoint backfills them from `slot_plans`.

## What Changes

- Add a `planned_ev_charging_kwh` column to `slot_plans`, via an Alembic migration that runs automatically on startup for all installs (Docker entrypoint and add-on). The column is nullable, and existing rows stay NULL, meaning "unknown", not zero.
- `store_plan` persists the aggregate planned EV energy per slot. Past rows keep the value from their execution time, because replans only upsert current and future slots.
- The schedule history endpoint backfills `ev_charging_kw` for historical slots from `slot_plans`, like battery and water.
- Fix the misleading "preserves past slots" docstring in `planner/output/schedule.py`.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `chart-planned-actual-display`: planned values sourced from `slot_plans` SHALL include EV charging.

## Impact

- `backend/learning/models.py` (`SlotPlan`), a new file in `alembic/versions/` (down_revision `bb3329253f22`)
- `backend/learning/store.py` (`store_plan`, and `get_plans_range` if it feeds history)
- `backend/api/routers/schedule.py` (`planned_map` + historical backfill)
- `planner/output/schedule.py` (docstring only)
- **DB schema change, additive:** the migration downgrade drops the column.
- The frontend is unchanged, since `ChartCard` already reads `ev_charging_kw`.
