## Context

- `planner/output/schedule.py:68-79`: `schedule.json` holds only current and future slots.
- `backend/learning/store.py:332-363`: `store_plan` upserts `slot_plans` on `slot_start` from the plan dataframe, and a replan only contains current and future slots.
- `backend/api/routers/schedule.py:267-293` builds `planned_map` from `slot_plans`, and `:392-409` backfills battery/SoC/export/water for historical slots. EV is missing from both.
- `planner/solver/adapter.py:665`: the plan row carries aggregate `ev_charging_kw` (sum over chargers).
- Precedent: `projected_soc_percent` was added the same way (migration `a0ce8c0ea3b5`, spec `projected-soc-persistence`).

## Goals / Non-Goals

**Goals:** planned EV bars persist for past slots across replans, goal clears, and restarts.

**Non-Goals:**
- Per-charger planned history.
- The keep-on "EV Standby" band and surplus-eligible kW for past slots.
- Backfilling rows from before the migration.

## Decisions

1. **Aggregate kWh column.** Store `planned_ev_charging_kwh = ev_charging_kw × slot_hours`, matching the `planned_*_kwh` convention. The API converts back to kW with the slot duration, as for water. Per-charger JSON was rejected as unneeded, since the chart plots the aggregate.
2. **Nullable column, NULL for old rows.** The history endpoint only sets `ev_charging_kw` from the DB when the value is not NULL. Old slots then show no planned bar rather than a false "0 planned".
3. **Upsert includes the new column.** A replan of the current slot updates it, which is consistent with the other planned columns.
4. **Migration.** Use `op.add_column("slot_plans", sa.Column("planned_ev_charging_kwh", sa.Float, nullable=True))` inside `batch_alter_table` for SQLite. Downgrade drops it. Startup runs `alembic upgrade head` for every install.

## Risks / Trade-offs

- [The slot duration is not 15 min] → Use the actual slot duration from the dataframe, the same way the water conversion does (verify during implementation that water uses a fixed 0.25; if so, reuse the same convention consistently).
- [The migration fails on a user's DB] → The change is additive and nullable, with no data rewrite. Test it against a copy of the prod DB schema.

## Migration Plan

Deploy → the entrypoint runs `alembic upgrade head` → new rows fill in. Rollback: `alembic downgrade -1` plus reverting the code.
