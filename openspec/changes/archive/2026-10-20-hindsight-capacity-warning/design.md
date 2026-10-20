# Design

## Context

`benchmark_day()` in `backend/battery_benchmark.py` calls `implied_capacity()` over the day plus up to `CAPACITY_HISTORY_DAYS` (6) earlier eligible days. That function accumulates energy and SoC movement only for slots where SoC moved at least `CAPACITY_MIN_SLOT_DELTA_PP` (1 pp) in the same direction as the flow, then returns `capacity_mismatch` (status `excluded`) if the result is >15 % off with >=20 pp movement. Results are JSON records in `system_state`, keyed per day, re-computed by `BenchmarkService.run_once()` only when `_is_done()` sees an outdated `BENCHMARK_VERSION` or `status == "failed"`. `get_battery_benchmark` returns stored records plus `summarize()`; `CommandDomains.tsx` lists non-scored days with `BENCHMARK_REASONS` text and shows capacity values for `capacity_mismatch`.

Evidence from the user's diagnostics bundle (64 kWh configured):
- Meter-derived battery in/out 119/91 kWh vs inverter battery sensors 116/94 kWh over 5 days: flows are good.
- Clean overnight discharge: 5.7 kWh for 9.2 pp -> ~62 kWh. Battery really is ~64 kWh.
- SoC moves in ~1.15 pp steps, changing only every 3-4 slots at ~0.2 kWh/slot.
- Per-slot filter keeps only the step slot's ~0.2 kWh for a 1.15 pp step and drops the 2-3 slots that built it up: reports 21-35 kWh.
- Per-day net energy / net SoC change: 36-117 kWh. Energy accumulated between SoC changes: 24-67 kWh.

## Goals / Non-Goals

**Goals:**
- A capacity mismatch never excludes a day; it becomes an advisory warning.
- Estimate is unbiased by SoC quantisation for large/slow batteries.
- Existing installs recover the last 14 days automatically.

- Hindsight shows data with a simple note instead of silently dropping or failing days where the data is usable (decisions 6-9).

**Non-Goals:**
- Changing exclusion reasons other than those in decisions 6-9.
- Auto-correcting configured capacity.
- Recovering days older than the 14-day window (their stored v1 records stay excluded).

## Decisions

1. **Warning, not exclusion.** Records gain `warnings: list[str]` (empty by default in `base_record`) and the day continues to the stock check and solve. `reason` stays reserved for blocking outcomes, so `summarize()`'s `by_reason` and the "not scored" list keep their meaning. `summarize()` adds `by_warning` counts. Alternative considered: a new status `scored_with_warning` - rejected, it would break every consumer counting `status == "scored"`.

