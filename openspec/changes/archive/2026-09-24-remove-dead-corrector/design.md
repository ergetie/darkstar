## Context

The corrector ML pipeline was replaced by recency weighting in `fad904e3`. Three leftovers remain:
1. `ModelTrainingCard` treats any `*.lgb` whose name contains `error` as the corrector. Stale `load_error.lgb` and `pv_error.lgb` files make it show "Ready · 195d ago".
2. `forecast.py::_fetch_correction_history` sums `SlotForecast.*_correction_kwh`. The result goes out as `correction_history`, which nothing reads.
3. `CorrectionHistoryChart.tsx` is imported nowhere.

## Goals / Non-Goals

**Goals:** Remove all corrector surfaces from the API and UI.

**Non-Goals:**
- Deleting `*_error.lgb` files on user installs.
- Changing the `/learning/training-status` backend. It lists all `*.lgb` generically, which is correct.

## Decisions

- **Main Models tile**: keep it. Its `find` currently excludes `error` files. Instead, select only `*model*` files, matching the backend's main-model glob in `training_orchestrator.py:207`. That way leftover error files can't affect the card.
- **Card layout**: with the Corrector tile gone, the status grid has one cell. Make Main Models full width rather than leaving an empty column.
- **API field**: remove `correction_history` outright rather than returning `[]`. No consumer exists, so a deprecation window adds nothing.

- **DB migration**: add a new Alembic revision after `b7c9d1e2f3a4`, following that revision's style.
  - `upgrade()` checks with `sa.inspect(bind).get_columns("slot_forecasts")` and drops only the columns that exist. Fresh installs, where the baseline created them, and partially-migrated DBs both converge; a rerun does nothing.
  - The drop runs inside `op.batch_alter_table("slot_forecasts")`. SQLite then rebuilds the table (copy, drop, rename) in one transaction. `env.py` already sets `render_as_batch=True`, and indexes and the `(slot_start, forecast_version)` unique constraint are preserved.
  - `downgrade()` re-adds the three columns with the original types and `server_default`s (`0`, `0`, `'none'`), so older images work again after a rollback. The values are not restored.
  - Safety net: `docker-entrypoint.sh` already copies the DB to `/data/backups/` before `alembic upgrade head` and aborts startup if the migration fails.
- **ORM/store**: remove the three `Mapped` fields from `SlotForecast`, remove them from the `get_forecasts_range` select, and delete the "remain for backward compatibility" comment.

## Risks / Trade-offs

- [Table rebuild fails mid-way] → It runs in one SQLite transaction, so it rolls back; the entrypoint backup covers the rest.
- [User rolls back to an older image] → Run `alembic downgrade -1` first; the columns come back with default values.
- [An external consumer (HA or a script) reads `correction_history`] → Unlikely, since it has been all zeros for 6 months. Mention it in the commit message.
