# Tasks: EV Fractional Planning and Quota Floor

## 1. Solver input plumbing (min power)

- [x] 1.1 Add `min_power_kw: float = 0.0` field to `EVChargerInput` in `planner/solver/types.py`
- [x] 1.2 In `planner/solver/adapter.py`, compute `min_power_kw` for `type: current` chargers as `min_current_a × 230 × phase_count / 1000 × 1.01` (1% margin per design D2), reading `min_current_a` (default 6) and the charger's configured phase count (default 3) from the charger config; leave `min_power_kw = max_power_kw` for `type: binary` chargers
- [x] 1.3 Unit tests for the adapter derivation: 3-phase 6A → ~4.18 kW with margin, 1-phase 6A → ~1.39 kW, binary charger → equals `max_power_kw`, missing `min_current_a` → default 6 used

## 2. Semi-continuous EV planning in Kepler

- [x] 2.1 In `planner/solver/kepler.py`, replace the equality energy link (`ev_energy == ev_charge × max_power_kw × h`, line ~419) with control-type-dependent constraints: equality for `type: binary`; `min_power_kw × h × ev_charge <= ev_energy <= max_power_kw × h × ev_charge` for `type: current`
- [x] 2.2 Confirm (and cover with an assertion in tests) that all `ev_charge`-gated constraints still bind for fractional slots: `any_ev_charging` / discharge blocking, surplus-charging exclusivity (`kepler.py:399`), deadline zeroing, per-day quota `<=`, import limit
- [x] 2.3 Solver test: current-type charger with a small requirement across cheap slots gets fractional power ≥ `min_power_kw` and total energy meets the requirement (spec scenario "Current-type charger is planned at fractional power")
- [x] 2.4 Solver test: any nonzero planned slot power for a current-type charger converts via `planned_kw_to_amps` to an amp value ≥ `min_current_a` (spec scenario "never planned below its minimum amps")
- [x] 2.5 Solver test: binary charger slots remain exactly `max_power_kw × h` (spec scenario "Binary charger keeps full-power-or-off planning"), and a fractional-charging slot still blocks battery discharge

## 3. Chunk-aware multi-day quota

- [x] 3.1 Add optional `min_chunk_kwh: float = 0.0` parameter to `MultiDayPlanner.compute_quota` in `planner/strategy/multi_day_planner.py`; implement the final normalization pass per design D3: zero out nonzero days below one chunk and redistribute their energy to the cheapest day(s) with capacity that meet the chunk, preserving the total and respecting per-day caps
- [x] 3.2 Implement the sub-chunk-goal floor: when `0 < remaining_kwh < min_chunk_kwh`, allocate exactly `min_chunk_kwh` to the cheapest day with capacity (design D4)
- [x] 3.3 In `planner/pipeline.py` `_compute_daily_ev_quota`, compute and pass `min_chunk_kwh` per charger: `min_power_kw × slot_h` for `type: current`, `max_power_kw × slot_h` for `type: binary` (reuse the adapter's derived min power, don't re-derive)
- [x] 3.4 Unit tests for `compute_quota`: (a) the observed bug — 2.6 kWh over 2 days with chunk 2.425 lands entirely on one day; (b) allocations already ≥ chunk are unchanged; (c) `min_chunk_kwh=0` is byte-identical to current behavior; (d) sub-chunk goal (0.3 kWh, chunk 1.05) yields exactly one day at 1.05 and total ≤ one chunk; (e) redistribution never exceeds a day's capacity cap

## 4. Zero-scheduled warning

- [x] 4.1 In `planner/pipeline.py`, after the solve, log a WARNING for any charger with `required_kwh > 0` and a resolved deadline whose total scheduled energy is 0 — include charger ID, required kWh, quota-by-day split, and min chunk kWh
- [x] 4.2 Test: infeasible-goal setup produces the WARNING; a normally scheduled goal produces no WARNING

## 5. End-to-end regression and verification

- [x] 5.1 End-to-end regression test reproducing the 2026-07-17 incident: current-type 9.7 kW charger (2.425 kWh binary chunk), required_kwh=2.6, deadline next day, multi-day spreading active → schedule contains nonzero EV charging and total scheduled energy ≥ 2.6 kWh
- [x] 5.2 Run the full test suite (planner + executor + frontend build) and fix any regressions
- [x] 5.3 Visual verification per backlog rule: check the Dashboard, Executor, and schedule chart pages render fractional EV kW values sensibly (shared chart/output code touched)
