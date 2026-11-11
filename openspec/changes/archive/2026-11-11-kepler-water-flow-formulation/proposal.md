# Proposal

## Why

Almost every prod solve stops at the solver time limit instead of proving optimality. Investigation (replays of prod archives) showed the water heater is the whole cause: with the water heater removed or `water_heat` relaxed the model proves optimal in 2-8 s. The LP relaxation runs each heater at ~17 % in every slot and meets the daily minimum with almost no start or comfort cost, so the start, spacing, gap and block-overshoot rows give a very weak bound (gap stalls 3-5 % below the plan). Incumbents are then up to ~8 SEK above a known better plan. Tighter big-M values, Rajan-Takriti spacing, cover cuts, warm starts, a gap tolerance and HiGHS were tried and rejected (see design.md). An exact state-expanded arc-flow formulation of the same rules closes the gap.

## What Changes

- Replace the per-heater `water_start`, `discomfort`, `gap_over` and `block_overshoot` variables and their spacing, gap and block rows in `planner/solver/kepler.py` with an exact arc-flow DAG per heater (off-counter states, on block-length states with an over-cap state, never-heated start state). `water_heat[t]` stays binary and equals the flow into on-states; arc flows are continuous.
- Arc costs reproduce the existing penalties exactly: cumulative gap penalty, block start penalty and block overshoot penalty; the `1e-5 * t` symmetry term stays on `water_heat`. Per-slot hours are used (shortened first slot, DST).
- Daily minimum kWh, reliability penalty, boost, `force_on_slots` and `heated_today` keep acting on `water_heat` unchanged. Initial-state semantics are unchanged.
- When a heater's spacing is below its block cap (or spacing is 0), keep the existing block-overshoot window rows for that heater, since per-window and per-slot overshoot are only equal when spacing >= block cap.
- Bulk mode (`enable_top_ups: false`) keeps working: the graph reduces to a start-penalty-only DAG.
- Result extraction and any debug output or tests that read the old variables by name read equivalent values from the flow (starts = flow on off-to-on arcs).
- Delete the backlog item "[Planner] Tighten EV/Water Solver Model (PRIORITY 1)" from `docs/BACKLOG.md` (done by this change's creation per backlog workflow).
- No new dependencies, config keys, DB schema changes or UI changes. Solver stays CBC with threads and the 90 s default limit.

Evidence (read-only replays, CBC 4 threads, 90 s):
- Prod, 17 new plans: current model hit the limit on 15 (median 90.5 s); flow model proven optimal on all 17, median 24 s, worst 67 s. Full objective better on 14, equal on 3, never worse (median -3.05 SEK). Real cost excluding penalties: median -0.25 SEK, up to +1.7 SEK on 5 plans where the optimum trades cost for comfort or fewer starts.
- Torleif faithful config (bulk mode, 3 plans): identical plans, ~6 s vs ~4 s. Torleif with comfort rules on (3 plans): current hit the limit on all, flow 30 s median, proven optimal, cheaper.
- Earlier 6-plan run: flow median 27 s vs current 90 s (all limit hits).
- All flow plans re-validated by fixing the water pattern in the original model: feasible, objective match < 1e-6, spacing, force_on and boost honoured. Covered: EV deadline beyond horizon, `heated_today > 0`, force_on slots, boost with synthetic surplus PV. Not exercised: the spacing < cap path.
- Known cost: ~30k continuous variables at 168 slots (vs ~4k); solve time grows with horizon (96 slots 15 s, 120 slots 30 s on the slowest plan).

## Capabilities

### New Capabilities

### Modified Capabilities
- `per-device-water-scheduling`: block duration, spacing, block start penalty and gap-comfort requirements are restated in terms of the exact flow formulation (same economic behaviour, different model structure); new requirement that the water model is exact and equivalent to the previous penalties.

## Impact

- Code: `planner/solver/kepler.py` (water variables, constraints, objective, result extraction); possibly `scripts/profile_solver_spacing.py` and `tests/planner/test_water_gap_comfort.py` which read the old variable names; new tests under `tests/planner/`.
- Behaviour: plans may differ slightly from the old model where the old model stopped at the limit with a suboptimal incumbent; the full objective is never worse. Real cost can rise by up to ~1.7 SEK on some plans where comfort or fewer starts is cheaper overall.
- Performance: solves proven optimal in a median ~24 s instead of hitting the 90 s limit; `time_limit_hit` becomes rare.
- `docs/BACKLOG.md`: item removed. No `docs/RELEASE_NOTES.md` or `config.yaml` changes.
