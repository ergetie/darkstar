## Context

Current state (verified 2026-10-01):
- HA access is REST via httpx (`backend/core/ha_client.py`). The only websocket is `backend/ha_socket.py`, a subscribe-and-listen loop with no request/response helper. Nothing reads the entity or device registry.
- `GET /api/ha/entities` (`ha.py:187`) returns `entity_id, friendly_name, domain, unit_of_measurement, device_class, options` from `/api/states`. It has no platform or device information.
- `POST /api/ha/test` (`ha.py:285`) takes no body and always tests the saved secrets.
- Nothing reads HA `/api/config`.
- Profiles (`executor/profiles.py`, `profiles/*.yaml`, schema v2) have `metadata/entities/modes/behavior` and no match rules. `GET /api/profiles` exists. The suggestions endpoint (`executor.py:~633-690`) returns flat dotted keys.
- Fronius defaults are one user's entity IDs. `write_threshold_a` in deye/generic is never parsed (`profiles.py:~329`).
- Save (`POST /api/config/save`) is a partial deep merge with an atomic write and backups. `config-save-persistence` fixes add-on persistence.
- Health checks exist in pieces (`backend/health.py`, `GET /api/health`, `/api/executor/health`, `/api/config/validate`). None reads sensors live, checks prices and runs a plan together.
- `POST /api/run_planner` runs the planner and reports `slot_count`/error. `POST /api/executor/run` actuates hardware.
- Synthetic load is signalled by storing a number in `input_sensors.total_load_consumption` (`ha_client.py:923-936`), and the wizard never actually saves it.
- Auth: in add-on mode `run.sh` writes `http://supervisor/core` plus `SUPERVISOR_TOKEN` into secrets. In standalone mode the user supplies a URL and a long-lived token.

## Goals / Non-Goals

**Goals:**
- Give the wizard everything it needs to auto-fill and verify a complete, working configuration for the add-on and standalone Docker.
- Have one generic matcher driven by declarative rules, so adding a brand means a YAML file only.
- Have a readiness check that answers "will Darkstar work" without touching hardware.

**Non-Goals:**
- Non-Nordpool price sources, or non-Swedish fee models.
- Auto-detecting PV tilt/azimuth.
- Changing the executor control logic.
- New inverter profiles (victron etc.).
- UI work. That is in `onboarding-wizard`.

## Decisions

1. **Short-lived websocket for registry reads (`backend/core/ha_registry.py`)**, not reusing `HASocketClient`. The live socket is an event loop with dispatch semantics, and bolting request/response onto it couples onboarding to executor monitoring. The helper opens a connection, authenticates, sends `config/entity_registry/list` and `config/device_registry/list` (incrementing ids), joins the results and closes. It uses the same URL derivation as `ha_socket.py` (`http(s)` → `ws(s)`, `/api/websocket`), `max_size=10MB` and a 10 s overall timeout. The result is cached in-process for 60 s.
   - Alternative considered: the HA template API `integration_entities()`. It is per-integration only and has no device model, so it was rejected.
2. **Graceful degradation.** If registry access fails (auth or permission, old HA, or a timeout), discovery returns state-only entities with `platform: null` and a `registry_available: false` flag. The matcher then skips integration rules. Add-on access is verified from source (2026-10-01): the Supervisor proxy registers both `/core/websocket` and `/core/api/websocket` (`supervisor/api/__init__.py`), so the existing `/api/websocket` URL derivation works. It only checks that the add-on has `homeassistant_api` (Darkstar sets `homeassistant_api: true` in `darkstar/config.yaml`), and it filters only `supervisor/*` and `hassio/*` commands (`supervisor/api/proxy.py`). Core sees the Supervisor system user, which is created and kept in the admin group (`homeassistant/components/hassio/__init__.py`). So the registry commands are permitted in add-on mode. In standalone mode they work with any admin long-lived token. The fallback covers non-admin standalone tokens and transient failures.
3. **Credential test with body.** `POST /api/ha/test` accepts an optional `{url, token}`. When present, it tests those values against `/api/` and the websocket auth without persisting them. In add-on mode the body is ignored and Supervisor credentials are used. The response gains `ha_version` and `registry_available`.
4. **HA core config endpoint.** `GET /api/ha/core-config` proxies HA `/api/config` and returns only the needed fields. **No price-area guessing.** The SE1–SE4 borders follow municipal boundaries, not latitude (they are drawn at transmission bottlenecks, see Svenska kraftnät and the elområde lookup services). A coordinate guess would be wrong near the borders, for example in Dalarna, Gävleborg, Västerbotten, Halland, Västra Götaland, Kalmar and Jönköping, which are split between areas. Shipping municipality polygons was rejected as disproportionate. Instead the wizard shows a required SE1–SE4 choice: it keeps the existing value on re-run, and otherwise none is preselected. Each option has a plain-language region description, and a hint says to check the electricity bill or the network operator's postal-code lookup. Currency comes from HA, with SEK as the fallback for SE.
5. **Match rule schema** (an optional `match:` per profile entity, all keys optional; domain is a hard filter and every other rule scores independently):
   - `integration: [str]`: the entity registry `platform`.
   - `domain: [str]`: defaults to the entity's declared domain.
   - `device_class: [str]`, `unit: [str]`
   - `entity_id_regex: str`, `name_regex: str`: case-insensitive.

   Profile-level `metadata.detect: {integrations: [..], manufacturers: [..]}` is used for brand suggestion. It is validated in `Profile.validate()`, and unknown keys are an error at load time.
