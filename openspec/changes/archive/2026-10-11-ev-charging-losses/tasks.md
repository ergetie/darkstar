## 1. Config and settings

- [x] 1.1 Add `charge_overhead_kw: 0.25`, `start_loss_kwh: 0.15`, `charge_efficiency: 0.95` and `energy_added_sensor: ""` with comments to the `ev_chargers` entry in `config.default.yaml`; verify `merge_arrays` (`backend/config_migration.py`) fills them for an existing entry, with a test
- [x] 1.2 Validate the ranges (overhead 0–2, start loss 0–1, efficiency 0.5–1.0) in `backend/api/routers/config.py` next to the existing EV validation, with tests for accept/reject
- [x] 1.3 Parse the new fields in `executor/config.py` `EVChargerDeviceConfig` and wherever the planner reads EV config
- [x] 1.4 EV tab: add three NumberInputs with tooltips and an EntitySelect for `energy_added_sensor` in `frontend/src/pages/settings/components/EntityArrayEditor.tsx` (type, new-entity defaults, fields); update `frontend/src/lib/api.ts` types; follow `docs/design-system/AI_GUIDELINES.md`

## 2. Kepler loss model

- [x] 2.1 Add `charge_overhead_kw`, `start_loss_kwh`, `charge_efficiency` and `charging_now` to `EVChargerInput` (`planner/solver/types.py`); fill them in `build_ev_charger_inputs` (`planner/solver/adapter.py`), with `charging_now` from the charger's measured power above a small threshold
- [x] 2.2 Add binary `ev_surplus_on[d][t]` with `ev_surplus_kw ≤ max_kw × ev_surplus_on`, and add a continuous `ev_start[d][t] ∈ [0,1]` with `ev_start[t] ≥ on[t] − on[t−1]`, where `on = ev_charge + ev_surplus_on` and `on[−1] = charging_now` (`planner/solver/kepler.py`)
- [x] 2.3 Replace `delivered_terms` (~`kepler.py:679`) with the loss-adjusted energy; add `start_loss_kwh × import price × ev_start` to the objective; keep grid import and the energy balance on full wallbox energy
- [x] 2.4 Solver tests: fewer high-power slots chosen; efficiency raises wallbox energy (10 kWh at 0.95 → ≥10.53); no start counted when continuing a running session; surplus slot pays overhead; solve-time limit tests still pass

## 3. Goal accounting

- [x] 3.1 Make `_ev_delivered_today_kwh` / `_calculate_required_kwh` (`planner/pipeline.py`) use recorded car energy where present, else wallbox × efficiency; apply the same rule in goal diagnostics/progress; add tests

## 4. Car-side energy recording

- [x] 4.1 Alembic migration (down_revision `d2a6f1c8e4b7`) adding nullable `car_energy_kwh` (Float) and `car_energy_source` (String) to `ev_charger_observations`; update `EvChargerObservation` in `backend/learning/models.py`
- [x] 4.2 Compute per-slot car energy in `backend/recorder.py` (energy-added sensor delta with reset handling, else fresh-SoC delta × `battery_capacity_kwh`, else NULL) and persist it in `LearningStore._replace_ev_charger_observations`
- [x] 4.3 Recorder tests: sensor reset mid-slot, SoC fallback (60→62% on 64 kWh = 1.28), stale SoC → NULL

## 5. Automatic learning

- [x] 5.1 Add an EV loss analyser to `backend/learning/reflex.py`: aggregate the last 30 days per charging day, apply the ratio filter (0.3–1.02) and sensor-over-SoC preference, least-squares fit of efficiency/overhead/start loss, minimum 8 clean days and 20 starts, clamping, and writes through the existing `update_config` with daily max-change, gated by `learning.reflex_enabled`
- [x] 5.2 Learning tests: not enough data → no change; synthetic data recovers known parameters; reflex disabled → no change; bounds clamped

## 6. Load balancer: pause instead of 1-phase when the goal is on track

- [x] 6.1 Add `goal_at_risk: bool` to `EVBalancerInput`; evaluate `_pause_goal_risk` per charger in `_run_load_balancer` before the tick (`executor/engine.py`), failing open
- [x] 6.2 Gate 1-phase relief in `_degrade_at_floor` and `_refit_paused` (`executor/load_balancer.py`) on `relief_available and goal_at_risk`
- [x] 6.3 Tests in `tests/executor/test_load_balancer_graceful_degradation.py`: on track → pause; at risk → 1-phase; evaluation error → 1-phase allowed; resume stays in current mode when on track; update existing relief tests to set `goal_at_risk=True`
- [x] 6.4 Also allow 1-phase relief (floor and resume) when the current plan slot is solar-surplus charging for the charger: `surplus_slot` on `EVBalancerInput` from `slot.ev_surplus_kw`, gate `relief_available and (goal_at_risk or surplus_slot)`; tests for surplus → 1-phase, non-surplus → pause, surplus resume → 1-phase, and the engine reading the flag

## 7. Verification

- [x] 7.1 Run `./scripts/lint.sh` and the full test suite
- [ ] 7.2 Run the dev environment, check the EV tab fields visually, and check that a plan with a goal shows fewer, higher-power EV slots
