# Design

## Context

Verified facts (prod, 2026-11-22). See proposal.md for the motivation.

- The 978 clamped rows come from the old recorder (before commit 453e1095, 2026-10-03), which mixed a lagging, 0.1 kWh-quantised cumulative counter (`sensor.inverter_total_load_consumption`) with integrated water power. The current recorder integrates all slot energy from power history (`backend/recorder.py` around lines 386-404 and 471, `backend/core/slot_energy.py`) and produced no clamp since 2026-10-07; re-integration of 2026-11-14..22 matches to 1e-10. No root-cause hunt remains.
- `load_kwh` is `NOT NULL` in the baseline migration and `Mapped[float]` in `backend/learning/models.py`. Python code uses `COALESCE(load_kwh, 0)` in the energy router, the monitor and others, so NULL would silently become a fake 0 in the very places we want to protect.
- A mature provenance layer exists: `quality_flags.recording.components.<name>.method`. `has_unmeasured_device` (`ml/load_clean.py`) and its SQL twin `unmeasured_device_clause` / `UNMEASURED_DEVICE_SQL` (`backend/learning/models.py`) already exclude slots with an unknown device or unknown `load`. Water or EV with no history is already `unknown` (spec "Unavailable device sensors are recorded as unknown").
- The battery benchmark and grid-only comparison deliberately keep slots with an unknown device and `load = derived_history` ("partial": load plus water plus EV is still the exact demand). That must keep working for partial coverage.
- `store_slot_observations` merges `quality_flags` per field with ownership rules (`backend/learning/store.py` around line 170); a new top-level key must survive and be replaceable by a later recorder write.

## Goals / Non-Goals

**Goals:**
- No consumer treats a clamped, contaminated or legacy-counter base load as measured.
- One predicate decides "base load unreliable", with Python and SQL forms that stay equivalent.
- History is flagged once, safely and reversibly, with no schema change.
- Universal behaviour: derived from config, data and coverage, never from one installation's values.

**Non-Goals:**
- No NULL `load_kwh`, no schema change.
- No reintroduction of cumulative-counter load, no repair of old values (they cannot be recovered).
- No change to `docs/` (needs approval).
- Totals that sum recorded energy for the user (energy router range totals, cost cards) keep their numbers; they are not learning inputs.

## Decisions

