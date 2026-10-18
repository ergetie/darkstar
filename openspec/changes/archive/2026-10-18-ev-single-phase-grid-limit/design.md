# Design

## Verified facts

- Kepler variables (kWh per slot): `grid_import[t]` (`kepler.py:~216`, lowBound 0), `grid_export[t]`, per-charger `ev_energy[d][t]` (wall kWh, `kepler.py:189`), `ev_charge[d][t]` binary, and excess-PV `ev_surplus_kw[d][t]` (kW, `kepler.py:361`), which is an additional load of the same charger (`ev_surplus_load_kwh`, `kepler.py:519`). Plugged chargers = `plugged_chargers` (`kepler.py:158`).
- The hard total cap is `grid_import[t] <= max_import_power_kw * h` at `kepler.py:595`, fed from `system.grid.max_power_kw` at `adapter.py:556`. Energy balance at `kepler.py:~550` includes `load_shedding[t]` (penalty 10000/kWh, `kepler.py:402`), so any hard cap on import is already absorbed by that slack.
- Nothing forces `ev_charge`/`ev_energy` on (current chargers are semi-continuous, `kepler.py:482-483`; the goal is soft via `ev_shortfall`, penalty 50), so the EV can always be reduced to 0.
- `main_fuse_a` is `system.grid.main_fuse_a` (config.default.yaml:32, commented out, optional). The planner (`adapter.py`) receives the whole config as `planner_config`, so it can read it; today only `executor/load_balancer.py` and config validation (`backend/api/routers/config.py:1534`) use it. Voltage: `nominal_voltage_v(config)` in `backend/core/ev_power.py:28`, already imported by `adapter.py:17` and `preflight.py:15`, default 230 V.
- Charger phases: `ev_chargers[].phases` is a list of grid lines (config.default.yaml:143). `charger_power_limits` (`ev_power.py:~70`) uses `len(phases)` only for `type: current`; binary chargers use `rated_power_kw` and their `phases` is not part of the power model. `EVChargerInput` has no phase info today (`types.py:28`).
- Multiple chargers: each plugged charger has its own `ev_energy`; they may sit on different lines.
- `planner/preflight.py:121` (`check_ev_chargers`) only validates power/capacity; it needs no change (see D6).
- Benchmark mode (`types.py:178,195`, `kepler.py:~912`) is a hindsight battery-only run; the new constraint is skipped there.

## Math

Let F = `main_fuse_a x target_margin_percent / 100` (effective fuse limit), V = nominal voltage, G = net grid import kW (`grid_import/h - grid_export/h`), e_c = total kW of charger c (`ev_energy/h_ev + ev_surplus_kw`), n_c its number of phases, s_{c,L} = 1/n_c if line L is in c's phases else 0. Non-EV load (G - sum e_c) is spread evenly, so per line L:

  sum_c s_{c,L} e_c + (G - sum_c e_c)/3 <= F*V/1000

Single charger on L1 (n=1): G + 2e <= 3FV. 2-phase: G + 0.5e <= 3FV. 3-phase: G <= 3FV, which is a looser total cap than the existing one in practice and adds nothing, so it is skipped. Using net G (import minus export) keeps this exact when PV or battery discharge offsets load, since PV and inverter output are also assumed even over phases. Valid for the Sungrow case; for other topologies it is an approximation (KISS, no per-phase forecasting).

## Decisions

