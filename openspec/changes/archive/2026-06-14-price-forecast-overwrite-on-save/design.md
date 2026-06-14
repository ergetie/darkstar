## Context

`generate_price_forecasts()` (in `ml/price_forecast.py`) calls `_persist_forecasts()`, which loops the batch and does `session.add(PriceForecast(...))` for every row — a plain append with no dedup. The `price_forecasts` table has no UNIQUE constraint (only two non-unique indexes), so repeated runs accumulate duplicate rows. Generation runs daily at 06:00 and again after each ML training cycle, so duplicates pile up quickly and are only pruned by `cleanup_price_forecast_duplicates()` at startup.

Two distinct keys are already in play and must not be conflated:
- The **startup cleanup** keys on `(slot_start, days_ahead)` — it keeps the latest `issue_timestamp` per pair.
- The **read-side dedup** (`get_price_forecasts_from_db`, `get_d1_price_forecast_fallback`) keys on `slot_start` — it keeps the latest `issue_timestamp` per slot.

The same physical slot legitimately gets multiple rows over its life — one per `days_ahead` as the horizon counts down D+7→D+1 on successive days. Those are kept by the cleanup and collapsed by the read-side dedup. The only *unwanted* rows are **same-run/same-horizon re-issues**: multiple `issue_timestamp`s for an identical `(slot_start, days_ahead)`.

This is a single-writer system: only the scheduler/training pipeline writes `price_forecasts`.

## Goals / Non-Goals

**Goals:**
- Stop the write path from creating duplicate `(slot_start, days_ahead)` rows: a save overwrites the prior row for that pair.
- After any single generation run, at most one row exists per `(slot_start, days_ahead)` pair that run covered.
- Keep the change minimal and behavior-preserving for every existing reader.

**Non-Goals:**
- No DB schema change, no UNIQUE constraint, no Alembic migration.
- No data backfill / one-time migration to purge existing duplicates (the retained startup cleanup already handles legacy rows).
- Not removing or altering `cleanup_price_forecast_duplicates()` or its startup call — it stays as a backstop.
- No change to read-side dedup or to the daily-outlook aggregation logic (it self-corrects once duplicates stop accruing).

## Decisions

**Decision: Delete-then-insert keyed on `(slot_start, days_ahead)`, inside one transaction.**
In `_persist_forecasts()`, before inserting the batch: collect the distinct `(slot_start, days_ahead)` pairs present in the batch, bulk-delete any existing rows matching those pairs, then add the new rows, then commit. Delete + insert in a single transaction is atomic, so a crash mid-write cannot leave a slot with no forecast.

- *Why this key:* it matches the existing startup cleanup exactly. Within one run each `(slot_start, days_ahead)` is unique (a run assigns exactly one `days_ahead` per slot, derived from `now.date()`), so deleting the batch's pairs removes only prior same-horizon re-issues. Cross-day rows with a different `days_ahead` for the same slot are preserved (then read-deduped), exactly as today.
- *Why NOT key on `slot_start` alone:* it would delete legitimate other-horizon historical rows for that slot, destroying data the cleanup intends to keep.

**Decision: Application-level overwrite, not a DB upsert.**
SQLite `INSERT ... ON CONFLICT` requires a UNIQUE index to target, which would require adding a constraint (and deduping existing rows first to apply it). Per the agreed KISS scope, we avoid the schema change and enforce single-row-per-pair in the write path, with the startup cleanup as the safety net.
- *Alternative considered — ON CONFLICT upsert + UNIQUE constraint + one-time dedupe migration:* stronger (DB-enforced) but larger surface (migration + data purge). Rejected for this change; can be revisited later if a hard guarantee is wanted.
- *Alternative considered — `session.merge()`:* merges on primary key (`id`), not the natural `(slot_start, days_ahead)` key, so it does not fit. Rejected.

**Decision: Implement the bulk delete via the natural-key pairs.**
Build the set of `(slot_start, days_ahead)` pairs and delete matching rows in one statement (e.g. SQLAlchemy `tuple_(slot_start, days_ahead).in_(pairs)`, supported by SQLite row-value IN). If row-value IN proves awkward, the equivalent fallback is per-pair deletes within the same transaction — same result, slightly more statements.

## Risks / Trade-offs

- **[No DB-level guarantee]** → A future second writer, or a code path that bypasses `_persist_forecasts()`, could still create duplicates. Mitigation: the retained startup cleanup sweeps them; single-writer assumption documented in the spec.
- **[Bulk delete uses row-value tuple IN]** → Older SQLite may not support it. Mitigation: Python 3.12's bundled SQLite supports it; fallback to per-pair deletes if a test shows otherwise.
- **[Atomicity of delete+insert]** → Must occur in one transaction so a failure cannot drop a slot's forecast without re-inserting it. Mitigation: single transaction with rollback on exception (keep the existing try/except, add rollback).
- **[Behavior change for daily outlook]** → Averages stop double-counting duplicates. This is the intended correctness improvement, not a regression; no reader depends on duplicate weighting.

## Migration Plan

No migration. Deploy is code-only. Existing duplicates remain harmless and continue to be handled by the read-side dedup and the next startup cleanup. Rollback = revert the `_persist_forecasts()` change; the table shape is unchanged so no rollback steps are needed.
