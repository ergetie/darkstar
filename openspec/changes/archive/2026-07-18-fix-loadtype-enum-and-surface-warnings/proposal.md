## Why

Backend startup logs `Invalid load type 'current' for EV charger 'ev_charger_1', defaulting to binary` on every boot. Root cause: `backend/loads/base.py`'s `LoadType` enum (`BINARY`/`FIXED`/`VARIABLE`) was never extended with a `CURRENT` member when current-based EV charging (`ev_chargers[].type: "current"`) was introduced everywhere else (config validation, `config_migration.py`, planner, executor, frontend). The mislabeling is confined to the load-disaggregation dashboard/telemetry subsystem — actual charging control reads `type` directly from config and is unaffected — but it is a real, live bug producing wrong data in `/api/loads/debug` and recorder telemetry.

The same root cause also affects water heaters: the frontend's water heater "Load Type" dropdown (`EntityArrayEditor.tsx:575`) offers `"modulating"` as an option, which is likewise missing from `LoadType` and hits the identical silent-fallback-to-binary path in `backend/loads/service.py` — and unlike EV chargers, water heaters have **no existing config-validation check at all** for this field, so an invalid/unsupported water heater type produces no warning anywhere, not even the (already insufficient) hardcoded-tuple check EV chargers get.

Separately, this bug was only caught by manually reading dev logs, even though the app already has a global, proactive config-warning banner (`App.tsx` calls `POST /api/config/validate` on every page mount and renders any returned issue). That endpoint already validates EV charger `type` against a **hardcoded** `("binary", "current")` tuple — the same two values the runtime `LoadType` enum should recognize — but the two lists live independently and had already drifted apart. The gap isn't "no UI mechanism exists," it's that the existing mechanism's accepted-values list (where it exists at all) wasn't derived from the same source of truth as the runtime code it's supposed to protect against.

## What Changes

- Add `CURRENT = "current"` and `MODULATING = "modulating"` to the `LoadType` enum in `backend/loads/base.py` so both resolve correctly instead of raising `ValueError`.
- Remove the now-dead "defaulting to binary" fallback path in `backend/loads/service.py` for the `"current"` and `"modulating"` values (fallback remains for genuinely unrecognized/future-invalid values).
- Make `backend/api/routers/config.py`'s EV charger `type` validation derive its accepted-values set from the same source the runtime `LoadType` enum uses, instead of a separately hardcoded tuple, so a future drift between "config accepts X" and "runtime understands X" is caught by the existing `/api/config/validate` → `App.tsx` banner instead of silently degrading behavior.
- Add the equivalent water heater `type` validation to `backend/api/routers/config.py` (currently missing entirely), using the same shared source of truth.
- No new UI: the existing global config-warning banner is the surfacing mechanism; this change makes sure it stays trustworthy rather than adding a second one.

## Capabilities

### New Capabilities
- `load-type-integrity`: The load-disaggregation subsystem (`backend/loads/`) recognizes every load `type` value the frontend can produce for EV chargers and water heaters, and `/api/config/validate` validates both against that same runtime definition, so config-accepted values and runtime-understood values can't silently drift apart.

### Modified Capabilities
(none — the affected code has no prior formal spec coverage)

## Impact

- `backend/loads/base.py` — `LoadType` enum gains `CURRENT` and `MODULATING`.
- `backend/loads/service.py` — remove the `"current"`/`"modulating"`-triggers-fallback branches; keep fallback behavior for truly unknown values.
- `backend/api/routers/config.py` — EV charger type validation reads its accepted set from a single shared source instead of a hardcoded tuple; water heater type gains an equivalent validation check it currently lacks.
- No frontend changes — the existing banner already displays whatever `/api/config/validate` returns.
- No changes to planner/executor control logic (already correct).
