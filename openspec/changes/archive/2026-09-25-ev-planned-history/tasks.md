## 1. Schema

- [x] 1.1 Add `planned_ev_charging_kwh` (nullable Float) to `SlotPlan` in `backend/learning/models.py`
- [x] 1.2 Add an Alembic migration (down_revision `bb3329253f22`, or the current head at implementation time) with batch add_column and a downgrade drop
- [x] 1.3 Migration test: upgrade on a DB with existing rows leaves them NULL; downgrade removes the column

## 2. Persistence

- [x] 2.1 `store_plan`: write `ev_charging_kw × slot_hours` (same duration convention as water), and include it in the upsert set
- [x] 2.2 Include the column in `get_plans_range` and any other `slot_plans` readers feeding history
- [x] 2.3 Test: a stored plan round-trips planned EV kWh

## 3. History API

- [x] 3.1 `backend/api/routers/schedule.py`: add EV to `planned_map` (kWh → kW) and backfill `slot["ev_charging_kw"]` for historical slots when not NULL
- [x] 3.2 Test: after a replan, a past slot keeps its planned `ev_charging_kw`; a NULL row yields no fabricated value
- [x] 3.3 Fix the "preserves past slots" docstring in `planner/output/schedule.py`

## 4. Verification

- [x] 4.1 Run `./scripts/lint.sh` and the full test suite
- [x] 4.2 Run `alembic upgrade head` against a copy of the prod DB and confirm the schema
