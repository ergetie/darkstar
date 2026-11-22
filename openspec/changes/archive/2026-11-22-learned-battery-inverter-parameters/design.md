# Design

## Context

See proposal.md for motivation. Facts that shape the design (code verified 2026-11-22):

- Kepler's SoC equation (`planner/solver/kepler.py:783`) and the price reserve (`planner/strategy/price_reserve.py`) use only `charge_efficiency` / `discharge_efficiency`, read from `system.battery` or `battery` in the config (`planner/solver/adapter.py:707`, `planner/pipeline.py:1154`). Kepler's charge/discharge are AC-bus flows; the DC-coupled AC limit already caps grid charging (`kepler.py:874-880`). The benchmark (`backend/services/benchmark_service.py:83`, `backend/battery_benchmark.py`) builds its own `KeplerConfig` from the same config through `config_to_kepler_config`.
- Recorder battery counters (`backend/recorder.py:345`) are battery-DC-side integrated power. `soc_start_percent` is not written; the previous slot's `soc_end_percent` is the start (as `battery_benchmark.implied_capacity` does).
- Slot reliability machinery already exists: `UNMEASURED_DEVICE_SQL` / `has_unmeasured_device` and `base_load.reliable` (commit 2ed8de30), `slot_recording()` (clean / snapshot / partial) in `backend/battery_benchmark.py`, `quality_flags.exclude`, `meter_battery_flow()`.
- Planner runs are archived (`backend/services/plan_archive.py`, commit 23f5436a): inputs, schedule, redacted config, initial SoC. `PlannerPipeline.generate_schedule(input_data, save_to_file=False, publish_state=False, now_override=...)` can replay a record offline.
- Notifications: executor toggles live in `executor.notifications.*` (`executor/config.py` `NotificationConfig`, `backend/api/routers/executor.py`, `Executor.tsx`, Settings `types.ts`); delivery from the backend goes through `get_executor_instance().send_notification(...)` (as the test endpoint does).
- Health issues (`backend/health.py`, e.g. PV site sanity) are the existing warning surface and are snoozable (spec `system-alert-snooze`).
- Reflex: `backend/learning/reflex.py` (630 lines), `bin/run_reflex.py`, `reflex_state` and `learning_daily_metrics` tables (the latter is read by nothing; `tests/planner/test_no_learning_overlay.py` already pins that), store methods `get_reflex_state`, `update_reflex_state`, `get_capacity_estimate`, `get_forecast_vs_actual`, `get_low_soc_events` (used only by Reflex), tests `tests/ml/test_reflex.py` and `tests/ml/test_reflex_ev_losses.py`.
- Alembic head is `c3a9e5d7b1f2`; migrations are idempotent (`inspector.get_table_names()` guard) and tested with the `alembic_db` fixture (see `tests/test_migration_ev_charger_observations.py`).

## Goals / Non-Goals

**Goals:**
- One resolution seam: every consumer gets effective battery efficiencies from a single pure function, so planner, price reserve, benchmark and archive cannot disagree.
- Estimators are pure functions over row lists with an `as_of` argument, so the same code serves the daily service, the offline walk-forward evaluator and the tests.
- A learned value can never be stale, implausible, jumpy, silent or unoverridable.

**Non-Goals:**
- No learning of capacity, max power, PV confidence, base factor, S-index weights, risk or minimum SoC (user preferences or not identifiable).
- No inverter standby in the planner (cost-only, does not change decisions).
- No EV loss learning (D11).
- No change to `slot_observations` columns and no new dependency.

## Decisions

