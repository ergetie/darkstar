# Design

## Context

See proposal.md for motivation. Verified against HEAD:

- `ml/price_features.py:284` calls `dst_safe_date_range(start=D 00:00, end=D+1 00:00, freq="15min")`. The helper (`utils/time_utils.py:16`) passes `**kwargs` to `pd.date_range`, whose default is an inclusive end, so each day has 97 slots (101 and 93 on DST days). `ml/price_forecast.py:165` sets `end_time = start_time + 1 day`, so the next day's 00:00 is stored under days_ahead=N and N+1.
- `get_d1_price_forecast_fallback` (`ml/price_forecast.py:~514`) reads `days_ahead=1, limit=96` ordered by `slot_start` descending. With 97 rows this drops tomorrow's 00:00 and keeps the day after's 00:00. `backend/core/prices.py:~345` merges the result before `TOMORROW_PUBLISH_HOUR`, so the schedule jumps 23:45 to 00:15.
- `days_ahead` is relative to the forecast issue date (`ml/price_forecast.py:161`). The daily issue runs at `daily_run_time` (default 06:00, range 1-7) and the post-publication run uses range 2-7 (`backend/services/scheduler_service.py`). Between 00:00 and the daily issue, tomorrow's slots exist only as `days_ahead=2` rows from yesterday's issue. The current `days_ahead=1` read returns nothing then (those rows are today and discarded as stale), so there is no fallback until 06:00 and the planner horizon then jumps a day.
- `fetch_forecast_spot_sync` (`planner/strategy/ev_deferral.py:146`) already picks the latest issue per slot by date window, ignoring `days_ahead`.
- `get_nordpool_data` -> `_process_nordpool_data` builds output dicts with a fixed key set (`backend/core/prices.py:~540`), so a fallback record's source horizon would be dropped unless carried explicitly.
- Other `dst_safe_date_range` callers: `ml/forward.py:429` passes `inclusive="left"`. `ml/context_features.py:104` and `:190` use the inclusive end but slice the result with `index < end_local` afterwards, so they have no bug. The helper stays unchanged.
- `backend/core/price_outlook.py` collects slots into a dict keyed by tz-aware slot start before grouping by date, so duplicate rows from old data collapse. The suspected 00:00 double-count is not real; no change there.
- `backend/battery_benchmark.py:benchmark_day` solves `KeplerBenchmark` mode. The strict constraints in `planner/solver/kepler.py` (~1153-1175) fix `soc[T]`, set curtailment, load shedding, SoC slacks and export-floor violation to zero, and forbid discharge in EV slots. The production hard limits still apply: grid import and export caps (~793-797), the inverter AC limit with PV routing (~855-872), `enable_export` (~881) and the export floor (~884-889). Recorded reality can exceed these, which makes the model infeasible, stored as failed with `solver_not_optimal`.
- `benchmark_service._is_done` already retries failed days on every run, and the main spec says so. A version bump is therefore not what re-runs failed days; it recomputes older scored days so every record in the window has the new field.
- `ml/bootstrap.py:ensure_active_models` runs from the FastAPI lifespan in `backend/main.py:63`. Both `scripts/docker-entrypoint.sh` and the HA add-on `darkstar/run.sh` start `uvicorn backend.main:app`, so it runs in both modes. Training backups live in `data/ml/models/backup/backup_*` (`ml/training_orchestrator.py:21`), and `_restore_latest_backup` copies `*.lgb` from them, so backups can resurrect a stale file.
- `auto_tune_enabled` is read nowhere in code, template or UI (grep outside docs, archives and debugging dumps).

## Goals / Non-Goals

**Goals:**
- One slot per local 15-minute slot in stored forecasts, and a continuous merged price series across midnight.
- Benchmark days stay scored when recorded reality exceeded configured limits, and the user can see that.
- No dead error-correction config or model files remain after startup.

**Non-Goals:**
- Changing `dst_safe_date_range` or the callers that already handle the end correctly.
- Migrating or deleting existing duplicate `price_forecasts` rows; the read path tolerates them.
- Changing live planning, price reserve logic (`price-reserve-forecast-accuracy`) or any control behaviour.
- Relaxing the battery's own physics (charge and discharge power, capacity, SoC bounds, efficiencies, ending stock).
- Curtailment or EV-slot discharge in the relaxed solve (see decision 3).

This reverses the non-goal "Deleting `*_error.lgb` files on user installs" of archived change `2026-09-24-remove-dead-corrector`. That change left the files because they were harmless; they still appear in the training status listing and could be restored from backups, so removing them is now preferred.

## Decisions

1. **Half-open range at the call site.** `build_price_features_batch` passes `inclusive="left"` to the helper. Alternative: change the helper default, rejected because it is shared and other callers depend on current behaviour. The persisted `(slot_start, days_ahead)` dedupe stays.

