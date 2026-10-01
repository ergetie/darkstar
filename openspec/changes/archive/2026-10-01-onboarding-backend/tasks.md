## 0. Preconditions

- [x] 0.1 Confirm `config-save-persistence` is archived/merged (add-on saves persist) before starting

## 1. HA discovery

- [x] 1.1 Create `backend/core/ha_registry.py`: short-lived websocket request/response helper (auth, id sequencing, 10 s timeout, 10 MB max_size, URL derivation shared with `ha_socket.py`)
- [x] 1.2 Implement registry fetch + join (entity → device manufacturer/model) with 60 s in-process cache and graceful `registry_available: false` fallback
- [x] 1.3 Add `GET /api/ha/discovery` returning enriched entities (state, state_class, platform, device fields)
- [x] 1.4 Extend `POST /api/ha/test` with optional `{url, token}` body (not persisted; ignored in add-on mode); return `ha_version` and `registry_available`
- [x] 1.5 Add `GET /api/ha/core-config` (HA `/api/config` subset) and currency fallback (no price-area guessing, see design Decision 4)
- [x] 1.6 Tests: discovery with/without registry, cache, test endpoint body/no-body/add-on, core-config SE vs non-SE vs unreachable

## 2. Entity matching

- [x] 2.1 Extend `executor/profiles.py`: `match` on `EntityDefinition`, `metadata.detect`, `metadata.role_overrides`; validate keys and compile regexes in `Profile.validate()`
- [x] 2.2 Parse `write_threshold_a` (and audit all shipped behavior keys are parsed)
- [x] 2.3 Update `profiles/schema.yaml` docs for new keys
- [x] 2.4 Create `backend/core/entity_roles.py`: role rules for core sensors (incl. dual meter; `total_*` per design Decision 7), water heater control/power, EV switch/current/SoC/plug/power
- [x] 2.5 Create `backend/core/entity_matcher.py`: domain hard filter, independently additive non-domain rules, single weights table, top-5 candidates with score/confidence/reasons, brand ranking via `detect`
- [x] 2.6 Rewrite profile suggestions endpoint to return `patch` (nested), `candidates`, `current`, `missing_required`; add `GET /api/setup/suggestions?roles=...`
- [x] 2.7 Add match rules + detect to `deye`, `fronius`, `sungrow`, `generic` (generic: role-style rules only); replace fronius installation-specific defaults with `null`
- [x] 2.8 Remove `victron` from `config.default.yaml` profile comment
- [x] 2.9 Tests: validation errors, scoring/confidence/margin, domain filter, brand detection, nested patch, current values, missing_required, write_threshold_a parsed, fixture-based discovery samples per brand

## 3. Synthetic load baseline

- [x] 3.1 Add `input_sensors.synthetic_daily_load_kwh: null` to `config.default.yaml` with comment
- [x] 3.2 Update `ha_client.py` fallback to read the new key (sensor precedence preserved)
- [x] 3.3 Add idempotent migration in `backend/config_migration.py` moving numeric `total_load_consumption`
- [x] 3.4 Tests: synthetic used, sensor precedence, migration numeric/sensor/idempotent

## 4. Onboarding progress

- [x] 4.1 Implement state store for `data/onboarding_state.json` (atomic write, corrupt-file fallback) following `backend/core/ev_state.py` pattern
- [x] 4.2 Add `GET/PUT /api/setup/onboarding` in new `backend/api/routers/setup.py` with Pydantic validation; register router
- [x] 4.3 Ensure `data/onboarding_state.json` is gitignored
- [x] 4.4 Tests: not_started default, roundtrip, 422 on invalid, corrupt file

## 5. Readiness

- [x] 5.1 Implement `GET /api/setup/readiness` composing: HA reachable, live sensor plausibility per role, profile entities exist, battery preflight rules (reuse `planner/preflight.py`), PV/location placeholder, Nordpool fetch, water heater/EV validation (reuse `_validate_config_for_save` rules) + entity existence
- [x] 5.2 Add fresh isolated plan check using the planner pipeline with `save_to_file=False`; no live schedule publication or executor involvement; timeout → `warn`
- [x] 5.3 Flag-driven `skipped` checks; `fix_hint` and `settings_path` per check
- [x] 5.4 Tests: ready/not ready, flags skip, dual meter, unavailable/wrong unit, placeholder location, missing battery W, fresh plan pass, assert no live schedule publication, executor involvement or HA service calls

## 6. Integration

- [x] 6.1 Update route snapshot / smoke tests for new endpoints
- [x] 6.2 Run `./scripts/lint.sh` and full test suite; all green