### D1. Parameter set and storage
Four keys: `battery_round_trip_efficiency` (RTE), `inverter_charge_loss`, `inverter_standby_w` (informational), `inverter_discharge_efficiency` (no estimator, default 0.97, lock-only). Tables (Alembic):
- `learned_parameters`: `key` PK, `learned_value` REAL NULL, `confidence` REAL NULL, `evidence_json` TEXT, `estimated_at` TEXT NULL (last accepted estimate), `applied_value` REAL NULL, `applied_at` TEXT NULL, `status_note` TEXT NULL, `locked` INTEGER 0/1, `locked_value` REAL NULL, `updated_at` TEXT.
- `learned_parameter_history`: `id` PK autoincrement, `key`, `at`, `event` (`learned`, `expired`, `recovered`, `locked`, `lock_changed`, `unlocked`), `old_value`, `new_value`, `confidence`, `evidence_json`, `notify_state` (`pending`, `sent`, `disabled`, `none`), `notified_at`; index on `(key, at)`.
- `inverter_loss_observations`: `slot_start` PK, `loss_kwh` REAL NOT NULL, `created_at` (same side-table pattern as `ev_charger_observations`, so `slot_observations` stays untouched).
`learned_value` is the latest accepted estimate; `applied_value` is the step-limited value the planner uses while the value is valid. Keeping them apart shows "learned says X, applied is Y (moving)" and lets a lock coexist with continuing estimation.
Alternative: JSON blob in `system_state`. Rejected: no typed history, no queryable evidence, harder to test migrations.

### D2. Pure estimators (`backend/learning/battery_estimators.py`)
All take row dicts and `as_of`, return `Estimate(value, confidence, evidence, rejected_reason)`; they never touch the DB.
- **RTE.** Rows: past slots with non-null charge, discharge, `soc_end_percent`, battery and SoC components `recording` measured and live, not `exclude`. The estimator works on *runs*: maximal stretches of back-to-back eligible slots (any gap, null or unusable slot ends a run; runs shorter than 1 day are ignored; no whole-day or midnight alignment is required). The first slot of a run only supplies the starting SoC. Each run is cut into chunks of about 7 days (SoC is recorded in every slot, so a run can be cut anywhere; each chunk starts at the end SoC of the slot before it, and the SoC change of a run telescopes to its first and last reading). The pool is corrected for the net SoC change: with `dS = sum(dSoC) x config capacity` and the symmetric split of D2a, `charge x sqrt(R) - discharge / sqrt(R) = dS`, solved as `sqrt(R) = (dS + sqrt(dS^2 + 4 x charge x discharge)) / (2 x charge)`; it reduces to `discharge / charge` when the pool is SoC-neutral. Capacity therefore only scales a correction that is small over a long pool; the correction share `|dS| / charge` must be <= 10 %, otherwise the estimate is rejected. Gate: pooled run time >= 28 days and pooled discharge >= 5 x config capacity. Lookback 120 days. The earlier whole-day, SoC-neutral-window design was dropped after it learned nothing on production data: only 32 of about 46 eligible days were complete (a single lost slot breaks a whole day) and the longest stretch of consecutive complete days was 6, below the 7-day minimum window, so no window could form whatever the SoC did.
- **Units.** See D2a. The loss fit regresses on the DC charge counter (that is what the backtest validated) and the result is converted to the AC basis before storing.
- **Inverter loss.** Eligible slots: `slot_recording() == "clean"`, not `exclude`, `NOT UNMEASURED_DEVICE_SQL` (or its Python twin), all energy values and the battery values non-null, past. Fit `loss_kwh = standby_kw x hours + k x charge_kwh` by Huber-weighted iteratively reweighted least squares (numpy, 20 iterations, scale from MAD). Slots with a stored sensor loss use it instead of the residual. Gate: >= 1000 slots spanning >= 14 days and sum(charge) >= 2 x config capacity. Lookback 120 days. Output two estimates: `inverter_charge_loss` = k / (1 + k) (AC basis, D2a) and `inverter_standby_w`. Bounds apply to the stored AC-basis value.
- **Confidence** (both): split-half consistency, `min(1, size / full) x max(0, 1 - |a - b| / tol)` where a, b are the estimates of the odd/even chunks (RTE, tol 0.03, full 42 days) or the first/second chronological half of slots (loss, tol 0.03, full 2000 slots). Applied only when confidence >= 0.5.
- **Bounds** (reject, not clamp): RTE 0.80..0.995, charge loss 0.0..0.15, standby 0..300 W, inverter discharge efficiency (lock) 0.85..1.0.
Constants are named module-level values pinned by tests. None is per-user: every threshold scales with the configured capacity or is a physical bound.
Alternatives: median of per-window ratios (rejected: 1 % SoC steps make short windows noisy, pooling is what the backtest validated: 0.962 in two disjoint periods); ordinary least squares for the loss (rejected: outlier slots such as unreported devices bias it).