2. **Date-based, latest-issue D+1 read.** Add optional local-date bounds to `get_price_forecasts_from_db` (compare `slot_start` against the date prefix of the ISO string, which every stored value has) and make `days_ahead` optional in that selection. The fallback reads tomorrow's local date across all `days_ahead` values, keeps rows with a non-null `spot_p50`, and keeps one row per `slot_start` from the latest `issue_timestamp`, mirroring `fetch_forecast_spot_sync`. No row limit, and no dependency on `daily_run_time`. The stale filter requires `slot_date == tomorrow`. Each record gets `forecast_days_ahead` from its source row; `get_nordpool_data` copies that key (and keeps `price_source: "forecast"`) into the processed price entries, which become `input_data["price_data"]`. `price-reserve-forecast-accuracy` uses the key for horizon-matched accuracy. Alternatives: keep `days_ahead=1` with a date window (still empty before the daily issue, rejected); raise the limit to 101 (fragile, rejected).
   **Behaviour change:** the planner now sees tomorrow's forecast prices from 00:00, not from the daily issue. Between 00:00 and the issue they come from yesterday's issue and can be up to about a day old. The planner horizon no longer jumps by a full day at 06:00.

3. **Relaxed benchmark solve.** `KeplerBenchmark` gains an optional relaxation: per-slot caps (kWh) for grid import, grid export and inverter AC, and a per-slot flag that lifts the export-disabled and export-floor constraints. In the benchmark branch the solver uses `max(configured * hours, recorded)` for those caps. Recorded values per slot come from the row: `import_kwh` and `export_kwh` for the grid caps. The inverter cap is computed from the modelled flow the recorded battery flows imply, not from the meter balance: PV not charging the battery goes to AC (PV is routed to the battery first, the cheapest routing the model allows), then DC-coupled adds discharge and grid-charge (`charge - pv_to_battery`), AC-coupled adds charge and discharge, exactly as the solver's own constraint sums them. The recorded schedule is then a feasible point of the relaxed model by construction; a meter-balance estimate (load plus export minus import) could differ from the modelled flow and cut that point off. The export-disabled and export-floor constraints are lifted only in slots that recorded export while violating them (export disabled, or stock from the recorded flows below the floor), so slots that comply keep the normal constraints. `benchmark_day` runs the strict solve first; only when it is not optimal does it build the relaxation from the rows. If no recorded value exceeds any limit the retry is skipped, since the relaxed model would equal the strict one; the day then fails with the specific reason below. Otherwise it solves once and scores. The record gets `warnings += ["limits_relaxed"]` and `relaxed_limits`, a sorted list drawn from `grid_import`, `grid_export`, `inverter_ac`, `export_floor`, including only limits that were actually raised in at least one slot. Curtailment and EV-slot discharge stay forbidden: recorded flows balance without them, and allowing free curtailment would let hindsight dump PV and overstate its value. If a day is still infeasible, the specific reason points at a data inconsistency instead of hiding it.
   Alternatives: a single solve with relaxation always on (changes normal-day results, rejected); relaxing by a large constant (no record of what really happened, rejected).

4. **Failure reasons.** After a failed relaxed solve, or a failed strict solve where no limit was exceeded and no retry ran, the reason is `infeasible_with_recorded_limits`, or `solver_time_limit` if the time limit was hit. `solver_not_optimal` is no longer produced. The old label stays in the frontend map for stored legacy records.

5. **Version.** `BENCHMARK_VERSION = 3`. Base record gets `relaxed_limits: []`. The frontend type treats the field as optional for older records.

6. **Frontend.** `benchmarkWarningText` gets a `limits_relaxed` case that names the limits, and `BENCHMARK_REASONS` gets labels for the two new reasons. The existing warnings list is reused, following `docs/design-system/AI_GUIDELINES.md` (no new components, existing text styles). The warning is already counted by `by_warning` in the summary.

7. **Config keys.** Add the three keys to `DEPRECATED_NESTED_KEYS` (`learning`, `automation.ml_training`). `remove_deprecated_keys` runs from `_migrate_config` both before and after the template merge, so the keys are not re-added. No version bump, as with earlier dead-key removals.

8. **Model purge.** `ml/bootstrap.py` gets a purge helper run at the start of `ensure_active_models`, before the defaults-exist check so it cannot be skipped. It unlinks exactly `pv_error.lgb` and `load_error.lgb` (`missing_ok=True`) in `data/ml/models/`, `data/ml/models/defaults/` and each `data/ml/models/backup/*/`, logging each real deletion. `git rm ml/models/defaults/load_error.lgb`. `scripts/health_check.py` drops `optional_models`.

## Risks / Trade-offs

- [A relaxed day compares against a hindsight plan with looser limits than live planning can use] → The warning names the relaxed limits; it only applies to days where reality already exceeded them.
- [Implied inverter AC flow assumes PV charges the battery first] → That is the lowest AC flow the model allows, so the recorded point stays feasible; the cap is the larger of configured and that flow, and a still-infeasible day stores the specific reason.
- [Forecast prices 00:00-06:00 are up to a day old] → They are labelled `price_source: forecast` with `forecast_days_ahead`, replaced by newer issues as soon as they exist, and by published prices after publication.
- [Old duplicate forecast rows remain in user databases] → Date-based read; no migration needed. They age out with normal retention.
- [Deleting user files] → Exactly two named, unused files; the user decided this explicitly.
- [Other change touches `ml/price_forecast.py`] → This change only edits the slot loop call and `get_d1_price_forecast_fallback` plus the DB read helper; no price reserve code.

## Migration Plan

No schema or data migration. Upgrade: the first startup purges stale model files; the first benchmark run recomputes the 14-day window under version 3; the next forecast run writes 96-slot days. Rollback: revert the commit; deleted model files are unused and need no restoration.
