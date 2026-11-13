# Tasks

## 1. Config model and migration

- [x] 1.1 Add `phases: [1, 2, 3]` (with comment) to the `water_heaters` entry and example in `config.default.yaml`; reword the `load_balancing.loads[].phases` comment (custom_entity only)
- [x] 1.2 Add `_migrate_water_heater_load_phases` in `backend/config_migration.py` and call it in the pre-merge section; idempotent, warns on no match or conflict
- [x] 1.3 Validation in `backend/api/routers/config.py`: validate `water_heaters[].phases` (1-3, distinct, non-empty); require `loads[].phases` only for `custom_entity`; warn on a water_heater load that still has `phases` without a matching device
- [x] 1.4 Tests: migration (moved, device already set, no match, custom untouched, idempotent) in the existing config migration test module

## 2. Load balancer

- [x] 2.1 `executor/config.py`: fill water_heater `BalancedLoadConfig.phases` from `water_heaters[]` (default `[1,2,3]`), ignore `loads[].phases` for them
- [x] 2.2 Check `executor/engine.py` and `executor/load_balancer.py` use only the resolved `phases`
- [x] 2.3 Tests: balancer config reads device phase; custom_entity keeps own phases; EV unchanged

## 3. Planner

- [x] 3.1 `planner/solver/types.py`: `WaterHeaterInput.phases: tuple[int, ...] = (1, 2, 3)`; `adapter.py` reads and sanitises `water_heaters[].phases`
- [x] 3.2 `kepler.py`: generalise phase-limited device set (EV + water heaters), activate when either exists, add water heater terms `(share - 1/3) * kWh` (normal + boost) to the per-line rows, keep dedupe
- [x] 3.3 Add slack with `PHASE_OVERLOAD_PENALTY` only on rows of slots with a forced-on phase-limited heater; log slack use
- [x] 3.4 Update the stale comments (~787-790) describing the constraint
- [x] 3.5 Tests (planner): 1-phase heater + 1-phase EV on same phase stay under the limit in every slot; heater on another phase from the EV is not restricted; 3-phase heater adds no rows; forced-on slot over the limit stays feasible; benchmark mode unaffected
- [x] 3.6 Test that `min_kwh_per_day` is still met or penalised, not infeasible, with the limit active

## 4. Frontend

- [x] 4.1 `EntityArrayEditor.tsx`: `phases` on `WaterHeaterEntity`, default in `createDefaultWaterHeater`, L1/L2/L3 chip picker in the water heater card (follow AI_GUIDELINES.md and the EV phase picker pattern)
- [x] 4.2 `GiveWayListEditor.tsx`: water_heater loads show phases read-only with link to the VVB tab; custom loads unchanged
- [x] 4.3 Frontend tests (EntityArrayEditor water heater phases, LoadBalancingTab / GiveWayListEditor read-only behaviour); run `pnpm` lint, type check and tests

## 5. Docs (ask user before editing docs/)

- [x] 5.1 `docs/USER_MANUAL.md`: document `water_heaters[].phases`, the load balancing `loads[].phases` change, and the note to map the heater power sensor
- [x] 5.2 `docs/BACKLOG.md`: update "[Planner] Per-Phase Load Awareness" to say the per-device water heater part is done; per-phase house-load forecast remains
- [x] 5.3 `docs/ARCHITECTURE.md`: update the planner per-phase constraint / load-balancing description if it mentions it
- [x] 5.4 Do NOT edit `docs/RELEASE_NOTES.md`

## 6. Verification

- [x] 6.1 `UV_NO_SYNC=1 uv run python -m pytest` for touched tests, then `./scripts/lint.sh`
- [x] 6.2 Do not commit or push without explicit user instruction
