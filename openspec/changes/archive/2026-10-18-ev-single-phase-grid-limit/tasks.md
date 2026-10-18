# Tasks

## 1. Plumbing

- [x] 1.1 Add `max_phase_import_kw: float | None = None` to `KeplerConfig` and `phases: tuple[int, ...] = (1, 2, 3)` to `EVChargerInput` in `planner/solver/types.py`. Verify: existing planner tests still construct both without change.
- [x] 1.2 In `planner/solver/adapter.py`, set `max_phase_import_kw = main_fuse_a * (load_balancing.target_margin_percent / 100) * nominal_voltage_v(planner_config) / 1000` when `system.grid.main_fuse_a` is a positive number, else `None`. `target_margin_percent` defaults to 85 when unset or invalid (shipped default 85, range 50-100). Verify: unit test for set, unset, zero, non-numeric fuse, default margin, custom margin (e.g. 100), invalid margin.
- [x] 1.3 In `build_ev_charger_inputs`, set `phases` for `type: current` chargers (filter to {1,2,3}, dedupe, fallback (1,2,3) with a warning); binary chargers keep the default. Verify: unit test for `[1]`, `[1,2]`, `[1,2,3]`, invalid, binary.

## 2. Solver

- [x] 2.1 In `planner/solver/kepler.py` after the `max_import_power_kw` cap (~595), add the per-line constraint from design.md (skip when `benchmark` is set, `max_phase_import_kw` is None, or no plugged charger has fewer than 3 phases). Include `ev_surplus_kw` and the partial first slot handling (D2). Verify: solves feasibly in all tests below.

## 3. Tests (tests/planner/test_kepler_ev_phase_limit.py)

- [x] 3.1 1-phase EV, fuse 20 A / 230 V / default 85% margin, cheap window making battery grid charge and EV both attractive: assert every slot satisfies EV kW + (net import kW - EV kW)/3 <= 3.91 (20 x 0.85 x 230 / 1000) and total EV delivered is below the unconstrained plan. Verify: fails without the constraint.
- [x] 3.2 3-phase EV (`phases (1,2,3)`): plan equals the plan with `max_phase_import_kw=None`.
- [x] 3.3 `max_phase_import_kw=None`: plan equals today's plan.
- [x] 3.4 House load alone above the limit: solver returns a plan (load shedding or EV 0), no infeasibility.
- [x] 3.5 Two chargers on different lines (L1, L2): each line satisfied independently.
- [x] 3.6 Adapter tests from 1.2 and 1.3.

## 4. Checks

- [x] 4.1 Run `./scripts/lint.sh` and `tests/planner`. Verify: green.
