## Context

Prod planner run (11.9 s, 2026-09-28 00:04) mapped from log timestamps and measured piecewise on prod hardware:

| Part | Now | Batched / cached | Evidence |
|---|---|---|---|
| `store_forecasts`, 672 rows | 4.5-4.9 s | ~40 ms | DB copy, 3 runs, identical rows |
| `SunCalculator.is_sun_up` x2016 | 0.71 s | 45 ms | identical booleans |
| Hybrid PV loop (3 quantiles x 672, `iterrows`) | 0.60 s | est. <0.05 s | row-shape replica |
| `store_plan`, 100 rows | ~470 ms | 13 ms | DB copy |

Remaining time (Open-Meteo network ~1.1 s, HA load profile + DB forecast read ~0.7-1.5 s, solver ~0.8 s) is out of scope.

`store_forecasts` and `store_plan` already use one session and one commit; the cost is compiling and awaiting one `INSERT ... ON CONFLICT` per row through aiosqlite.

## Goals / Non-Goals

**Goals:**
- Identical persisted rows and identical forecast values.
- Per-run cost of these four paths reduced to tens of milliseconds.

**Non-Goals:**
- Batching rarely-run or small writers (`store_slot_prices`, `store_slot_observations`, `store_openmeteo_pv_baselines`).
- Parallelising the per-array Open-Meteo fetches, HA reads, or solver work.
- Schema or index changes.

## Decisions

1. **executemany with a single upsert statement.** Build one `sqlite_insert(Model).on_conflict_do_update(...)` referencing `excluded.*` and pass the list of row dicts to `session.execute(stmt, rows)`. SQLAlchemy 2.0 runs it as executemany in one transaction. Verified identical on prod copy. Alternative: multi-VALUES single statement — rejected; hits SQLite variable limits at 672 x 13 columns and needs chunking.
2. **Row normalisation stays in Python.** Timestamp conversion, `None` skipping, float coercion and the `duration_h` scaling in `store_plan` are unchanged and produce the row dicts; only execution is batched. Rows with no `slot_start` are still skipped; the plan's missing-end warning is still logged per slot.
3. **Duplicate keys within one batch.** Per-row execution let a later duplicate overwrite an earlier one. executemany applies rows in order within the same statement, preserving last-wins. Covered by a test.
4. **Per-date sun-time cache on the instance.** `get_sun_times` is keyed by the calendar date of the (localised) input; cache `dict[date, tuple | None]` on the `SunCalculator` instance so a failed calculation (`None`) is cached too. The cache is bounded by instance lifetime (one per inference run). Alternative: `functools.lru_cache` on a method — rejected (holds `self`, less explicit).
5. **Vectorised hybrid PV.** Compute `max_residual = baseline * bound_fraction`, clip residual to `[-max_residual, max_residual]`, multiply by `personalization_weight`, add baseline, then zero where sun is down (per-slot booleans computed once and shared across quantiles) or radiation `< 1.0`, floor at 0, cap at `physical_ceiling_kwh` when > 0, then the existing rolling smoothing. `_pv_tuning_config` read once. NaN radiation keeps current semantics (no clamp, since `NaN < 1.0` is False). NaN residual/baseline also keep the per-slot semantics: the bound, floor and ceiling use element-wise builtin `min`/`max` (`np.where(b < a, b, a)`) rather than `np.minimum`/`np.maximum`, which would propagate NaN; so a NaN residual bounds to `-max_residual` and any NaN value floors to 0.0.

## Risks / Trade-offs

- [executemany semantics differ from per-row for `func.coalesce(excluded.x, Model.x)`] → Verified identical on prod copy; test asserts NULL `openmeteo_pv_forecast_kwh` keeps the stored value.
- [Vectorised float order differs from scalar loop] → Operations are the same element-wise; test compares with `==` on a fixture and against the previous implementation retained in the test as a reference.
- [Sun cache returns stale data across DST boundaries] → Keyed by local calendar date, same input astral receives today.

## Migration Plan

Code-only; ships with the next release. Rollback = revert the commit.
