## Context

`planner/solver/kepler.py` models each water heater with binary `water_heat[t]`, binary `water_start[t]`, `discomfort`/`gap_over` (cumulative gap penalty with a deadband), `block_overshoot` window rows (windows of cap+1 slots) and a big-M spacing row. The LP relaxation of these is very weak: it heats ~17 % in every slot, so CBC cannot close the bound and hits the time limit on almost every prod solve. Prototype: `~/.cache/darkstar-flow-prototype/kepler_flow.py` (functions `_flow_plan` and `_build_flow`; scratch hooks FIX_WATER, SOLVER_LOG, LAST, FLOW_LOG, a GLPK bypass and a debug-LP path must NOT be carried over) and its README.

## Goals / Non-Goals

**Goals:** identical water semantics with a formulation CBC can prove optimal quickly; no behavioural regressions in the full objective.
**Non-Goals:** new config keys, UI, DB, dependencies, other solvers, changes to EV/battery modelling, changing penalty semantics.

## Decisions

### 1. Exact state-expanded arc-flow DAG per heater
Unit flow traverses the slots. Per slot t:
- Off-states `F(t,k)`: k = slots since last heat, k = 1..t (uncapped while the gap rule is active, because the gap penalty is cumulative: each off slot costs `gap_penalty * (hours since last heat - max_hours_between_heating)` when positive, so states cannot be merged). When the gap rule is off, k saturates at `max(S,1)`.
- Never-heated state `N(t)`: off since plan start (gap counter starts at 0 at the horizon start, so its cost is exact from cumulative hours).
- On-states `O(t,l)`: block length l = 1..cap, plus an absorbing over-cap state l = cap+1 that costs the overshoot penalty per slot (only when overshoot is priced by flow); otherwise a single on-state.
- Arcs: off->off (gap cost), off->on only from `N` or `F(k >= S)` carrying the block-start cost, on->on (over-cap cost on entering/staying in the over-cap state), on->`F(1)` (gap cost for one off slot), source -> `N(0)` or `O(0,1)`.
- Flow conservation: unit flow per slot. `water_heat[t]` is binary and equals the total flow into on-states; arc flows are continuous in [0,1]. The existing `1e-5 * t * water_heat[t]` symmetry term stays on `water_heat`, which equals the on-state inflow. Per-slot hours (shortened first slot, DST) are used for gap hours.
- Spacing S = `max(1, int(min_spacing_h / avg_slot_h))` if spacing > 0 else 0; a start at t needs the previous S slots off, with the window truncated at plan start (a never-heated start is always allowed).
- A heater needs flow only if S > 0, a start penalty > 0, the gap rule is active, or overshoot is priced by flow. Bulk mode (S = 0, gap off, no block penalty) reduces to a 2-3 state start-penalty-only graph, as fast as before.

Why exact: arc-flow integrality means the LP relaxation is tight for the water rules, so the bound is close to the incumbent and CBC proves optimality.

### 2. Rules that stay on water_heat
Daily min kWh with its reliability penalty, boost, `force_on_slots` (mid-block locking) and `heated_today` act on `water_heat[t]` as today. `heated_today` does not feed the gap or spacing counters (unchanged initial-state semantics).

### 3. Overshoot when spacing < cap
Per-window overshoot (sum over cap+1 slots) equals per-slot overshoot (L - cap)+ per block only when no window can hold two blocks, i.e. spacing >= cap. When S < cap (or S = 0) the flow graph omits the over-cap state and the existing `block_overshoot` window rows are kept for that heater. This path is implemented from the old code but was not exercised in the prod replays, so equivalence tests cover it explicitly.

### 4. Dead code
The old start/spacing/discomfort/gap_over rows and variables are removed. Only the block-overshoot rows remain, for the spacing < cap path. Result extraction and debug/test code that read `water_start`, `discomfort`, `gap_over` or `block_overshoot` by name read equivalent values from the flow (starts = flow on the off->on arcs).

### 5. Rejected alternatives
- Gap tolerance (`gapRel` 0.1-4 %): does not help, bound stalls.
- Longer time limit: already raised to 240 s without closing the gap; slow for the user.
- Rounded-relaxation warm start: gained only a few SEK.
- HiGHS: worse than CBC at 90 s, effectively single-threaded.
- Tighter big-M, Rajan-Takriti spacing, start cover cuts: gap only 4.9 % -> 2.7 %.
- Dense window rows: far worse.
- Block start-time formulation (binary per block start/length plus y-based gap-cover cuts): exact under spacing >= cap, gap 4.5 % -> 1.45 % on 129 slots, still not proven in 90 s.
- Window rule, hourly water decisions: change semantics or lose accuracy.
- Relax-and-round heuristic: not exact, no guarantee.
- Schedule library with column generation: same plans in ~20 s but heuristic, needed tuning and relies on a pruning assumption.

## Risks / Trade-offs

- Model size: ~30k continuous variables and ~19k rows at 168 slots (vs ~4k). CBC root LP ~1-2 s. Solve time grows with horizon (96 slots 15 s, 120 slots 30 s on the slowest plan; worst replay 67 s). Mitigation: stays under the 90 s limit on all replays; the limit and `time_limit_hit` handling are unchanged.
- Plans can differ from old incumbents. Mitigation: full objective never worse in replays; real cost may rise up to ~1.7 SEK where the optimum prefers comfort/fewer starts.
- Spacing < cap path unvalidated by replays. Mitigation: equivalence tests with fixed patterns.
- Equivalence risk. Mitigation: tests compare flow water penalty against the old formulation for fixed heat patterns across the configurations listed in tasks.
