# Tasks: backlog-quick-wins

## 1. Delete the dead simulate stack

- [x] 1.1 In `backend/api/routers/schedule.py`, delete the entire `run_simulation` handler including its `@router.post("/api/simulate", ...)` decorator (the block spanning ~lines 524-545). Then check whether any imports at the top of the file are now unused and remove only those.
- [x] 1.2 Delete the file `planner/simulation.py` (its only consumer was the handler deleted in 1.1 — verified 2026-07-10).
- [x] 1.3 Delete the file `tests/planner/test_simulation.py` (tests only the module deleted in 1.2).
- [x] 1.4 In `tests/api/test_route_snapshot.py`, remove the `POST /api/simulate` entry from the expected-routes list. In `tests/api/test_endpoint_smoke.py`, remove the smoke test (or test-case entry) for `/api/simulate`. Do not change any other route entries.
- [x] 1.5 In `frontend/src/lib/api.ts`, delete the `simulate` function (~line 770, the block containing `fetch('api/simulate', ...)`). If a type/interface is referenced ONLY by that function, delete it too; otherwise leave types alone.
- [x] 1.6 Delete the files `frontend/src/pages/archive/Planning.tsx`, `frontend/src/pages/archive/Lab.tsx`, and `frontend/src/pages/archive/Learning.tsx`. If `frontend/src/pages/archive/` is then empty, delete the folder. (All three verified unrouted and unimported, user-approved.)
- [x] 1.7 Verify: run `pytest tests/api/ tests/planner/` (must pass) and the frontend typecheck/lint (must pass). Also `grep -rn "simulate" backend/ planner/ frontend/src/ tests/` must return no hits related to the deleted endpoint (ignore unrelated words containing "simulate" if any, and ignore `backend/static/assets/` build artifacts).

## 2. Mock script timezone fix

- [x] 2.1 In `scripts/insert_mock_price_forecasts.py` (~line 52), replace the `strftime("%Y-%m-%dT%H:%M:%S")` formatting of `slot_start` with `.isoformat()` on a timezone-aware datetime, and do the same for `issue_timestamp` on the same line. The datetimes must carry the local timezone (match how production writes `slot_observations.slot_start`, e.g. `2026-03-30T00:00:00+02:00`).
- [x] 2.2 Verify: run the script against a scratch copy of the DB (or add a temporary print of one row) and confirm both timestamps include a `+HH:MM` offset. Do not run it against the production DB.

## 3. Spec validation fixes (documentation lint only — no behavior changes)

- [x] 3.1 Run `openspec validate --specs` and note the exact failing requirements in each of the 5 failing specs (`startup-wizard`, `sensor-configuration`, `aurora-corrector`, `executor`, `planner`). This pinpoints which requirement blocks the following tasks edit.
- [x] 3.2 `openspec/specs/startup-wizard/spec.md`: reword all 5 requirements to contain SHALL or MUST (keep the meaning identical — this is rewording, not redesign), and expand the Purpose section to at least 50 characters describing what the startup wizard is.
- [x] 3.3 `openspec/specs/sensor-configuration/spec.md`: reword requirements #4 and #5 to contain SHALL or MUST, meaning unchanged.
- [x] 3.4 `openspec/specs/aurora-corrector/spec.md`: reword requirement #1 to contain SHALL or MUST, and add a `#### Scenario:` block under it with WHEN/THEN bullets. Before writing the scenario, read the implementing code/tests for that requirement and describe the ACTUAL current behavior — never invent aspirational behavior (design D3).
- [x] 3.5 `openspec/specs/executor/spec.md`: add a `#### Scenario:` block (WHEN/THEN bullets, level-4 header exactly `#### Scenario:`) under requirements #2 and #3, derived from actual implemented behavior per design D3.
- [x] 3.6 `openspec/specs/planner/spec.md`: add a `#### Scenario:` block under requirement #5, derived from actual implemented behavior per design D3. (This is a different requirement than "Simulation SoC projection…", which is removed via this change's delta spec — do not touch that one here.)
- [x] 3.7 Verify: `openspec validate --specs` exits with all specs passing.

## 4. Parallelize per-charger HA reads in GET /api/ev/chargers

- [x] 4.1 In `backend/api/routers/ev.py`, `get_ev_chargers` (line 268): replace the three sequential awaits at lines 308-310 (`_safe_kw`, `_safe_float`, `_safe_bool`) with a single `power_kw, soc_percent, plugged_in = await asyncio.gather(...)` call preserving that result order. No error-handling changes needed — the `_safe_*` helpers already catch all exceptions internally and return `None`, so gather can never receive a raised exception. Add `import asyncio` if not present.
- [x] 4.2 Also parallelize across chargers: extract the per-charger body of the `for ev in ev_chargers_cfg:` loop into an inner async function returning the charger dict (or `None` for disabled chargers), and `asyncio.gather` one task per charger, preserving the original config-list order of the response.
- [x] 4.3 Update/add tests for `GET /api/ev/chargers`: (a) response shape and ordering unchanged versus before, (b) one charger's failed sensor read still yields `None` fields for that charger only, other chargers unaffected.
- [x] 4.4 Verify against live HA (`ssh darkstar`, see memory `reference_prod_server`): the endpoint returns the same data as before the change; note the latency before vs after.

## 5. Slim HA history fetches (flag-only, equivalence-gated — design D5)

- [x] 5.1 Capture baseline BEFORE changing code: against live HA, record (a) the JSON response of `GET /api/ha/average` for a fixed entity + fixed time window, and (b) the list returned by `get_load_profile_from_ha` (log or scratch-script it). Save both to compare in 5.4.
- [x] 5.2 Read the response-parsing code in `backend/api/routers/ha.py` `_fetch_ha_history_avg` and `backend/core/ha_client.py` `get_load_profile_from_ha` (~line 589). Check compatibility with HA's `minimal_response` format: after the first entry per entity, HA returns abbreviated dicts (keys `state`/`last_changed` only, no `entity_id`, no attributes). If the parsing reads `attributes` or `entity_id` from every entry, adapt it before flipping flags.
- [x] 5.3 In exactly those two call sites, set `"minimal_response": True` and add `"no_attributes": True`. Leave `"significant_changes_only": False` unchanged (dropping intermediate points would change duration-weighted averages). Do NOT touch `backend/learning/backfill.py` or `get_energy_from_power_history` in `ha_client.py`.
- [x] 5.4 Verify equivalence: repeat the 5.1 measurements with the new flags for the same window — averaged values must match the baseline (allow only float-noise differences). Record the latency improvement.

## 6. Finalize

- [x] 6.1 Run the full local CI gate (`scripts/ci_local.sh`) and fix anything it flags.