6. **Scoring.** A hard filter on domain comes first. Then each matching rule independently adds points, regardless of whether any other rule matches: integration +40, device_class +20, unit +15, entity_id_regex +15, name_regex +10, and the profile `default_entity` exact match +50. Candidates scoring below 25 are dropped and the top 5 are returned with `score` and `reasons[]`. Confidence is `high` when score ≥ 70 and the margin to the next candidate is ≥ 20, otherwise `medium`/`low`. The wizard only pre-selects `high`. The numbers live in one constant table and are covered by tests, so tuning does not change behaviour silently.
7. **Built-in role rules for non-profile entities.** `backend/core/entity_roles.py` defines match rules for the roles below, filtered further by the integration of the chosen inverter when it is known:
   - Core sensors: `battery_soc`, `pv_power`, `load_power`, `battery_power`, `grid_power`, `grid_import_power`, `grid_export_power` and the cumulative `total_*`.
   - Water heater: control entity and power sensor.
   - EV: switch, current, SoC, plug and power.

   Profiles may override role rules under `metadata.role_overrides` (for example, Deye sensor naming).

   Cumulative `total_*` roles require `device_class: energy` and a unit of kWh, Wh or MWh, with `state_class` `total_increasing` or `total`. State_class cannot tell lifetime counters from daily-reset counters, since both are commonly `total_increasing`. A daily-reset counter is still usable, because the recorder already detects negative deltas as a meter reset and falls back to the power snapshot for that slot (`backend/recorder.py:149-152`, `:425`). Names containing `total`/`lifetime` add +10, and `today`/`daily` subtract 15, so lifetime counters rank first.
8. **Suggestions response.** `GET /api/profiles/{name}/suggestions` returns:
   - `patch`: a nested config dict holding the best high-confidence picks only.
   - `candidates`: a map from a dotted config path to its ranked list.
   - `current`: the existing values for the same paths.
   - `missing_required`: required paths with no match.

   The wizard uses `current` vs `patch` to render explicit "current → new" choices (never a silent overwrite). New `GET /api/setup/suggestions?roles=...` gives the same shape for role entities.
9. **Readiness endpoint `GET /api/setup/readiness`.** It returns `{ready: bool, checks: [{id, group, status: pass|warn|fail|skipped, message, fix_hint, settings_path}]}`. The checks are driven by the `has_*` flags and `grid_meter_type`:
   - HA reachable.
   - Each required sensor exists, is not `unavailable`/`unknown`, is numeric, and has a plausible unit and range (for example SoC 0–100 %).
   - Required profile entities exist.
   - Battery capacity, charge/discharge W, and min < max SoC (the planner preflight rules).
   - PV kWp > 0, plus location not equal to the shipped placeholder.
   - Nordpool fetch succeeds for the configured area.
   - Water heater and EV entries pass save-validation, and their entities exist.
   - A fresh isolated test plan uses the planner pipeline with `save_to_file=False` and `publish_state=False`, independently of live planner runs, and produces slots. It never publishes a live schedule or updates executor-facing planner state, including EV progress and anti-legionella timestamps.

   It reuses `HealthChecker` and `planner/preflight.py` logic rather than duplicating rules. It never calls the executor. `ready` is true only when no check is `fail`.
10. **Onboarding state in `data/onboarding_state.json`**, following the `ev_multi_day_state.json` pattern: atomic write, schema `{version, status: not_started|in_progress|dismissed|completed, current_step, completed_steps[], updated_at}`. Endpoints are `GET/PUT /api/setup/onboarding`. It is runtime data, so it is never committed and never stored in config.yaml (which keeps config free of UI state). Wizard triggering (in `onboarding-wizard`) reads this state together with `inverter_profile`.
11. **Synthetic load key.** Add `input_sensors.synthetic_daily_load_kwh: null` to `config.default.yaml`. `ha_client` reads it first. A migration in `config_migration.py` moves a numeric `total_load_consumption` into the new key and blanks the old one. A sensor configured in `total_load_consumption` still takes precedence.

## Risks / Trade-offs

- [Standalone long-lived token belongs to a non-admin user, or the registry call fails transiently] → Degrade to state-only matching (Decision 2), and the wizard notes that matching is reduced.
- [Heuristic mis-matches pick a wrong entity] → Only high-confidence picks are pre-filled, and the user always confirms with a live value shown. Readiness verifies plausibility.
- [Planner test run during onboarding is slow, or overlaps the scheduler] → Use an isolated fresh pipeline run without live schedule publication or executor involvement. Readiness runs the plan last and reports a timeout as `warn`.
- [User picks the wrong price area] → Each option has a region description and a hint pointing to the electricity bill. The area is shown on the Review step.
- [Response shape change on suggestions] → Its only consumer is `ProfileSetupHelper`, which is updated in `onboarding-wizard`. Both changes ship in the same release.

## Migration Plan

- The synthetic key migration runs at startup through the existing migration pipeline, and it is idempotent.
- Profile YAML changes are additive (`match`, `detect`), and schema_version stays 2 with the new keys optional.
- Rollback: the new endpoints are unused by the old UI. A reverted synthetic migration leaves `total_load_consumption` blank, which falls back to the flat dummy profile. This is documented in the release notes.

## Open Questions

None. Add-on registry access, price-area handling and cumulative-sensor matching were all resolved before implementation (Decisions 2, 4 and 7).
