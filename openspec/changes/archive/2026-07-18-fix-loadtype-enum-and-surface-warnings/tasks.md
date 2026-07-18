## 1. Fix the `LoadType` enum gap

- [x] 1.1 In `backend/loads/base.py`, add `CURRENT = "current"` and `MODULATING = "modulating"` members to the `LoadType` enum.
- [x] 1.2 In `backend/loads/service.py`, verify the EV charger branch (`_initialize_from_entity_arrays`, ~line 122-129) no longer hits the `ValueError` fallback for `type: "current"` — no code change expected here beyond the enum addition, but confirm the `try/except` still correctly handles a genuinely unknown future value.
- [x] 1.3 In `backend/loads/service.py`, verify the water heater branch (~line 76-82) no longer hits the `ValueError` fallback for `type: "modulating"`, same confirmation as 1.2.

## 2. Single source of truth for accepted load types

- [x] 2.1 In `backend/loads/base.py`, add a small shared constant/helper next to `LoadType` exposing the accepted `type` values per device kind (e.g. EV chargers accept `binary`/`current`; water heaters accept `binary`/`modulating`), derived from the enum rather than duplicated literals.
- [x] 2.2 In `backend/api/routers/config.py`, replace the hardcoded `ev_type not in ("binary", "current")` check (~line 607-616) with a check against the shared constant/helper from 2.1.
- [x] 2.3 In `backend/api/routers/config.py`, add a new water heater `type` validation check (mirroring the EV charger one) using the same shared constant/helper, since no such check exists today. Emit `severity: "warning"` (not `"error"`) so it doesn't block saves.

## 3. Tests

- [x] 3.1 Add/update a test in `tests/loads/` (or extend `tests/planner/test_load_disaggregation.py`) asserting `LoadDisaggregator` registers an `ev_chargers[]` entry with `type: "current"` as `LoadType.CURRENT`, with no warning logged.
- [x] 3.2 Add/update a test asserting a water heater entry with `type: "modulating"` registers as `LoadType.MODULATING`, with no warning logged.
- [x] 3.3 Add/update a test for `POST /api/config/validate` (or the underlying validation function) confirming an EV charger with an unsupported `type` still produces a warning after the refactor to the shared source.
- [x] 3.4 Add a new test for `POST /api/config/validate` confirming a water heater with an unsupported `type` now produces a warning (previously produced none).

## 4. Verification

- [x] 4.1 Run `pnpm run dev`, confirm the `Invalid load type 'current' for EV charger 'ev_charger_1', defaulting to binary` warning no longer appears in backend startup logs.
- [x] 4.2 Hit `GET /api/loads/debug` and confirm `ev_charger_1` reports type `current`, not `binary`.
- [x] 4.3 Run the full backend test suite and confirm no regressions in `tests/loads/`, `tests/planner/test_load_disaggregation.py`, `tests/executor/test_config.py`, `tests/config/test_give_way_migration.py`.
