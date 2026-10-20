# Tasks

## 1. Backend benchmark

- [x] 1.1 Rewrite `implied_capacity()` in `backend/battery_benchmark.py` as a least-squares fit of cumulative stored energy (net>0 -> net*charge_eff, else net/discharge_eff) against SoC % over all slots of the window, capacity = slope*100, returning the window SoC range; remove `CAPACITY_MIN_SLOT_DELTA_PP` and `CAPACITY_MIN_MOVEMENT_PP`; add `CAPACITY_MIN_SOC_RANGE_PP = 20.0`; set `CAPACITY_TOLERANCE = 0.20`. Verify with unit tests in 3.x.
- [x] 1.2 Add `warnings: []` to `base_record()`; in `benchmark_day()` append `capacity_mismatch` to `warnings` and continue scoring instead of returning excluded. Verify: test 3.2.
- [x] 1.3 Add `by_warning` counts to `summarize()`. Verify: extend `test_summary_totals_cover_scored_days_only`.
- [x] 1.4 Bump `BENCHMARK_VERSION` to 2. Verify: service test that a stored v1 `capacity_mismatch` record inside the window is recomputed by `run_once()`.

## 2. Frontend

- [x] 2.1 Add `warnings: string[]` to `BatteryBenchmarkDay` and `by_warning` to totals in `frontend/src/lib/api.ts`; validation defaults missing values to `[]`/`{}` for legacy records. Verify: existing api tests pass.
- [x] 2.2 In `CommandDomains.tsx` hindsight ⓘ, show a non-blocking "Warnings" list for scored days with `capacity_mismatch` (recorded vs configured kWh) plus a small warning marker on the row, following `docs/design-system/AI_GUIDELINES.md` tokens; keep legacy `capacity_mismatch` reason rendering. Verify: test 3.4 and visual check.

## 3. Tests

- [x] 3.1 Update `tests/backend/test_battery_benchmark.py::test_capacity_mismatch_excludes_day_with_both_values` (rename e.g. `test_capacity_mismatch_warns_and_scores`) to assert status `scored`, `reason is None`, `"capacity_mismatch" in warnings`, both capacity values present. Run `UV_NO_SYNC=1 uv run python -m pytest tests/backend/test_battery_benchmark.py -v`.
- [x] 3.2 Add regression test: 64 kWh battery, 7 days, SoC quantised in ~1.15 pp steps with occasional counter-direction jitter steps, ~0.2 kWh/slot; assert day is scored, implied capacity within 20 % of 64, and no warning. Same pytest command.
- [x] 3.3 Add test where config is clearly wrong (config 64 kWh, flows/SoC imply ~40 kWh): assert `capacity_mismatch` warning with both values and status `scored`.
- [x] 3.6 Add test that a window with SoC range below 20 pp produces no warning.
- [x] 3.4 Add test in `frontend/src/components/CommandDomains.test.tsx` that a scored day with a `capacity_mismatch` warning shows the warning text with both values and counts in scored/total days. Run `pnpm vitest run src/components/CommandDomains.test.tsx` in `frontend/`.
- [x] 3.5 Run `./scripts/lint.sh` clean.

## 4. Show data with a note instead of dropping days

- [x] 4.1 EV threshold: replace `EV_ACTIVE_KWH` with `EV_CHARGING_MIN_KW = 0.02`; `no_discharge_slots` is true only when `ev_charging_kwh / slot_hours > EV_CHARGING_MIN_KW`. Verify: test 5.1 and existing `test_no_discharge_during_recorded_ev_charging`.
- [x] 4.2 Stored-energy change: add `stored_change_kwh` (terminal - initial after clamping) to records (`None` in `base_record`) and a `stored_change_kwh` total over scored days to `summarize()` (missing field counts as 0). Verify: tests 5.2 and extended summary test.
- [x] 4.3 Unverified slots: in `_recording_reason`, count slots (start-SoC slot plus day slots) whose `slot_recording()` is None or snapshot; exclude as `not_clean_recording` only above `MAX_UNVERIFIED_SLOTS = 4`; remove `MAX_SNAPSHOT_SLOTS`; keep `missing_values` blocking. Store `unverified_slots` and `day_slots`, and add an `unverified_slots` warning when the count is > 0. Verify: tests 5.3.
- [x] 4.4 Stock clamp: clamp initial and terminal stock to [0, capacity] and add a `stock_clamped` warning instead of `stock_out_of_range`; solver failure still stores `failed`. Verify: tests 5.4.
- [x] 4.5 Frontend types: add `stored_change_kwh`, `unverified_slots`, `day_slots` to `BatteryBenchmarkDay` and `stored_change_kwh` to totals in `frontend/src/lib/api.ts`, defaulting missing values for legacy records.
- [x] 4.6 `CommandDomains.tsx`: Warnings list covers all warning codes on scored days (`capacity_mismatch`, `unverified_slots` "N of M slots not verified", `stock_clamped`), row marker for any warning, and a muted "Battery ended X kWh fuller than it started; that value shows up the next day" note when scored days exist, score is null and summed stored change is positive. Verify: tests 5.5.

## 5. Tests for section 4

- [x] 5.1 Regression: net-discharge day with idle EV noise 7.5e-05 kWh in most slots is scored (not failed). Add a slot-length test that a 20 W threshold is applied as power.
- [x] 5.2 Record stores `stored_change_kwh` on a net-charging day; summary sums it over scored days.
- [x] 5.3 1 slot with no recording info: scored with `unverified_slots` warning and count 1; unverified start-SoC slot counts; 5 unverified slots: excluded `not_clean_recording`; unverified slot plus non-finite value: `missing_values`. Update existing exclusion parametrisations and the 2-snapshot test.
- [x] 5.4 Replace `test_end_stock_above_capacity_is_excluded` with a clamp test (scored, `stock_clamped`, terminal matches capacity); add a test that a solver failure on a clamped day stores `failed`.
- [x] 5.5 Frontend: net-charging scored day with null score shows the fuller note and missed kr; unverified-slot and clamped-stock warnings render in the Warnings list.
- [x] 5.6 Run lint.sh steps, full pytest and full vitest clean.

## 6. Recording gap slots (design decision 10)

- [x] 6.1 In `backend/battery_benchmark.py`, count a day slot with missing/non-finite energy or SoC (finite prices) as one unverified slot in `_recording_reason`; keep `missing_values` for missing/non-finite prices in day slots and for a missing start-SoC slot `soc_end_percent`. Verify: tests 6.3.
- [x] 6.2 In `benchmark_day`, after eligibility, treat missing energy in gap slots as 0 kWh for actual/hindsight/no-battery, and skip missing SoC in `implied_capacity`; history eligibility still uses the raw rows. `BENCHMARK_VERSION` stays 2. Verify: tests 6.3.
- [x] 6.3 Tests: 2026-10-11 gap slot pattern scored with `unverified_slots` count 1; missing energy equals 0 kWh costs; gap slot with missing price -> `missing_values`; 5 gap slots -> `not_clean_recording`; gap slot + 3 unverified = 4 -> scored; missing start SoC -> `missing_values`.
- [x] 6.4 Run ruff, ruff format, pyright, eslint, prettier, tsc, full pytest and full vitest clean.
