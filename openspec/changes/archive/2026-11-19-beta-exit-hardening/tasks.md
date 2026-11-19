# Tasks

## 1. Cross-site write protection

- [x] 1.1 Create `backend/middleware/fetch_site.py` with `FetchSiteGuard` (http, websocket, lifespan scopes; delegating `other_asgi_app` property); verify by unit tests in `tests/api/test_fetch_site_guard.py` covering method x header (`cross-site`, `same-site`, `same-origin`, `none`, absent, mixed case) x scope
- [x] 1.2 Remove `CORSMiddleware` and its import from `backend/main.py:313-319,16`; verify `grep -n CORSMiddleware backend` returns nothing
- [x] 1.3 Wrap the returned `socket_app` in `FetchSiteGuard` at `backend/main.py:444`; verify `create_app().other_asgi_app` still returns the FastAPI app (existing tests in `tests/api/` pass)
- [x] 1.4 Set `cors_allowed_origins=[]` in `backend/core/websockets.py:28-30` and make `backend/api/routers/debug.py:243` report the real value; verify via a test asserting the debug payload and `sio.eio.cors_allowed_origins == []`
- [x] 1.5 Type the body of `PUT /api/executor/config` (`backend/api/routers/executor.py:383-390`) with an `extra="allow"` model; verify a valid payload still writes config and invalid JSON returns 422
- [x] 1.6 Type the body of `POST /api/executor/notifications` (`executor.py:496-503`) the same way; verify with the same two tests
- [x] 1.7 Use `BriefingRequest` as the body of `POST /briefing` (`backend/api/routers/forecast.py:365-375`) and drop the manual `request.json()` try/except; verify valid payload works and invalid JSON returns 422
- [x] 1.8 Add integration test: cross-site POST to `PUT /api/executor/config` returns 403 and `config.yaml` is unchanged; same-origin and header-less requests succeed
- [x] 1.9 Add integration test: no response (including preflight-style `OPTIONS` with `Origin`) carries `Access-Control-Allow-Origin`
- [x] 1.10 Add Socket.IO test: handshake with `Sec-Fetch-Site: cross-site` is refused, `same-origin` is accepted

## 2. Unitless power sensors