### D2a. Units: which side each stored value refers to
Kepler's `charge` and `discharge` are AC-side energies; recorded `batt_charge_kwh` / `batt_discharge_kwh` are DC-side (battery terminals). The two sets are never mixed.
- `battery_round_trip_efficiency`: DC/DC at the battery terminals, estimated only from DC counters and SoC (consistent by construction). Symmetric split assumed: each way is sqrt(RTE).
- `inverter_charge_loss` (ell): fraction of AC-side energy entering the charge path lost before the DC side, so `DC_charge = AC_charge x (1 - ell)`. The balance gives `loss = AC_net - DC_net`; while charging `AC_charge = DC_charge x (1 + k) + standby`, so the fit's `k` (per DC charge kWh) converts to `ell = k / (1 + k)`. Using `1 - k` directly would be off by about 0.5 point at k = 0.075.
- `inverter_discharge_efficiency` (eta): DC to AC. Not measurable, default 0.97, lock-only.
- Effective values for the planner, per AC kWh as Kepler uses them: `charge_eff = (1 - ell) x sqrt(RTE)` (stored kWh per AC kWh charged) and `discharge_eff = sqrt(RTE) x eta` (AC kWh out per stored kWh). Check against the SoC equation `stored += charge x charge_eff - discharge / discharge_eff`: stored gain = AC x (1 - ell) x sqrt(RTE) = DC_charge x sqrt(RTE), correct; stored drawn = AC_dis / (eta x sqrt(RTE)) = DC_dis / sqrt(RTE), correct. A test pins this identity on a synthetic DC battery.
- Standby and PV/discharge conversion losses are not in the pair; the AC-side flow from the balance contains them (D13 handles standby).
`apply_to_config` therefore only ever receives AC-basis values, and the benchmark's `implied_capacity` (AC flows from `meter_battery_flow`) stays consistent with them.

### D3. Lifecycle (`backend/learning/learned_parameters.py`)
`apply_estimate(state, estimate, now)` is pure and returns the new state plus history events:
1. Rejected or gated-out estimate: no change, `status_note` records the reason, `estimated_at` not refreshed.
2. Accepted: `learned_value`, `confidence`, `evidence`, `estimated_at` updated.
3. If locked: stop here (no applied change, no notification).
4. First value: `applied_value` = learned. Later: skip when |learned - applied| < deadband; else move toward learned by at most the step. Once per local day. Steps/deadbands: RTE 0.01 / 0.002, charge loss 0.01 / 0.002, standby 20 W / 5 W.
5. Expiry is evaluated at resolution time, never stored as a side effect: valid iff `now - estimated_at <= 30 days`. The daily run compares the previous and the new resolved source and writes `expired` / `recovered` events from the difference, so a crash cannot leave a stale value silently valid.
The first adoption is direct because there is no learned baseline to step from; the gate, bounds and confidence are the protection. Alternative: step from the config-implied RTE (`charge_eff x discharge_eff`). Rejected: config pair mixes inverter loss, so the baseline is not comparable (see Open Questions).

### D4. One resolution seam
`resolve_battery_parameters(config, rows, now) -> ResolvedBattery` (pure) returns per-parameter `{value, source}` and the effective `charge_efficiency` / `discharge_efficiency`. Rule: the pair is learned-based only when RTE, charge loss (learned valid or locked) and discharge efficiency (locked or default) are all available; otherwise both come from `battery.charge_efficiency` / `discharge_efficiency` in config. `apply_to_config(config, resolved)` returns a deep copy with those two keys replaced in whichever dict (`system.battery` or `battery`) the planner reads, so Kepler, price reserve and `config_to_kepler_config` all see them without edits to their internals. Call sites: `PlannerPipeline.generate_schedule` right after `active_config` is built (reading rows through the existing `LearningStore`, off the event loop like other pipeline DB reads, failure = config fallback + warning log), and `BenchmarkService.run_once`. The resolved result is captured for the archive (`plan_archive.capture("battery_parameters", ...)`).
Standby is never part of the pair (D8).

