## 1. Resolve open design questions

- [x] 1.1 Decide OQ-A: split `charge[t]` vs. keep it as total with `pv_to_battery[t]` as a bounded sub-flow (check every wear/ramping/efficiency constraint that references `charge[t]` in `planner/solver/kepler.py`)
- [x] 1.2 Decide OQ-B: whether the DC charge path needs its own power limit distinct from `max_inverter_ac_kw`; if not, bound `pv_to_battery[t]` by the existing battery charge-power limit only
- [x] 1.3 Decide OQ-C: confirm `dc_coupled` is the correct default topology against known user configs before shipping

## 2. Config + topology plumbing

- [x] 2.1 Add `inverter.topology` field (`dc_coupled` | `ac_coupled`, default `dc_coupled`) to `config.default.yaml` and config schema/validation
- [x] 2.2 Add a config-migration step defaulting `inverter.topology` to `dc_coupled` for configs that set `max_inverter_ac_kw` but have no topology
- [x] 2.3 Thread `topology` through `planner/solver/adapter.py` and `planner/solver/types.py` into the solver input

## 3. Solver constraint refactor (`planner/solver/kepler.py`)

- [x] 3.1 Add per-slot continuous variables `pv_to_battery[t] >= 0` and `pv_to_ac[t] >= 0`
- [x] 3.2 Add the PV balance constraint `pv_to_battery[t] + pv_to_ac[t] + curtailment[t] == s.pv_kwh`
- [x] 3.3 Replace the AC-limit block at `kepler.py:431-434` with `pv_to_ac[t] + discharge[t] <= inverter_ac_kwh` for `dc_coupled`
- [x] 3.4 Bound `pv_to_battery[t]` by available battery charge headroom and the battery charge-power limit (per OQ-A/OQ-B decision)
- [x] 3.5 For `ac_coupled`, include battery charging in the AC limit (reproduce the prior `pv_forecast[t] + discharge[t] <= inverter_ac_kwh` math)
- [x] 3.6 Keep ramping, wear, and efficiency constraints operating on total charge/discharge (verify untouched)
- [x] 3.7 Confirm the no-limit default path adds no AC constraint and omits PV-routing vars when `max_inverter_ac_kw` is unset

## 4. Tests (`tests/planner/`)

- [x] 4.1 Update the existing inverter-AC-limit scenarios to the new constraint form (within-limit discharge bound; PV-exceeds-limit stays feasible)
- [x] 4.2 Add dc_coupled case: PV above the AC limit routes surplus to battery instead of forcing curtailment/infeasibility
- [x] 4.3 Add dc_coupled case: `pv_to_ac[t]` (load + export) is independently capped at `inverter_ac_kwh`
- [x] 4.4 Add ac_coupled case: battery charging counts against the AC limit (stricter combined bound)
- [x] 4.5 Add unset-limit case: no AC constraint, no routing vars

## 5. Verification

- [x] 5.1 Benchmark MILP solve time on a representative 48 h horizon before vs. after (confirm the added continuous vars don't materially slow the solve)
- [x] 5.2 Run the full planner test suite; confirm no regression in non-AC-limit solver behavior
- [x] 5.3 Update `docs/BACKLOG.md` (mark the inverter item resolved) and stabilization-review Finding #34 status once shipped
