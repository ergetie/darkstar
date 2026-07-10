## Why

A post-merge review of `price-forecasting-module-4` (goal-based EV target charging) and `price-forecasting-module-5` (EV dashboard integration and scheduler sync) confirmed 11 functional defects that defeat the features' core promises: cars systematically stop short of target, HA-side schedule edits never sync (and get actively reverted), multi-day spreading only constrains today, and goal state handling has concurrency and shadowing bugs. All must be fixed before the EV charger is enabled in production.

## What Changes

- Fix energy-requirement double-count: delivered-today is only subtracted when no live SoC sensor exists (live SoC already reflects progress). Delivered-today becomes per-charger-aware or is gated to the single-charger case.
- Wire HA→Darkstar schedule sync: register `ha_ready_by_entity`/`ha_target_soc_entity` in the websocket monitored-entities map (the handler already exists). On reconnect, HA wins: read HA values and adopt sane (future-dated) ones instead of pushing the stale state file back to HA.
- Enforce per-day quotas in the solver for **every** in-horizon day (not just today), so multi-day spreading actually spreads; the shortfall constraint no longer forces the full multi-day requirement into the visible horizon.
- Include today (offset 0, remaining slots) in the multi-day price weights so "charge more on the cheap day" works for the only day previously enforced.
- **BREAKING**: Remove goal fields (`target_soc_percent`, `ready_by`, `repeat`, `ready_by_date`, `n_days`, and deprecated `departure_time`) from `config.yaml`/`config.default.yaml`. The dashboard/API (backed by `data/ev_multi_day_state.json`) is the sole source of truth for goals; config keeps only hardware facts. First boot without a goal uses safe defaults (no charging goal until one is set; UI prompts to set one).
- Fix `every_n_days`: one shared ready-by resolver (single default for `n_days`, no `date(2020,1,1)` magic anchor divergence) used by API, planner, and HA sync; `n_days` persisted through the planner writeback and returned by the API.
- Serialize state-file access: single lock (or single-writer ownership) for `data/ev_multi_day_state.json`; unique temp file per writer; preserve goals of chargers not processed in a run (e.g. temporarily disabled).
- Backend owns its HA HTTP session per event loop — stop borrowing/rebinding the executor's aiohttp session across threads; fix the leaked fallback client and bare `except: pass`.
- Frontend fixes: EV-tab lockout when no charger is configured, HA-Ingress-safe settings link, phantom default goal display, `'throttled'`→`'throttling'` dead check plus `stale_fallback` badge, local-timezone date handling (default date, `isToday`, weekday labels), post-save revert effect, error-state reset and fetch-race guard, stale `readyByDate`/`nDays` reset.
- Validation and consistency: real ISO-date validation with past/impossible dates rejected at the API, staleness rule aligned between GET API and planner, surplus EV energy counted against quota/requirement, net-excess sink cap accounts for concurrent battery charging.
- Test coverage: net-excess surplus constraint gets direct solver tests; pipeline goal-merge test exercises the real pipeline code (not a copy-paste); `n_days` round-trip test; HA-sync wiring test.
- Cheap hygiene from the review folded in where files are already touched (dead `get_ha_datetime` or use it, `_ = asyncio` removal, `str(None)`=="none" repeat collision, misc). Non-cheap leftovers recorded in `docs/BACKLOG.md`.

## Capabilities

### New Capabilities

(none — all changes fix requirements of existing capabilities)

### Modified Capabilities

- `ev-target-charging`: required-energy calculation must not double-count progress; goal source of truth moves entirely to state file/API (config goal fields removed).
- `multi-day-deferral-controller`: per-day quotas enforced for all in-horizon days; today's real price included in allocation weights; allocations clamped to physical bounds; `n_days` round-trips.
- `ha-schedule-sync`: HA→Darkstar runtime sync must actually fire; reconnect reconciliation is HA-wins with sanity checks; no stale push-back reverting user edits.
- `ev-schedule-api`: strict date validation; `n_days` persisted and returned; staleness semantics aligned with planner; backend-owned HA client session.
- `ev-dashboard-card`: correct local-timezone date handling; truthful goal/status display (no phantom goals, correct balancer badges); resilient fetch/error state.
- `dashboard-ev-display`: Resources card must never lock the user out of the Metrics tab when EV chargers are absent.
- `ev-surplus-charging`: net-excess cap accounts for concurrent battery charging; surplus energy counts toward daily quota; regression tests for the constraint.
- `per-device-ev-scheduling`: goal fields no longer read from per-charger config; delivered-energy attribution is per-charger-aware or explicitly single-charger-gated.

## Impact

- **Planner**: `planner/pipeline.py` (requirement calc, state persist/merge, resolver), `planner/solver/kepler.py` (quota constraints, net-excess cap), `planner/solver/adapter.py`, `planner/solver/types.py` (per-day quota input), `planner/strategy/multi_day_planner.py` (day-0 price, clamping).
- **Backend**: `backend/ha_socket.py` (entity registration, reconnect rule), `backend/api/routers/ev.py` (validation, `n_days`, session), `backend/core/ev_state.py` (locking), `backend/core/ha_client.py`.
- **Executor**: `executor/config.py` (goal-field parsing removed).
- **Frontend**: `EVChargingCard.tsx`, `CommandDomains.tsx`, `EntityArrayEditor.tsx`.
- **Config**: `config.default.yaml` goal fields removed (BREAKING for configs carrying goal fields — prod config verified to carry none).
- **Docs**: `docs/BACKLOG.md` gains deferred minor findings.
