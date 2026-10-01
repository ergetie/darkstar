## Why

A fresh install that completes today's startup wizard is not a working system. Pricing, location, system flags, core sensors, battery limits, water heater and EV setup are all left on placeholder defaults or empty. The planner then refuses to run (it needs `battery.max_charge_w`/`max_discharge_w`), or it plans against the wrong location and price area. The backend also lacks what a guided, auto-filling onboarding needs. It cannot see which integration or device an HA entity belongs to, it does not read HA's own location/timezone/currency, and it cannot test credentials the user has typed in. Inverter profiles carry no rules for finding matching entities, and nothing answers "can Darkstar actually run now?". This change builds that backend foundation. The `onboarding-wizard` change builds the new UI on top of it.

## What Changes

- **HA connection test with supplied credentials**: `POST /api/ha/test` accepts an optional `{url, token}` body and tests those credentials instead of the saved ones. Standalone first-run users can then pass the connection step. Add-on mode keeps using the Supervisor credentials.
- **HA core config read**: new endpoint returns HA's `latitude`, `longitude`, `time_zone`, `currency`, `country` and `unit_system`, used to pre-fill location, timezone and currency. The price area is never guessed, because SE1–SE4 borders follow municipalities rather than coordinates.
- **Entity and device discovery**: a request/response HA websocket helper reads `config/entity_registry/list` and `config/device_registry/list`. A new discovery endpoint returns entities enriched with `platform` (integration), `device_id`, device `manufacturer`/`model`, `device_class`, `unit_of_measurement`, `state_class` and current state. It degrades gracefully to state-only data if the registry is unavailable.
- **Profile match rules**: inverter profile entities gain an optional `match:` block (integration, domain, device_class, unit, entity_id/name regex). Profiles may declare `metadata.detect` (integrations/manufacturers) so the inverter brand can be auto-suggested.
- **Generic entity matcher**: one matcher scores discovered entities against match rules and returns ranked candidates with a confidence and reason. It covers profile entities and also the core sensors, water heater and EV roles through a built-in role rule table.
- **Profile suggestions endpoint fix**: suggestions are returned as a nested config patch with ranked candidates per key, not as flat dotted keys.
- **Profile data fixes**: fronius defaults that point at one user's hardware are replaced with `null` plus match rules. `write_threshold_a` is parsed (it is ignored today). All shipped profiles get match rules. The config comment no longer lists the non-existent `victron` profile.
- **Synthetic load baseline**: a dedicated `input_sensors.synthetic_daily_load_kwh` key replaces the overloading of `total_load_consumption` with a number, with a migration for existing numeric values.
- **Readiness check**: new `GET /api/setup/readiness` reports per-requirement pass/fail with a fix hint, depending on the system flags. It covers the HA connection, required sensors (readable live, with plausible values), required profile entities, battery limits, PV arrays/location, Nordpool prices, water heater/EV entries and a test plan run. The test plan run is a planner run only and never actuates hardware.
- **Onboarding progress state**: a small server-side state (`data/onboarding_state.json`) records the current step, completed steps and dismissal, so onboarding can be resumed from any browser.
- **Scope limit**: pricing remains Nordpool-only, with the Swedish fee model. No new price sources.

## Capabilities

### New Capabilities
- `ha-discovery`: testing supplied HA credentials, reading HA core config, and registry-enriched entity discovery.
- `entity-matching`: profile match rules, brand detection, role rules for core/water heater/EV entities, ranked candidate suggestions as a nested config patch.
- `setup-readiness`: consolidated readiness check endpoint, including a non-actuating test plan run.
- `onboarding-progress`: persisted onboarding step state (resume, dismiss, completion).
- `synthetic-load-baseline`: dedicated config key for the estimated daily load, plus migration.

### Modified Capabilities
<!-- none: profile parsing fixes are covered under entity-matching; no existing spec requirements change -->

## Impact

- Backend: `backend/api/routers/ha.py`, new `backend/api/routers/setup.py`, new `backend/core/ha_registry.py` (websocket request/response helper), new `backend/core/entity_matcher.py`, `backend/api/routers/executor.py` (profile suggestions), `executor/profiles.py` (match rules, detect, `write_threshold_a`), `backend/core/ha_client.py` (synthetic load key), `backend/config_migration.py` (synthetic key migration), `backend/health.py` (reused by readiness).
- Profiles: `profiles/*.yaml`, `profiles/schema.yaml`.
- Config: `config.default.yaml` (new `synthetic_daily_load_kwh` key, profile comment).
- API: new endpoints, `POST /api/ha/test` gains an optional body (backward compatible), and the profile suggestions response shape changes. Its only consumer, `ProfileSetupHelper`, is updated in `onboarding-wizard`. The route snapshot test needs updating.
- Depends on `config-save-persistence` landing first. Without it, add-on saves are lost on restart.
- No new dependencies (the `websockets` library already used by `backend/ha_socket.py` is reused). No DB schema changes.