- [x] 2.1 Add `sensor_unit_overrides: {}` with a comment to `config.default.yaml`; verify `tests/config` default-key tests and the migration test add the key to an old config
- [x] 2.2 Validate `sensor_unit_overrides` in `backend/api/routers/config.py` (key pattern, values `W`/`kW`) with clear error messages; verify with accept and reject tests
- [x] 2.3 Create `backend/core/power_sensors.py` with the declarative registry of power config path patterns and `path_key`s; verify a test that expands each pattern against a sample config
- [x] 2.4 Add `resolve_power_unit` (returns `ResolvedUnit(unit, source)`: reported, override, assumed kW) and `normalize_power_for_entity` plus the cached overrides accessor in `backend/core/ha_client.py`; verify resolver matrix tests (reported wins, override only when unitless, W/kW/MW, none gives assumed kW)
- [x] 2.5 Use the resolver in `get_ha_sensor_kw_normalized` (`ha_client.py:216-229`), keeping unitless as kW with the once-per-entity warning text "assuming kW. Set its unit in Settings"; verify tests for unitless with and without override and that the warning logs once
- [x] 2.6 Use the resolver in `parse_power_states` (`ha_client.py:259-298`), replacing `_warn_unknown_unit_once`; verify history tests including propagated cached unit and unchanged kW result for unitless
- [x] 2.7 Use the resolver at `ha_client.py:550-580` (history unit propagation) and `ha_client.py:946`; verify existing history tests pass plus one override case
- [x] 2.8 Use the resolver in `backend/core/water_progress.py:60-79`; verify water progress tests with unitless sensor and override W
- [x] 2.9 Use the resolver in `backend/loads/service.py:224-245`; verify load service tests with unitless power sensor
- [x] 2.10 Replace the inline unit check at `executor/engine.py:5156` with the resolver; verify an executor test with unitless sensor and override
- [x] 2.11 Replace inline `== "W"` checks at `backend/ha_socket.py:801,877,944` with the resolver (MW supported); verify socket handler tests for W, kW, MW, unitless, override
- [x] 2.12 Convert EV power with the resolver in `backend/api/routers/system.py:131-134` and remove the stale comment; verify a status test where a 7200 W sensor reports 7.2 kW
- [x] 2.13 Add a drift guard test: every `path_key` passed to the resolver exists in the registry, every registry entry has a caller, and no backend or executor module reads `unit_of_measurement` for power outside the resolver
- [x] 2.14 Add `compute_unit_needed(config, states)` in `backend/core/power_sensors.py` returning `{entity_id, settings_path, live_value}`; verify tests for unitless, unit reported, override present, non-numeric state, and one case per registry path (input roles, EV, water, load power sensor)
- [x] 2.15 Add `unit_needed` to the readiness response and replace the per-role unit logic at `readiness.py:98-144` and `:262-300` with warn checks carrying the `set_sensor_unit` action and the override pass message; verify readiness tests
- [x] 2.16 Add `POST /api/setup/sensor-units` (draft config in, `{unit_needed}` out, no planner run, nothing saved) in `backend/api/routers/setup.py`; verify an API test with two different draft selections
- [x] 2.17 Prune unreferenced `sensor_unit_overrides` entries on config save in `backend/api/routers/config.py`; verify a test that keeps referenced and drops stale entries
- [x] 2.18 Add `unit_needed`, the readiness action type, `sensor_unit_overrides` and the `sensorUnits` API call to `frontend/src/lib/api.ts`; verify `pnpm typecheck`
- [x] 2.19 Create `SensorUnitSelect` (W/kW segmented control using design-system tokens) and the `useUnitNeeded(draftConfig)` hook (debounced 300 ms, refetch on selection change); verify vitests for rendering, change events and debounce
- [x] 2.20 Render `SensorUnitSelect` inside the shared picker `frontend/src/components/EntitySelect.tsx` (used by `EntityField.tsx`, `SettingsField.tsx`, `EntityArrayEditor.tsx`, `GiveWayListEditor.tsx`, `ExcessPvPriorityEditor.tsx`) when the selected entity is in `unit_needed`, writing `sensor_unit_overrides.<entity_id>` to the draft config; verify vitests that it appears and disappears when the selection changes
- [x] 2.21 Pass the onboarding draft config (`OnboardingWizard.tsx`) and the Settings form state (`useSettingsForm.ts`) to the picker hook; verify one vitest per place showing identical behaviour for the same entity
- [x] 2.22 Keep the "Current value: <state> <unit>" line unchanged for entities with a unit (`EntityField.tsx:34-39`); verify a vitest asserting the text and no selector
- [x] 2.23 Add the "Set unit" action button to readiness warn rows using the existing readiness navigation to `settings_path`; verify a vitest that clicking it navigates to the field
- [x] 2.24 Add a guard vitest that fails when frontend sources contain a hardcoded power-sensor field list (for example `ev_chargers`/`power_sensor` path strings in `SensorUnitSelect`, `useUnitNeeded` or `EntitySelect`)

## 3. Schedule fallback alerting

- [x] 3.1 Reset `_stale_schedule_warning` as the first statement of `_load_current_slot` (`executor/engine.py:2510-2537`); verify a stale then deleted then fresh test shows no stuck warning
- [x] 3.2 Add the `_no_valid_schedule(reason)` helper (WARNING on first occurrence, DEBUG after) and use it for missing, unreadable, empty, no `generated_at` and stale causes (`engine.py:2519-2575`) with the "no valid schedule, idle fallback" texts; verify one test per cause
- [x] 3.3 Replace the "No valid slot found" branch at `engine.py:1696-1716` so all causes use the single notify/dedupe path; verify notify is called once per transition, not on cause change, and again after recovery
- [x] 3.4 Update existing executor tests asserting "holding" to the new wording; verify `UV_NO_SYNC=1 uv run python -m pytest tests/executor -q`
- [x] 3.5 Add a test that missing and empty schedule ticks are counted as uncounted (`tick_uncounted`, `engine.py:1720-1724`) like stale ones

## 4. Secret URLs in logs

- [x] 4.1 Add `scrub_urls` to `backend/core/exception_text.py` and call it in `describe_exception` before truncation; verify parametrized cases in `tests/test_exception_text.py` (webhook, query token, userinfo, trailing punctuation, multiple URLs, host-only preserved, no URL)
- [x] 4.2 Mask `token=`, `api_key=`, `key=`, `access_token=`, `password=` and bearer patterns outside URLs; verify tests
- [x] 4.3 Log only exception class and status in the Discord path of `backend/notify.py:118-121`; verify a test with an `HTTPError` containing the webhook URL where `caplog` has no secret and the line equals "Discord notification failed: HTTPError status=404"

## 5. CI