2. **Window regression estimate.** Over the eligible history window (the day plus up to 6 earlier eligible days, ~7 days), compute per-slot stored energy from meter net flow (net = import - export + pv - load - water - ev; stored = net x eta_c if net > 0 else net / eta_d), accumulate it across the window (cumulative stock, continuing across day boundaries), and fit it by least squares against SoC % over ALL slots. implied capacity = slope x 100. No per-slot threshold or direction filter.
   - Why: SoC is quantised (~1.15 pp steps, also 2.3/3.4 pp jumps) and jitters (38 of 459 SoC changes on the user's data go against the energy direction). A regression averages both out; any method summing |delta SoC| counts jitter as movement.
   - Verified on the user's real data (64 kWh): regression over 7-day windows gives 55-62 kWh on every window (worst 55.3 kWh = 13.6 % off). Single-day regression is noisy (40-94 kWh), hence the ~7-day window.
   - Rejected: per-slot filtering (current; 21-35 kWh); sum |stored| / sum |delta SoC| over the window (34-42 kWh, jitter inflates movement); per-day net energy / net SoC (36-117 kWh); energy accumulated between SoC changes (24-67 kWh).
   - The user's BMS also exposes a finer "emulator SoC" sensor. The method must not depend on it; pointing users at a finer SoC sensor is optional advice only.

3. **Thresholds.** `CAPACITY_TOLERANCE` 0.15 -> 0.20: the worst real window is 13.6 % off, so 15 % is too tight, while 20 % still flags a clearly wrong config (e.g. 64 vs 40 kWh = 60 %). Movement guard becomes SoC range (max - min SoC within the window) >= 20 pp, replacing summed movement (`CAPACITY_MIN_MOVEMENT_PP`), because summed movement is jitter-inflated while range is not, and the regression slope is only determined when SoC spans a meaningful range. Range is chosen over variance because it is easy to explain and test. `CAPACITY_MIN_SLOT_DELTA_PP` is removed. The warning stays advisory and never excludes.

4. **Version bump.** `BENCHMARK_VERSION` 1 -> 2. `_is_done()` then treats every v1 record as pending, so `run_once()` re-scores all days in `WINDOW_DAYS` (14) on the next startup or nightly run. History load (`HISTORY_DAYS` = 14 before oldest pending) already covers the capacity window. Days older than 14 days are not re-scored; the API will still return their v1 `capacity_mismatch` records, and the UI keeps rendering them as not scored.

5. **UI.** In the hindsight ⓘ panel, scored days with a `capacity_mismatch` warning appear in a separate small "Warnings" list (e.g. "2026-10-12 battery capacity may not match recorded flows (recorded 31.0 kWh, configured 64.0 kWh)") using existing muted/warn text tokens per `docs/design-system/AI_GUIDELINES.md` - no error colour, no blocking. The row also shows a short warning marker when any day in range has warnings. Legacy v1 `capacity_mismatch` reason keeps its current "not scored" rendering. `api.ts` validation must accept a missing `warnings` (legacy records) as `[]`. The Warnings list covers every warning code on scored days, one line per warning: `capacity_mismatch` as above, `unverified_slots` as "N of M slots not verified", `stock_clamped` as "stored energy outside battery capacity, clamped". Missing `unverified_slots`/`day_slots`/`stored_change_kwh` fields default to 0/null in `api.ts`.

6. **EV charging threshold (20 W slot average).** `no_discharge_slots` used `ev_charging_kwh > EV_ACTIVE_KWH` (1e-6 kWh). Evidence (Torleif): his EV sensor idles at ~0.3 W (7.5e-05 kWh per 15-min slot) in 55-93 slots per day, so hindsight forbade battery discharge almost all day and Kepler was Infeasible on net-discharge days (Oct 8, 13, 15, 16 -> status `failed`). With a ~40 W threshold every one of those days solves. Decision: a slot counts as EV charging only when its average EV power, `ev_charging_kwh / slot_hours`, exceeds `EV_CHARGING_MIN_KW = 0.02` (20 W). Expressing it as power keeps it correct for any slot length (DST, non-15-min slots). Rationale: values are slot averages; 20 W over a slot at 8 kW charging is ~2 s of real charging, while real ramps are hundreds of W or more, so nothing real is lost. EV energy below the threshold still counts as demand in pricing.

7. **"Battery ended fuller" note.** A day where the battery ends with more stored energy than it started (grid-charged for the next day) has negative `value_ideal_sek`, so `score` is None by design (`MIN_IDEAL_VALUE_SEK`), and the UI showed only "missed kr" with no explanation. Over 7d/30d this washes out in totals; it is mainly visible on "Yesterday". Decision: records gain `stored_change_kwh` = modelled terminal - initial stored energy (after clamping, i.e. what the hindsight plan had to match); `summarize()` adds `stored_change_kwh` summed over scored days (legacy records without the field count as 0). The card keeps showing the kr values; when the period has scored days, its score is None and the summed change is positive, the row shows a muted note "Battery ended X kWh fuller than it started; that value shows up the next day". A percentage is never fabricated.

8. **Tolerate a few unverified slots.** A day was excluded as `not_clean_recording` if ANY slot (including the previous day's last slot used for start SoC) had no usable recording (`slot_recording()` None: missing provenance or non-live SoC) or there were more than `MAX_SNAPSHOT_SLOTS` (2) snapshot slots. Evidence (Torleif): Oct 11 had 95 clean slots and 1 slot with no recording info -> whole day skipped; Oct 12 had 3 bad slots (2 with SoC source `cached`, 1 with no info). Decision: count unverified slots = slots whose recording is None or snapshot, over the day's slots plus the start-SoC slot. The start-SoC slot counts toward the limit because its SoC sets the initial stock; an unverified start is exactly as uncertain as an unverified day slot. Up to `MAX_UNVERIFIED_SLOTS = 4` (1 hour) the day is scored with an `unverified_slots` warning and the count in `unverified_slots` (plus `day_slots`, the number of the day's slots, for display: "3 of 96 slots not verified"). More than 4 stays `not_clean_recording`. Values must still be finite (`missing_values` still blocks). Days with no recording info at all (older versions, e.g. his before Oct 7) have far more than 4 unverified slots and stay excluded. `MAX_SNAPSHOT_SLOTS` is removed (snapshot slots are now part of the unverified count); `snapshot_slots` keeps being stored. Clean days carry no warning, as before; 1-2 snapshot slots, previously silent, now get the warning, which is more honest and harmless.

9. **Clamp stock instead of `stock_out_of_range`.** The day was excluded when initial or modelled terminal stored energy was outside [0, capacity] (flow drift or capacity config on large batteries). Decision: clamp both to [0, capacity], score the day and add a `stock_clamped` warning. Feasibility: Kepler's benchmark SoC variable is bounded by [0, capacity] and the benchmark bounds already widen min/max SoC to include both ends, so clamped ends are always inside the bounds; clamping is 1-Lipschitz, so the required net change never grows beyond what the recorded day did. If Kepler still cannot solve, the existing path stores `failed` / `solver_not_optimal` (no crash) and the day is retried. `stock_out_of_range` stays in the UI reason map for legacy records.

10. **Recording gap slots count as unverified, not `missing_values`.** Evidence (Torleif): with decision 8 implemented, 2026-10-11 was still excluded, now as `missing_values`. It has 95 clean slots and one gap slot at 15:30 where Darkstar recorded nothing: `quality_flags` NULL, import/export/pv/load/water/ev = 0.0, `batt_charge/discharge_kwh` NULL, `soc_start/soc_end_percent` NULL, prices present. The NULL `soc_end_percent` failed the finite check although the slot was within `MAX_UNVERIFIED_SLOTS`. Decision: a day slot with missing (or non-finite) energy values and/or SoC, but finite prices, is a gap slot and counts as one unverified slot toward the same limit of 4 (together with missing-provenance and snapshot slots; a slot is counted once). The day is scored with the existing `unverified_slots` warning and count. Missing energy values in a gap slot are treated as 0 kWh (no recorded flow) for actual, hindsight and no-battery alike, so all sides see identical inputs; a missing SoC is skipped in the capacity fit (stored energy still accumulates across it). Missing or non-finite import/export price in any day slot still excludes the day as `missing_values` (cost cannot be computed). The start-SoC slot (previous day's last slot) must have a finite `soc_end_percent` to set the initial stock; otherwise the day stays `missing_values`. Fallback considered: `battery_comparison.py` uses the first slot's `soc_start_percent`, but the gap pattern leaves that NULL too and it would need its own provenance check, so it is not equally simple and robust; we keep blocking. Days from older Darkstar versions with no recording provenance at all stay excluded as `not_clean_recording` (user decision; they age out of the 14-day window). `BENCHMARK_VERSION` stays 2: no v2 records have been released, and the re-score on upgrade already covers the window.

### Review of exclusion reasons
| Reason | Blocking? | Notes |
|---|---|---|
| `not_finished` | Yes | Day not over. |
| `incomplete_day` | Yes | Missing slots or no previous-day start SoC; cannot price the day. |
| `not_clean_recording` | Only above 4 unverified slots | Decision 8; up to 4 becomes the `unverified_slots` warning. |
| `missing_values` | Yes, for prices and start SoC | Missing/non-finite price or start-SoC slot SoC; cost or initial stock cannot be computed. Missing energy/SoC in a day slot is a gap slot (decision 10). |
| `stock_out_of_range` | No longer produced | Decision 9; becomes the `stock_clamped` warning. Legacy records still render. |
| `solver_not_optimal` | Yes (status failed, retried) | No valid hindsight plan. EV idle noise no longer causes it (decision 6). |

## Risks / Trade-offs

- [Wrongly configured capacity now silently skews scores] -> warning is shown in the panel with both values; spec still forbids auto-changing config.
- [Re-scoring 14 days on startup costs 14 solves] -> already bounded and off the event loop; one-time.
- [Regression still noisy on short or flat windows] -> ~7-day window, 20 pp range guard, advisory only.
- [Scoring days with up to 4 unverified slots or clamped stock adds some error] -> bounded (1 hour of slots; clamp only shrinks the required change) and always shown as a warning with the count.
- [20 W EV threshold could miss a real trickle charge] -> 20 W average is ~2 s of real charging per slot; such a slot still prices the EV energy as demand.
- [Older-than-14-day days remain excluded] -> documented; they age out of the default 30-day view within ~16 days.

## Impact Analysis

- Hindsight scoring itself is correct when configured capacity is right: flows come from the meters, and SoC is only used for the start stock (+-1.15 pp ~ 0.7 kWh on 64 kWh).
- Nothing else live derives capacity from SoC deltas: planner, schedule chart and monitors use SoC as a value.
- `fit_calibration` / `_battery_pairs` in `backend/battery_comparison.py` have no live callers (retired path). Out of scope; dead-code removal follow-up.

## Migration Plan

Deploy; the next startup run re-scores the window. Rollback: reverting code with version 1 would treat v2 records as outdated and re-score them under old rules - acceptable.

## Open Questions

- Exact thresholds (20 %, 20 pp range) may be tuned after seeing warning rates across users; does not change approach or tasks.