### D5. Daily service and API
`LearnedParametersService` follows `BenchmarkService`: started in the lifespan, runs 5 minutes after startup and daily at 00:40 local (after the benchmark's 00:10), each estimator fenced individually, errors logged, never raised. `POST /api/learning/parameters/recompute` calls the same `run_once`. Routes live in `backend/api/routers/learning.py` (cross-site write protection middleware already covers non-GET). `POST /api/learning/run` loses the Reflex step and keeps training; its response drops `reflex_report` (the UI does not read it; verify by grep in the frontend task).

### D6. Notifications
One message per run listing every applied change (parameter, old -> new, window days). Gate: `executor.notifications.on_learned_parameter_change` (default true), added everywhere `on_ev_soc_stale` appears: `config.default.yaml`, `NotificationConfig`, executor config parse, `GET /api/executor/notifications` (both branches), Executor page list, Settings `types.ts`, search guides. Delivery through `get_executor_instance().send_notification`. History rows carry `notify_state`: `pending` until sent; a failed or impossible delivery (no executor, exception) leaves them `pending` and the next run retries rows younger than 3 days; toggle off writes `disabled`. Lock actions are user-initiated: `notify_state = none`.
Executor shadow mode logs "would send" and returns success, like every other notification; accepted.

### D7. Lock
Lock state lives in `learned_parameters` (`locked`, `locked_value`). Resolution order: locked, learned (valid), default (discharge efficiency only), config fallback. Lock validation uses the same bounds as D2. A locked RTE or charge loss still requires the other component to resolve for the pair to be learned-based; otherwise the config pair applies and the UI says which component is missing (resolved object carries `missing: [...]`).

### D8. Inverter standby is informational
A constant draw is added to every plan equally, so the optimal schedule is unchanged; including it would only shift reported costs. Stored and shown, never applied. Revisit only if a later change models cost totals.

### D9. Optional inverter-loss sensor
New optional `input_sensors.inverter_power_losses`. The recorder adds the entity to the slot history batch it already issues (`get_power_history_batch`), integrates with the existing power-to-energy helpers (units via the sensor-unit machinery), and writes `inverter_loss_observations` only when integration covered the slot; unavailable = no row, never 0. The estimator prefers a stored value per slot. Kept as its own task group so it can ship or slip independently of the balance path.

### D10. Warn-only checks (`backend/learning/battery_warnings.py`)
Pure functions plus a `HealthIssue` producer in `backend/health.py` (info severity for capacity, warning for power; snoozable like other issues).
- Capacity: weekly implied capacity via the existing `implied_capacity()` fit with effective efficiencies, window needs SoC range >= 20 pp; warn when the two latest consecutive weeks differ >= 25 % from the median of the 8 preceding weeks (>= 4 valid). Winter +20 % and summer shifts stay below the threshold; the 2026-08 module outage (34 -> 18-20 kWh, -42 %) trips it.
- Power: planned slots at >= 95 % of the configured limit (from `slot_plans.planned_charge_kwh` / `planned_discharge_kwh`) versus recorded power, >= 20 slots in 14 days, median ratio < 0.8.
Neither writes anything; the existing `capacity_mismatch` benchmark warning (config vs implied) is unchanged.

### D11. EV charging-loss learning is a follow-up
The planner's EV model is `car = eff x wall - overhead x hours - start_loss x starts` (`ev-charging-losses`). Constant-power sessions make `wall` proportional to `hours`, so efficiency and overhead are not separable; prod car-meter data (5-6.5 %) matches config. A clean version would learn one combined number from car-meter sessions only (>= 5 kWh, >= 10 sessions, never SoC-derived), but that changes which model parameter it maps to. Follow-up change `ev-learned-charge-efficiency`, after this store exists (a new key plus an estimator; no schema change). Removing the old analyzer loses nothing in practice: it has not run automatically since `06b40f9a`.

### D12. Reflex removal and stale-override safety
Delete `reflex.py`, `bin/run_reflex.py`, the `pyproject.toml` per-file-ignore, `tests/ml/test_reflex*.py`, store methods listed in Context, `ReflexState` and `LearningDailyMetric` models. Alembic migration drops `reflex_state` and `learning_daily_metrics` after the three new tables are created (idempotent guards; downgrade recreates them empty from the baseline definitions). Config: add `DEPRECATED_NESTED_KEYS["learning"]` entries `reflex_enabled`, `max_daily_param_change`, `min_sample_threshold`, `min_improvement_threshold`; remove them from `config.default.yaml`, the Settings page ("Learning Parameter Limits" section, the Reflex toggle, `guides.ts` text), `types.ts`. Aurora: remove toggle, `reflexEnabled` state, `Api.aurora.toggleReflex`, `state.reflex_enabled` (backend `forecast.py`) and `POST /api/aurora/config/toggle_reflex`. A guard test fails if any source file under `backend/`, `planner/`, `executor/`, `ml/` references `learning_daily_metrics`, `reflex_state` or `reflex_enabled` (migrations and the migration tests excepted), so a stale-row override cannot come back unnoticed. Values Reflex wrote into `config.yaml` stay as manual settings (the user's file is not rewritten except by the existing dead-key migration).
Tests that borrow `reflex_enabled` as a sample key (`tests/config/test_config_write_symlink.py`, `test_dead_error_correction_migration.py`, `test_dead_load_safety_margin_migration.py`) switch to another key.

### D13. Offline evaluation (`backend/learning/hindsight_evaluation.py`, `scripts/evaluate_learned_parameters.py`)
Walk-forward SoC replay (the objective measure), because counterfactual plan cost needs a truth model and any such model would be the thing under test. Basis (see D2a): both arms are driven by the same AC-side battery flow per slot, derived from the energy balance `net = import - export + pv - load - water - ev` (the quantity `meter_battery_flow` uses: charge = max(net, 0), discharge = max(-net, 0)), after subtracting the walk-forward standby estimate x slot hours from `net` for both arms alike (standby is in neither pair). Only slots eligible for the loss fit (clean recording, base-load reliable, non-null, not `exclude`) may lie in a horizon; a horizon containing any other slot is skipped and reported. The DC counters are never used here. For each ok archived run: estimate parameters with `as_of = run start` using the D2 estimators on a read-only DB, roll SoC from the recorded start SoC (previous slot's end SoC) under (a) the run's own config efficiencies and (b) the learned effective ones with `stored += charge x charge_eff - discharge / discharge_eff`, and record absolute error and bias against recorded SoC at 6/12/24 h. Exit non-zero when learned 24 h MAE exceeds config 24 h MAE by > 0.25 pp or fewer than 10 runs are evaluable. `--replan` re-solves each run through the pipeline under both sets and reports differing battery-action slots and planned-charge delta (informational). The automated test builds a synthetic archive and DB with known efficiencies and asserts the ordering, no-leakage and exit codes; a separate test asserts read-only behaviour.

### D14. UI
Battery settings tab gets a "Learned parameters" section (`frontend/src/pages/settings/components/`), using design-system tokens and the card/badge/banner classes of `docs/design-system/AI_GUIDELINES.md`: one row per parameter with effective value, source badge (`locked` accent, `learned` good, `default`/`config` muted, `expired` warn), learned value with confidence, evidence line (window days, slots), last change, a lock switch with a numeric input, and a collapsed history list. Shared code touched: `lib/api.ts`, settings `types.ts`; verification must open Settings (all tabs that share the registry), Executor and Aurora, per the backlog verification rule.

## Risks / Trade-offs

- [Learned pair differs from config pair and shifts plans] -> gate, bounds, step, deadband, confidence, lock, expiry, notification, and the offline gate that the learned pair must not predict SoC worse than config.
- [First adoption jumps from config to learned] -> prod numbers: config product 0.92 x 0.95 = 0.874 vs learned (1 - 0.0698) x 0.962 x 0.97 = 0.868, a small first step on the reference install; other installs see their own first step in the notification.
- [Balance residual absorbs unmeasured loads] -> only base-load-reliable, clean-recording slots; robust fit; confidence split-half; bounds reject absurd values.
- [Charge-loss fit confounds PV conversion loss] -> accepted: it is the share that scales with charge energy; documented in evidence text, lockable.
- [Dropping tables is irreversible] -> both tables are unused or Reflex-only; migration runs under the existing pre-migration DB backup (`database-backup-rollback`); downgrade recreates empty tables.
- [`learning.*` keys removed from user configs] -> only dead keys; values Reflex wrote elsewhere untouched.
- [Notification noise] -> deadband, one combined message, toggle.
- [Benchmark history recomputed with new efficiencies] -> `BENCHMARK_VERSION` is not bumped; only new scoring days use the effective values (stated in the daily-battery-benchmark delta).

## Migration Plan

1. Deploy: startup runs Alembic (new tables, drop old), config migration (remove dead keys), first estimate 5 minutes later. Until a gate is met everything reports `config` fallback and planning is unchanged.
2. Rollback: downgrade drops the three new tables and recreates the two old ones empty; re-adding Reflex code is not supported. Removed config keys are not restored (nothing reads them).

## Open Questions

Each has a recommended answer; none changes specs or task breakdown.
- Decided (coordinator, user may override): first adoption direct; remove `min_sample_threshold` / `min_improvement_threshold`; capacity threshold 25 %; keep the inverter-loss sensor; no `BENCHMARK_VERSION` bump; service at 00:40; leave the Settings-warning backlog item untouched.
- Update `docs/ARCHITECTURE.md` / `docs/DEVELOPER.md` Reflex sections: needs the user's approval (AGENTS.md); pending. Tasks 12.1 and 12.2 are marked "approved by the user 2026-11-22". Recommended: approve.


## Implementation notes (recorded during apply, 2026-11-22)

Deviations and refinements found while implementing; the specs are unaffected unless stated.

- **Rebase on `planner-run-archive` and `base-load-integrity`.** The archive record gains `battery_parameters` (effective pair, per-parameter source and config pair) in `_build_record`; `FORMAT_VERSION` stays 1 and readers treat the key as optional. Loss-fit eligibility is `slot_recording() == "clean"` (which already rejects base-load flags that affect demand), not `exclude`, and `base_load_unreliable(flags)` is false. `slot_recording` only accepts `disabled_zero` and `power_history` device methods, so a device configured but without sensor (`unconfigured_zero`) makes a slot ineligible; that is the existing project semantic and is kept.
- **Resolution signature.** `resolve_battery_parameters(config, states, now)` takes stored parameter states, not rows. Planner, benchmark and the evaluator read states through `resolve_effective_config(config, db_path, now)` (sync read-only sqlite in `asyncio.to_thread`; any failure keeps the config values). `PlannerPipeline.generate_schedule` has an optional `battery_parameters` argument so an offline replay can plan with explicit parameters instead of the database.
- **Standby confidence.** The standby estimate shares the confidence of the charge-loss fit (one fit, one data set); it keeps its own bounds check.
- **Capacity warning window validity.** A weekly window needs at least 4 usable days (`CAPACITY_WINDOW_MIN_DAYS`) in addition to the SoC range of 20 pp. Windows end yesterday and do not overlap.
- **Warning severity.** Both battery warnings use health severity `warning` (not `info`), because only critical and warning issues render a snooze control; info issues only support acknowledgement with a numeric value.
- **Service gating.** The service skips estimation when `learning.enable` is false (the master telemetry switch); no estimator runs, but stored values still resolve and expire normally, `expired` history rows are written and notified, and pending notifications are retried (`run_once(..., run_estimators=False)`).
- **Evaluator.** Learned parameters are estimated once per UTC day with `as_of` at that day's start, which precedes every run of the day (no leakage, one estimate serves many runs). A run counts as evaluable when it has a 24 h result. `--replan` runs in a scratch directory under `~/.cache/darkstar-evaluate`, with learning telemetry off, the database path pointing at the given database, no site location (no temperature request) and no EV SoC sensors (no Home Assistant request).
- **Removed read path.** `LearningStore.get_forecast_vs_actual` was only used by Reflex and is removed with it; the `energy-recording` delta keeps its generic forecast-versus-actual scenario (the archive validator requires every scenario of a MODIFIED requirement to be restated), which now has no caller.
- **Aurora toggle route.** A removed POST route answers 405 (not 404) because the SPA catch-all is GET-only; the test accepts both.
- **Visual check (10.5).** The Playwright smoke test needs system libraries (libatk) that the unprivileged build container does not have, so no browser could be started in the apply run; shared pages are covered by the jsdom page tests. The orchestrator later did the visual check with screenshots (see task 10.5).