- [x] 5.1 Add `"typecheck": "tsc --noEmit"` to `frontend/package.json` scripts; verify `pnpm typecheck` exits 0
- [x] 5.2 Add `pnpm typecheck` after ESLint and `pnpm build` after tests in the `lint-frontend` job of `.github/workflows/ci.yml`; verify YAML parses and step order by reading the file
- [x] 5.3 Update `scripts/ci_local.sh` to `[x/8]` steps adding frontend typecheck, vitest and build guarded by `command -v pnpm`; verify `bash -n scripts/ci_local.sh` and a dry read of numbering

## 6. Logs

- [x] 6.1 Replace `TimedRotatingFileHandler` with `RotatingFileHandler(maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")` in `backend/core/logging.py:99-101` and fix imports; verify `tests/test_logging.py` asserts type and parameters
- [x] 6.2 Add a rollover test writing past `maxBytes` in a temp dir (not `/tmp`) that produces `darkstar.log.1`
- [x] 6.3 Make clear-logs (`backend/api/routers/system.py:209-212`) also delete `darkstar.log.1..5`; verify a test with backups present
- [x] 6.4 Include `darkstar.log.1` in the diagnostics bundle (`system.py:494`) and manifest when present; verify a bundle test
- [x] 6.5 Add `logging` json-file `max-size: "10m"`, `max-file: "3"` to `darkstar` and `updater` in `docker-compose.yml`; verify with a YAML-parsing test

## 7. Add-on run.sh

- [x] 7.1 Create `backend/addon_bootstrap.py` with `merge_ha_secrets` (token always, url when missing or empty, preserve all keys and comments, no `notifications` section, no write on parse error, create when absent); verify tests in `tests/test_addon_run_sh.py` (webhook and OpenRouter key preserved, token rotated, user URL kept, parse error not overwritten)
- [x] 7.2 Add `apply_addon_options` applying `timezone` only when non-empty and different; verify tests for set, empty and absent
- [x] 7.3 Make `python3 -m backend.addon_bootstrap` run the merges with path overrides via arguments for tests; verify an end-to-end temp-dir test
- [x] 7.4 Edit `darkstar/run.sh`: delete the secrets heredoc (`:36-46`), replace the embedded Python block with the module call, remove `price_area`, `battery_soc_sensor`, `has_*` handling and `PRICE_AREA`, export `TZ` only when non-empty, print status values without hardcoded fallbacks
- [x] 7.5 Copy the result to `darkstar-dev/run.sh`; verify a test asserting both files are byte-identical
- [x] 7.6 Change both `darkstar/config.yaml` and `darkstar-dev/config.yaml` schema to `timezone: str?` and drop `timezone` from default `options:`; verify a test parsing both files
- [x] 7.7 Verify `bash -n` on both `run.sh` files and add a test asserting `Dockerfile` and `darkstar/Dockerfile` contain `COPY backend/ ./backend/` (`Dockerfile:54`, `darkstar/Dockerfile:47`) so `backend/addon_bootstrap.py` ships in the image

## 8. Currency

- [x] 8.1 Create `frontend/src/lib/currency.ts` (store, `CurrencyProvider`, `useCurrency`, `currencyInfo`, `formatMoney`, `formatPrice`, `priceUnitLabel`, `moneyUnitLabel`); verify `currency.test.ts` for SEK, EUR, NOK, unknown code, before-load and main versus sub unit
- [x] 8.2 Mount `CurrencyProvider` once in `frontend/src/App.tsx` and update the store after settings save in `pages/settings/hooks/useSettingsForm.ts`; verify a vitest that saving a new currency updates the labels
- [x] 8.3 Fix the price outlook tooltip and `ore()` in `BatteryStrategyCard.tsx:192,331-336` (P10, P90, Lowest hour, Highest hour); verify a vitest showing "2.90 SEK/kWh" and no "öre" for 2.9
- [x] 8.4 Replace literals in `KPIStrip.tsx:33,50,97` and `ContextRadar.tsx:14,37`; verify existing tests plus an EUR case
- [x] 8.5 Replace literals in `CommandDomains.tsx` (`:454-755` all lines in the inventory); verify `CommandDomains.test.tsx` updated for the helper output
- [x] 8.6 Replace literals in `CostSeriesChart.tsx:440,537`, `pages/Aurora.tsx:545`; verify tests
- [x] 8.7 Make `ChartCard.logic.ts:102,422,438` accept the unit label as a parameter and update callers in `ChartCard.tsx:81,367,481`; verify `ChartCard.logic.test.ts`
- [x] 8.8 Replace literals in `TransferFeeRulesEditor.tsx` (`:115,216,231,232,310,416,449`) and `onboarding/steps.tsx:528,539`, `ExcessPvPriorityEditor.tsx:263`; verify their tests
- [x] 8.9 Add `{currency}` and `{priceUnit}` token substitution in `SettingsField.tsx` (including `:300`) and convert `pages/settings/types.ts` labels and helpers and `search/guides.ts:83` to tokens; verify vitest that labels resolve for SEK and EUR
- [x] 8.10 Ensure a `nordpool.currency` select (SEK, EUR, NOK, DKK) exists in Settings; add it to the System tab when missing; verify `SystemTab.test.tsx`
- [x] 8.11 Add the vitest guard test that fails on `\bSEK\b|öre|\bkr\b` in non-test frontend sources outside the `currency.ts` allowlist
- [x] 8.12 Add `backend/core/currency.py` (`get_currency_code`, `price_unit`); verify `tests/core/test_currency.py` for missing key, lowercase, invalid code
- [x] 8.13 Use it in `backend/strategy/engine.py:95-123`, `backend/api/routers/analyst.py:191`, `backend/api/routers/config.py:1012,2009`; verify message tests with EUR
- [x] 8.14 Remove the unit text from log lines `planner/solver/kepler.py:1371` and `planner/pipeline.py:1175,1176,1336`; verify `grep -n "SEK" planner` shows only docstrings and comments

