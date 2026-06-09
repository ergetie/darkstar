## Why

CI gates merges on the API test subset only (`tests/api/test_api_routes.py`), so ~69 planner/executor/ML test files and strict pyright can regress silently while the build stays green (stabilization-review finding #3). The same review found the largest core modules have no tests (#5), operational warnings emitted via `print()` bypass logging (#11), and two runtime robustness gaps that make `database is locked` errors likely on some installs (#37, #38). This change raises the CI/runtime floor so the existing 1051-test suite actually protects the codebase — it is the foundation the other stabilization fix-changes rely on.

## What Changes

- **Expand CI to gate on the full test suite**, not just the API subset, and add **pyright strict as a merge gate** (currently local-only via pre-commit). (#3)
- **Add characterization tests** for the highest-risk untested core modules — `backend/ha_socket.py` and the planner→executor service wrappers — so runtime/glue bugs are caught. (#5)
- **Replace `print()` warnings with the structured logger** in library/service code, and add a lint guard forbidding `print` outside scripts/CLI. (#11)
- **Enable SQLite WAL mode at startup** for `planner_learning.db`, independent of whether the executor is enabled, so concurrent readers/writers don't block. (#37)
- **Move synchronous SQLite reads off the FastAPI event loop** in the price-forecast and executor-history routes, and add an explicit busy-timeout to the price connections. (#38)

## Capabilities

### New Capabilities
- `ci-quality-gate`: CI runs the complete Python test suite and enforces pyright strict as a required merge gate, so non-API regressions and type errors block the build.
- `database-concurrency-safety`: `planner_learning.db` runs in WAL mode from application startup, and synchronous SQLite access is kept off the async event loop with bounded busy-timeouts, so concurrent recorder/planner/ML/API access does not raise `database is locked` or stall request handling.

### Modified Capabilities
- `test-hygiene`: add requirements that (a) the highest-risk untested core infrastructure modules carry characterization tests, and (b) operational warnings use the structured logger rather than `print()`, enforced by a lint guard.

## Impact

- **CI / build:** `.github/workflows/ci.yml` (test scope + pyright job); merge protection now depends on the full suite passing.
- **Code:** `backend/learning/store.py` (WAL at startup), `backend/main.py` lifespan (call `ensure_wal_mode`), `backend/api/routers/price_forecast.py` + `backend/core/price_outlook.py` + `backend/api/routers/executor.py` (offload sync DB reads, add busy-timeout), `planner/inputs/weather.py` + `ml/evaluate.py` (print→logger), plus a lint rule.
- **Tests:** new test files for `backend/ha_socket.py` and the planner/executor service wrappers.
- **No behavior change** to planning, forecasting, or control logic — this is a CI, logging, and DB-concurrency hardening change.
- **Dependencies:** none added.
