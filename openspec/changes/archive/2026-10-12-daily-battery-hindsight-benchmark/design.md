## Context

Evidence: 2026-10-11 investigation on a read-only production copy (scripts in the session scratchpad, not committed). Key facts it established:

- Recorder battery flows were undercounted until v2.7.0 (fix 5afd5aa3). Rows from 2026-06-13 to 2026-10-07 all carry `{"source": "recorder"}` whether clean or not, so date-free eligibility is only possible from the power-history recording (453e1095), which writes `quality_flags.recording.components.<name>.method` per value (prod: from 2026-10-07 21:30).
- Pricing actual and ideal with the same model makes the score robust: methods agreed within ~4 SEK/day; calibrated 34.2 kWh / 0.92 / 0.95 reproduced measured SoC with 2.8 % daily RMSE on held-out days.
- Physical refinements (measured power caps, charge taper, 8 kW AC limit for grid charging, forbidding partial discharge) changed missed value by 1.7 SEK over 22 days. They are left out.
- Configured capacity can be wrong for months (prod had 27 kWh vs ~34.2 real) and real capacity can change (one of three modules disconnected ≈ 2026-08-24..09-20, implied 17–20 kWh). Using it blindly inflated September's missed value by ~100 SEK.

## Decisions

### 1. One day, one solve, same model on both sides

Horizon: the local day's contiguous 15-minute slots (92/96/100 on DST days). Inputs per slot: demand = `load_kwh + water_kwh + ev_charging_kwh` (fixed timing), `pv_kwh`, recorded import/export prices. Start stored energy = previous slot's `soc_end_percent` × capacity.

Actual battery flow per slot is derived from the meter balance: `net = import - export + pv - load - water - ev`, positive → charge, negative → discharge. End stored energy = start + Σ(charge × η_c − discharge / η_d). The hindsight solve must end at exactly that value, so both sides finish with the same model inventory.

Cost of a schedule = Σ per slot `max(net_grid,0) × import_price − max(−net_grid,0) × export_price` + wear `(charge + discharge) × wear_cost / 2`, where `net_grid = demand − pv + charge − discharge`. Applied identically to actual, ideal and no-battery (charge = discharge = 0, no wear).

`missed_sek = actual_cost − ideal_cost`; `value_actual = no_battery_cost − actual_cost`; `value_ideal = no_battery_cost − ideal_cost`; `score = value_actual / value_ideal` only when `value_ideal ≥ 1 SEK`, else null.

### 2. Kepler benchmark mode

Add an explicit benchmark option to Kepler rather than patching the problem from outside. In benchmark mode: ramping cost, curtailment penalty, export threshold, target-SoC and S-index terms are zero; curtailment fixed at 0; load shedding and SoC/export-floor violation slacks fixed at 0; terminal SoC equality; no simultaneous charge/discharge (binary); discharge = 0 in slots with EV charging; SoC floor = min(configured min, start, end) so a day that legitimately started below the floor stays feasible. Everything else (power limits from config, AC inverter limit, export floor, grid limits) is the live model. Live calls never set the option.

Solver must report proven optimal; time-limited or infeasible → day stored as `failed` with the status.

### 3. Eligibility (no dates, no versions)

A day is scored only if:
- all slots exist, are contiguous, and are past (slot end ≤ now; today and future placeholder rows are never used);
- every slot has `quality_flags.recording.components` and `recording.soc.end.source == "live"`, with methods only in {`power_history`, `derived_history`, `disabled_zero`}, except at most 2 slots per day with `snapshot` fallback (prod: ~1 in 300 slots); the count is stored with the result;
- the previous slot (start SoC) satisfies the same;
- all required numbers are finite; prices present;
- the capacity check (4) passes;
- start and end stored energy lie within [0, capacity].

Otherwise the day is stored as `excluded` with the first failing reason. Users therefore start getting scores from the day they run a build with power-history recording.

### 4. Capacity check