## 9. Browser display timezone

- [x] 9.1 Create `frontend/src/lib/timezone.ts` (`displayTimeZone`, `displayLocale`, mockable); verify `timezone.test.ts` incl. fallback to `UTC`
- [x] 9.2 Rework `frontend/src/lib/time.ts` (`TZ` at `:10`, `ymdLocal`, `formatHour`, `wallClockParts`) to use `displayTimeZone()`, locale-independent `formatToParts` keys and `hourCycle: 'h23'`; verify `time.test.ts` for Auckland, Stockholm and DST spring-forward and fall-back days
- [x] 9.3 Update `ChartCard.logic.ts:43,51,63` defaults to `displayTimeZone()`; verify `ChartCard.logic.test.ts`
- [x] 9.4 Change the `ChartCard.tsx:65,77` fallback to `displayTimeZone()` while keeping `config.timezone` for rule matching at `:98`; verify a test where browser and config timezones differ
- [x] 9.5 Replace `sv-SE` in `ModelTrainingCard.tsx:114,156`, `Aurora.tsx:582`, `Executor.tsx:598,607` with `displayLocale()` and `displayTimeZone()`; verify component tests or format helper tests
- [x] 9.6 Replace `sv-SE` and display timezone use in `CommandDomains.tsx:325-336` (labels use display timezone, buckets keep `time_axis.timezone`); verify `CommandDomains.test.tsx`
- [x] 9.7 Fix UTC-date bug in `pages/Dashboard.tsx:381-384` using the local-date helper; verify a test at 00:30 local where UTC date differs
- [x] 9.8 Fix `CommandDomains.tsx:75-119` date range keys with local-date formatting; verify a test across midnight
- [x] 9.9 Fix `pages/Aurora.tsx:678-679` the same way; verify a test
- [x] 9.10 Replace `Europe/Stockholm` in `pages/DesignSystem.tsx:47,228` and update the comment at `lib/api.ts:85`; verify `pnpm typecheck`
- [x] 9.11 Add the vitest seam test (browser `Pacific/Auckland`, config `Europe/Stockholm`) proving no slot is dropped or duplicated in `useChartSlots` and `ChartCard.tsx:1469-1470` over the 48 h window
- [x] 9.12 Add the guard vitest failing on `Europe/Stockholm` or `sv-SE` in non-test frontend sources outside the documented allowlist

## 10. Verification

- [x] 10.1 Run `UV_NO_SYNC=1 uv run ruff check backend/ planner/ ml/ executor/` and `UV_NO_SYNC=1 uv run ruff format --check`; all clean
- [x] 10.2 Run `UV_NO_SYNC=1 uv run pyright`; zero errors
- [x] 10.3 Run `UV_NO_SYNC=1 uv run python -m pytest -q`; all pass
- [x] 10.4 Run `pnpm lint`, `pnpm typecheck`, `pnpm test` and `pnpm build` in `frontend/`; all pass, and `npx tsc --noEmit` reports 0 errors
- [x] 10.5 Run `openspec validate beta-exit-hardening`; valid