### D1. Quality flag instead of NULL
Store `quality_flags.base_load = {"reliable": false, "reasons": [...]}` and keep `load_kwh` numeric.
Why: (1) the column is `NOT NULL`; NULL needs a SQLite table rebuild, a schema change that must be approved separately; (2) many readers coalesce NULL to 0, `Mapped[float]` and pandas `> 0.001` filters treat NULL inconsistently, so a NULL is easy to turn back into a fake 0; (3) the existing rule "numeric column keeps 0 as placeholder, provenance says unknown" already applies to water and EV and is honored by every filter; (4) a flag is reversible and carries a reason. Alternative rejected: NULL plus nullable column (risk, approval, no extra safety). Alternative rejected: reuse only `load.method = unknown` (cannot be set on legacy rows without `recording`, and would break the benchmark's partial-demand rule for coverage cases).
A reliable slot carries no key, so existing rows and the common case are byte-identical.

### D2. Extend the existing predicate, do not add a parallel one
`has_unmeasured_device` and `UNMEASURED_DEVICE_SQL` gain `OR base_load.reliable is false`. The flag check runs before the `recording` parse (legacy rows have no `recording`). SQL uses `json_extract(flags, '$.base_load.reliable') = 0` inside the existing `json_valid` guard. A shared helper `base_load_unreliable(flags)` and `base_load_demand_affected(flags)` live in `backend/measurement_provenance.py`; a test pins Python and SQL results equal over a fixture matrix. All current callers of the clause (store, forecast router, energy router `_base_load_avg_daily_kwh`, monitors energy balance, ml/evaluate, ml/train via `clean_load_observations`) are covered by this one change.

### D3. Clamp sets the load method to `unknown`, partial coverage does not
Reasons split in two classes. Demand-affecting (`negative_after_subtraction`, `load_partial_coverage`, `legacy_counter_clamp`, `legacy_counter_after_clamp`): the recorded water plus EV exceeds what the house used, so load plus water plus EV is wrong. The recorder also sets component `load` to `unknown`, which the benchmark, grid-only comparison and calibration already refuse; for migrated rows (no `recording`) `base_load_demand_affected` is checked explicitly in `calibration_eligible`, `slot_recording` and the grid-only reader. Demand-exact (`device_partial_coverage`): total load still contains the uncovered heater energy, so demand stays exact and the benchmark keeps the slot as "partial". `inactive_device_drawing_power`, `device_disabled_but_configured` are demand-exact too (the energy is in total load; only the split is wrong).

### D4. Partial coverage rule
`compute_slot_energy` switches the EV, water and total-load integration to `integrate_power_points_covered` and exposes `ev_coverage`, `water_coverage` and `load_coverage` as a share of the slot per sensor. Flag when any enabled device sensor is below the named constant `MIN_COVERAGE_SHARE = 0.95` (about 45 s of a 15-minute slot), reason `device_partial_coverage`; the same constant on `load_power` gives `load_partial_coverage`, which is demand-affecting (total and derived load are understated), so the recorder also sets `load` to `unknown`. The value is kept, the method stays `power_history` (spec "Partly unavailable boundary slot" is unchanged except that the slot is flagged for base load). A fully absent sensor stays `unknown` through the existing path. Backfill reuses the same helper.

### D5. Isolation returns a result object
`isolate_base_load` returns `BaseLoadIsolation(kwh, clamped)`. Recorder and backfill both call it, then compose `base_load` reasons with one helper `build_base_load_flag(clamped, partial_devices, inactive_devices)` so live and backfill cannot diverge. Exact equality (total = devices) is not a clamp; a tolerance of 1e-9 kWh absorbs float noise.

### D6. Inactive-but-configured devices
`build_slot_sources` also lists sensors of heaters and chargers that config excludes (`has_water_heater` false, `has_ev_charger` false, `enabled` false) as `inactive_*_sensors`. They are added to the one batched history request (no extra HA call, no snapshot read). If integrated active energy (same noise floor and cutoff) is above 0, the slot is flagged `inactive_device_drawing_power` and a once-per-sensor-and-process warning is logged. The device remains `disabled_zero` 0 and is not "measured": we do not guess a split. EV is included because it is the same code path and the same failure mode.

### D7. Noise floor in code
`normalize_active_power_kw` uses `max(idle_power_threshold_kw, NOISE_FLOOR_KW)` with the named constant `NOISE_FLOOR_KW = 0.010` (accepted value; boundary tests pin it). This is the single shared function (history, snapshot, backfill, planner progress, disaggregation), so all paths stay consistent. The floor applies to heater sensors only (callers pass the heater's `idle_power_threshold_kw`); PV, grid, battery and total-load sensors pass no cutoff and are only unit-converted, as before. Config default and the validation rule (non-negative) stay; a configured 0 remains legal and now means "no cutoff beyond sensor noise". Stored `idle_power_threshold_kw` in per-device metadata stays the configured value, so `water_progress` equality checks against stored rows keep matching. Rationale for 10 W: well below any heating element, above the 1-2 W stray readings and typical standby draw of smart plugs.

### D8. Historical migration
`backend/learning/base_load_migration.py`, one function `flag_historical_base_load(db_path, config)`, called once from the startup lifespan after DB migrations, guarded by `system_state` key `base_load_integrity_v1` (set only after success, in the same transaction as the updates). No rule uses a date, because installations switched to the power-history recorder at different times.

Per-row signal, verified in code: `backend/recorder.py` (`recording_metadata` into `quality_flags.recording`) and `backend/learning/backfill.py` (same call, owner `backfill`) both write `quality_flags.recording` for every row since provenance was introduced (2026-10-07 on the maintainer's install); the store merge keeps it (`"recording" not in flags` is already how `store.py` detects legacy rows). The old counter-based recorder wrote no `recording`. One gap: rows written by the new recorder between its introduction (453e1095) and the provenance commit (836bc247) also lack `recording`. They cannot be told apart from old-recorder rows per row, so rule (a) treats them alike. This is the safe direction: such a row with `load_kwh = 0` and `water_kwh > 0` is a base-load zero next to a running heater and is not trustworthy either way. `legacy_attestation` rows are not special-cased; a clamp is a clamp.

- (a) rows where `quality_flags` has no `recording` key (NULL flags included), `load_kwh = 0` and `water_kwh > 0` get `legacy_counter_clamp`. The slot starting 15 minutes later (if present) gets `legacy_counter_after_clamp` (the old recorder pushed the missing energy into the next slot). A wrongly dropped neighbour costs one training slot; a kept inflated one corrupts the model.
- (b) rows with `recording.components.water.method = disabled_zero` when the current config has at least one `water_heaters` entry with a `sensor` (enabled or not). Date-free by construction. HA history is purged, so per-row evidence cannot be recovered; configuration is the only universal evidence. No opt-out (decision): excluding is the safe direction because dropping training rows never fakes data. Installations with no configured sensor are untouched.
- Expected impact (prod, from the investigation): rule (a) up to 978 rows plus at most as many following slots (fewer when adjacent); rule (b) about 25 days x 96 = roughly 2,400 rows (2026-10-07..11-01). Together about 4,000 of about 36,800 rows (roughly 11 percent), all in the past and none in the recent clean period. Values are never changed or deleted; installations without old-recorder rows or without a configured-but-disabled heater see zero flagged rows.
- Fresh install: if `slot_observations` or `system_state` does not exist yet the migration returns without error (debug log, retried next start); an empty table completes (zero counts logged at info) and records the state key. Real errors stay fail-open at the call site.
- Logging: the migration logs one line with the counts flagged per rule (`a`, `after_clamp`, `b`), plus skipped unparseable rows, so the effect is visible in the log.
- Flags merge into the existing JSON (existing keys preserved, reasons unioned and sorted, `source: "migration"`), NULL flags become `{"base_load": ...}`, unparseable flags are skipped and counted. Idempotent by union plus the state key. Batches of 1000 rows in one `BEGIN IMMEDIATE`. A pre-migration DB backup is already taken by `db_safety` before Alembic.
- Rollback: remove the `base_load` key where `source` is `migration`, then delete the state key (module docstring).

### D9. Consumers of `load_kwh`
Complete list from the code search (non-test):

Learning and ML
1. `ml/train.py` (`_load_raw_slot_observations`, `clean_load_observations`) - via D2 mask in `ml/load_clean.py`; add clamp-day statistic exclusion of flagged rows (`clamp_slot` must not count flagged rows).
2. `ml/load_clean.py` `load_level_7d`, `slot_means_7d` - operate on the cleaned frame, covered by 1.
3. `ml/forward.py` `determine_graduation_level` - currently counts `load_kwh IS NOT NULL`; add `NOT UNMEASURED_DEVICE_SQL` (use the unaliased column form). This is deliberately the full predicate, not only the flag: graduation counts exactly the days load training keeps (`clean_load_observations` uses the same rule), so a model is never graduated on days it will not train on. `unconfigured_zero` and `disabled_zero` devices do not drop a day; `unknown`, `snapshot`, `mixed` devices and unknown load do.
4. `ml/evaluate.py` MAE and `training` observation frame (line ~416 sets unmeasured to NaN) - covered by D2 (already uses the mask).
5. `ml/api.py` - reads forecast values only, no observation `load_kwh`.
6. `backend/learning/store.py` `get_forecast_vs_actual` (line ~948) and the load MAE query (~1126) - covered by D2 clause; line ~1378 (water-progress observation reader) selects `load_kwh` only to hand it through, add the exclusion where it feeds a load figure, else unchanged.
7. `backend/learning/backfill.py` - writer; adopts D5.

Backend readers
8. `backend/api/routers/energy.py` `_base_load_avg_daily_kwh` - covered by D2; range totals (lines ~254-310, 359, 505) are household energy totals and unchanged (Non-Goal).
9. `backend/api/routers/forecast.py` (lines ~200, ~497 actual load for charts) - return null for flagged slots.
10. `backend/api/routers/schedule.py` (lines ~400, 510-560 `actual_load_kwh`) - null for flagged slots.
11. `backend/monitors.py` energy-balance invariant - covered by D2.
12. `backend/validation.py` - writer-side range validation, unchanged.

Demand-based (load + water + ev)
13. `backend/battery_benchmark.py` (`meter_battery_flow`, `slot_recording`, line ~448) - exclude `base_load_demand_affected` rows.
14. `backend/grid_only_comparison.py` - same, plus the existing `clamp_hidden_demand` rule keeps working.
15. `backend/comparison_history.py` / `backend/observation_provenance.py` `calibration_eligible` - exclude demand-affecting rows.

Not consumers of observations: `planner/*`, `backend/core/forecasts.py` (forecast `load_kwh` is a different field), `backend/core/ha_client.py` synthetic load, scripts and `debugging/` (one-off tooling, `bin/fix_load_gaps.py` is a legacy manual script and is left alone).

## Risks / Trade-offs

- [Over-flagging in (b)] a user who really has no heater but kept a stale sensor loses those slots for training → accepted: only excluded, never deleted, reasons visible, counts logged.
- [Noise floor changes recorded water slightly] values below 10 W disappear for configs with cutoff 0 → below 1 Wh per slot; the energy stays in base load, which is correct (spec "Idle draw is household consumption").
- [Partial-coverage threshold] 0.95 may flag short HA restarts → such slots are not used for base-load learning; a stricter or looser constant is one line and covered by boundary tests.
- [Flag lost on UPSERT] a later backfill write could overwrite `base_load` → store merge keeps the recorder's flag, and a backfill write for a recorder-owned slot never clears it (tested).
- [Python/SQL drift] two forms of one rule → a parametrised equivalence test.
- [Startup cost] one scan of `slot_observations` (about 30k rows on prod) → batched, once, guarded.

## Migration Plan

1. Deploy code. New writes are flagged immediately.
2. At first start the one-time migration runs after Alembic and records `base_load_integrity_v1`.
3. Next training run reports a higher `dropped_unmeasured_device_rows`; the load model retrains without the flagged rows.
4. Rollback: revert code; the `base_load` key is ignored by old code. Optional SQL to strip the migration-set flags is in the module docstring.

## Open Questions

- None blocking. Follow-up only: `docs/` should mention the 10 W floor next to `idle_power_threshold_kw`; `docs/` is not edited by this change.