- D1 Constraint form: per line L in {1,2,3} that carries any plugged charger with n_c < 3, add the inequality above (in kWh: multiply by h). Identical coefficient sets are emitted once. Lines carrying only 3-phase chargers and chargers with unknown/invalid phases emit nothing. This handles several chargers on different or the same line, using the real `phases` list (not `phase_1_line`, which is the balancer's 1-phase relief line).
- D2 Partial first slot: EV energy is over `ev_slot_hours[t]` (`kepler.py:91`) while import is over `h`. Convert EV energy to average kW with `/ev_slot_hours[t]` and scale by `h`; skip the EV term when `ev_slot_hours[t] <= 0` (its energy is already forced to 0). This is conservative for a short remainder.
- D3 Hard, not soft: the constraint is hard on EV and import, and relies on the existing `load_shedding` slack for the case where house load alone exceeds the limit (same behaviour as the `max_power_kw` cap, `kepler.py:595`). EV can drop to 0, so the EV's own term never causes infeasibility; the EV goal shortfall penalty trades it off. No new slack variable.
- D4 Plumbing: `KeplerConfig.max_phase_import_kw: float | None = None` (= F*V/1000 with F the margin-adjusted fuse, i.e. main_fuse_a * target_margin_percent/100; `None` when main_fuse_a is unset/non-positive/non-numeric) and `EVChargerInput.phases: tuple[int, ...] = (1, 2, 3)`. Adapter fills `phases` for `type: current` chargers only, filtered to {1,2,3} and de-duplicated; empty/invalid falls back to (1,2,3) with a warning. Binary chargers always get (1,2,3), consistent with `charger_power_limits`.
- D5 Not tied to `load_balancing.enabled`: a user with a fuse set gets protection from the planner even if the balancer is off. Unset `main_fuse_a` means the constraint is off (the config default is commented out).
- D6 Preflight: no new check. Invalid `phases` already yields `max_kw <= 0` (EV_MISSING_POWER) for empty lists; out-of-range line numbers are handled by D4 sanitising.
- D7 Phase-switching chargers are treated as 3-phase (no constraint). Kepler has no phase-mode model: planned power for phase-switching chargers never goes below the 3-phase floor (`backend/core/ev_power.py:60-79`, `kepler.py` ~489-491). 1-phase mode is chosen only at runtime by the executor (excess-PV charging in `executor/ev_surplus.py`, and load-balancer relief), so the runtime load balancer is the safety net. Per-device non-EV phase maps and per-phase house forecasts stay in the BACKLOG item.

## Risks

- Limit uses the same margin as the load balancer (`load_balancing.target_margin_percent`), so plan and balancer agree; this reduces EV delivery versus the full fuse.
- Pessimistic when non-EV load is actually concentrated on the other phases; optimistic when concentrated on the EV phase (heater on the same line). Accepted for KISS.

## Resolved decisions

- D8 (user decision): per-phase limit = `main_fuse_a x target_margin_percent / 100` (kW: x nominal_voltage_v / 1000). `target_margin_percent` lives at `load_balancing.target_margin_percent` (config.default.yaml:332, default 85, range 50-100; code default `LoadBalancingConfig.target_margin_percent = 85.0` in executor/config.py:246, resolved by `resolve_target_margin_percent`, executor/config.py:380, which also honours legacy `resume_margin_percent`). The planner reads it from `planner_config` and falls back to 85 when absent/invalid.
  Update: resolution is shared, not duplicated. `backend/core/load_balancing_margin.py` (`resolve_target_margin_percent`, `effective_target_margin_percent`, range, legacy default) is imported by both `planner/solver/adapter.py` and `executor/config.py`, so plan and balancer use the same margin even for a config still carrying a user-tuned legacy `resume_margin_percent` (config migration normally removes it, but the executor honoured it at runtime, so the planner must too). Test: `test_margin_matches_executor_resolution_for_legacy_key`.

## Verification addenda

- D9 Net import is correct: Kepler's energy balance nets grid flows and a meter cannot import and export at once, so per-line load = (net - e)/3 + e/n_c exactly under the even-spread assumption (house load, PV inverter and battery inverter output). Exporting PV while charging the EV is handled: net is lower, and the EV's own line still carries its full share. The only error source is non-even PV/house distribution (accepted risk above); gross import would not fix that (it equals net whenever there is no export) and would wrongly penalise export slots, so net is kept.
- D10 Scope of rows: a row is emitted only for slots where at least one phase-limited charger can draw (time left in the slot, not past its deadline), only for lines carrying such a charger, and identical coefficient sets are emitted once. Slots with no possible EV draw get no row, so the per-phase limit does not cap non-EV import there (would otherwise be a spurious 3 x limit cap).
- D11 Binary chargers are excluded per the spec requirement ("SHALL NOT apply to `type: binary` chargers") and D4: their `phases` is not part of their power model (`charger_power_limits` uses `rated_power_kw`), so no reliable line assignment exists. Their load still counts as non-EV load in the even-spread term.