Implied capacity = Σ(charge × η_c − discharge / η_d) / ΔSoC over the scored day plus the previous 6 eligible days, using only slots with |ΔSoC| ≥ 1 pp in the battery's direction. If |implied − configured| / configured > 15 % with at least 20 pp of total SoC movement, the day is `excluded` (`capacity_mismatch`, both values stored). Insufficient movement → check skipped and noted. The benchmark always uses the configured capacity; it never auto-corrects.

### 5. Execution and storage

A `BenchmarkService` in `backend/services/` started from `backend/main.py` lifespan like the others. At 00:10 local, and once after startup, it processes every not-yet-stored day in the last 14 days, oldest first, one at a time, each solve in a thread via `asyncio.to_thread` with Kepler's 60 s limit. A day is computed once; stored `scored`/`excluded` results are not recomputed unless the benchmark version changes. Days stored as `failed` (any reason, including `error` and solver failures) are retried on every run while inside the window.

Result per day in `system_state` key `battery_benchmark:<YYYY-MM-DD>`: JSON with `version`, `status` (`scored`/`excluded`/`failed`), `reason`, costs, missed, score, capacity used and implied, solve seconds. Bumping `version` makes old results be recomputed by the next run (within the 14-day window).

### 6. API and UI

`GET /api/energy/battery-benchmark?start_date&end_date` (inclusive local dates, default last 30 finished days, max 366): per-day records plus totals over scored days: `missed_sek`, `value_actual`, `value_ideal`, `score = Σvalue_actual / Σvalue_ideal` (null if Σvalue_ideal < 1), counts by status and reason. Reads only stored results.

No new card. The existing Grid & Financial card in `frontend/src/components/CommandDomains.tsx` gains, directly under the "DS vs grid-only" row and in the same style (label, amount, coverage note, ⓘ details popover):

`DS vs hindsight  −123.40 kr · 81% · 22/25 days  ⓘ`

The ⓘ popover explains the method in one paragraph and lists excluded days with reasons. Hidden for the Today view (no finished day); Yesterday/7d/30d/Custom use the selected range. When nothing in the range is scored, the row shows the reason instead of an amount.

Chart (`CostSeriesChart.tsx`): add a third cumulative line "Hindsight" (gold dashed, design-system token) below the DS line, with the area between DS and Hindsight shaded the same way as the existing grid-only/DS area. Points are day ends: `hindsight_cum(day_end) = DS_cum(day_end) − Σ missed of scored days so far`, so the gold gap equals cumulative missed value and the line stays aligned with DS regardless of the DS line's own bill basis. Excluded days add 0 and are marked in the line (gap, like existing segments). In hourly views (Today/Yesterday) the line is not drawn. Legend gains "Hindsight". The geometry helper and its tests are extended; the existing grid-only line and area are unchanged.

The cost-series endpoint is not changed; the frontend fetches the benchmark endpoint for the same range and merges by date.

## Risks

- Fewer eligible days if snapshot fallbacks are frequent on some installs; the exclusion reason makes that visible.
- Default efficiencies are wrong for some installs → slightly wrong optimum; both sides share it, so the effect on missed value is small (measured ±0.2 SEK/day).
- Hindsight knows the day's load and PV perfectly, so no planner can reach 100 %.

## Decisions Log

- Up to 2 snapshot-fallback slots per day are accepted (user, 2026-10-11).
- Capacity tolerance stays at 15 % (user, 2026-10-12).
- Negative scores are shown as-is, always alongside missed kr (user, 2026-10-12).
- Failed days are retried on each run inside the 14-day window, not only on version bump (user, 2026-10-12).
- Implementation choices: benchmark mode disables water/EV/excess-PV devices (their energy is already in recorded demand); SoC max is raised to max(configured, start, end); the soft grid-import slack is kept; excluded days are drawn as a faint grey band on the chart; the ⓘ popover shows implied vs configured capacity for `capacity_mismatch`.
- The overlapping backlog item `[Learning] Automatic Daily Replay` is removed; this change replaces it.
