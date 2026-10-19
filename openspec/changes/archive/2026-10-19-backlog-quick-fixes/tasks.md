## 1. Forecast created_at

- [x] 1.1 Add `created_at: func.current_timestamp()` to the forecast upsert `set_` in `backend/learning/store.py`; test in a new test file (store twice, assert created_at advanced and values updated): `UV_NO_SYNC=1 uv run python -m pytest tests/ -k forecast_created_at -v` passes.

## 2. Water heater control type

- [x] 2.1 Add shared `infer_control_type` helper; use it in `backend/api/routers/config.py` validator (infer when missing, error only on explicit mismatch or unsupported domain, include heater index in the issue) and in `executor/config.py`; backend tests cover missing, explicit match, explicit mismatch, and `climate.`/`water_heater.` cases and pass.
- [x] 2.2 Frontend: add pure domain-to-control-type helper in `frontend/src/pages/settings/logic.ts`; call it on entity change in `EntityArrayEditor.tsx`; clear wrong-domain entity on manual control type change; vitest tests in `EntityArrayEditor.water.test.tsx` and `logic.test.ts` pass.
- [x] 2.3 Show mismatch errors inline under the heater's fields and flag the Heating tab (`useSettingsForm.ts`, `EntityArrayEditor.tsx`); test that a 400 response renders the message inline and the Heating tab stays reachable (`SettingsNavigation.test.tsx`).

## 3. Inverter AC limit

- [x] 3.1 Update both topology rows in `planner/solver/kepler.py` per design; add tests in `tests/planner/test_inverter_limits.py` for dc grid-charge cap, dc PV-to-battery unconstrained, ac_coupled grid-charge cap, and feasibility with high load; `UV_NO_SYNC=1 uv run python -m pytest tests/planner -q` passes.
- [x] 3.2 Time a 192-slot solve before/after (same scenario, record both in the PR)(5 runs); within 10%.

## 4. Wrap-up

- [x] 4.1 `./scripts/lint.sh` and frontend tests pass; BACKLOG.md left untouched per instruction.
