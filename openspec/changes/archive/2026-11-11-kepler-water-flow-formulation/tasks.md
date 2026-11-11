## 1. Formulation

- [x] 1.1 In `planner/solver/kepler.py`, add a helper that builds the per-heater flow DAG (states, arcs, costs, conservation) from heater inputs, per-slot hours, spacing slots, block cap, gap deadband and penalties, using the reference prototype `~/.cache/darkstar-flow-prototype/kepler_flow.py` and its `README.md`; no FIX_WATER/SOLVER_LOG/LAST/FLOW_LOG/GLPK-bypass/debug-LP hooks from the prototype
- [x] 1.2 Define `water_heat[d][t]` as binary equal to total flow into on-states; arc flows continuous in [0,1]; keep the `1e-5 * t` symmetry term on `water_heat` (equal to the on-state inflow, so identical to carrying it on the arcs)
- [x] 1.3 Decide per heater whether flow is needed (spacing > 0, start penalty > 0, gap rule active, or overshoot priced by flow); bulk mode builds the start-penalty-only graph
- [x] 1.4 Use the over-cap state for overshoot when spacing >= block cap; otherwise keep the existing `block_overshoot` window rows for that heater
- [x] 1.5 Remove the old `water_start`, `discomfort`, `gap_over` variables and the spacing/gap rows; keep only what the spacing < cap overshoot path needs
- [x] 1.6 Leave daily min kWh, reliability penalty, boost, `force_on_slots` and `heated_today` acting on `water_heat`; keep initial-state semantics

## 2. Readers of the old variables

- [x] 2.1 Update result extraction and any debug output in `kepler.py` to read starts from flow on off-to-on arcs
- [x] 2.2 Update `scripts/profile_solver_spacing.py` and `tests/planner/test_water_gap_comfort.py` which reference the old variable names
- [x] 2.3 Grep the repo (excluding `.venv`, bundles, archive) for `water_start`, `discomfort`, `gap_over`, `block_overshoot`

## 3. Tests

- [x] 3.1 Equivalence tests: for fixed heat patterns the flow water penalty equals the old formulation's, across spacing >= cap, spacing < cap, spacing 0, gap rule on/off, bulk mode, shortened first slot, `heated_today`, force_on and boost
- [x] 3.2 Tests for exact semantics: cumulative gap cost, start penalty, over-cap penalty, spacing truncated at slot 0, never-heated start allowed
- [x] 3.3 Unit test that `time_limit_hit` and per-heater result extraction still work with the flow formulation
- [x] 3.4 Regression: existing planner and water tests pass (`UV_NO_SYNC=1 uv run python -m pytest tests/planner -v`)
- [x] 3.5 Check a bulk-mode plan equals the previous plan and a comfort-rules plan solves proven optimal within the limit
- [x] 3.6 Add a test fixture that exercises the spacing < block cap path end to end (plan solves, overshoot priced by window rows, penalty equals the old formulation)

## 4. Final checks

- [x] 4.1 Run `./scripts/lint.sh`
- [x] 4.2 Run the full pytest suite and the frontend tests once
