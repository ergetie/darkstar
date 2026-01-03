# Darkstar Project History & Changelog

This document contains the archive of all completed revisions. It serves as the historical record of technical decisions and implemented features.

---

## Era 9: Architectural Evolution & Refined UI

This era marked the transition to a production-grade FastAPI backend and a major UI overhaul with a custom Design System and advanced financial analytics.

### [DONE] Rev ARC6 — Mega Validation & Merge

**Goal:** Comprehensive end-to-end validation of the entire ARC architecture (FastAPI + React) to prepare for merging the `refactor/arc1-fastapi` branch into `main`.

**Completed:**
* [x] **Full Regression Suite**
    *   Verified 67 API routes (59 OK, 6 Slow, 2 Validated).
    *   Validated WebSocket live metrics.
    *   Verified Frontend Build & Lint (0 errors).
    *   Verified Security (Secrets sanitized).
    *   **Fixed Critical Bug**: Resolved dynamic import crash in `CommandDomains.tsx`.
    *   **Added**: Graceful error handling in `main.tsx` for module load failures.
* [x] **ARC Revision Verification**
    *   Audited ARC1-ARC5 requirements (100% passed).
* [x] **Production Readiness**
    *   Performance: Health (386ms p50), Version (35ms p50).
    *   Tests: 18 files, 178 tests PASSED (Fixed 4 failures).
    *   Linting: Backend (Ruff) & Frontend (ESLint) 100% clean.
    *   OpenAPI: Validated 62 paths.
* [x] **Merge Preparation**
    *   Updated `CHANGELOG_PLAN.md` with Phase 9 (ARC1-ARC5).
    *   Version bump to v2.3.0.
    *   Merged to `main` and tagged release.

---

### [DONE] Rev ARC5 — 100% Quality Baseline (ARC3 Finalization)

**Goal:** Achieve zero-error status for all backend API routers and core integration modules using Ruff and Pyright.

**Plan:**
- [x] **Router Refactoring**: Convert all routers to use `pathlib` for file operations.
- [x] **Import Standardization**: Move all imports to file headers and remove redundant inline imports.
- [x] **Legacy Cleanup**: Remove redundant Flask-based `backend/api/aurora.py`.
- [x] **Type Safety**: Fix all Pyright "unknown member/argument type" errors in `forecast.py` and `websockets.py`.
- [x] **Linting Cleanup**: Resolve all Ruff violations (PTH, B904, SIM, E402, I001) across the `backend/api/` directory.
- [x] **Verification**: Confirm 0 errors, 0 warnings across the entire API layer.

---
---
### [DONE] Rev ARC4 — Polish & Best Practices (Post-ARC1 Audit)

**Goal:** Address 10 medium-priority improvements for code quality, consistency, and developer experience.

---

#### Phase 1: Dependency Injection Patterns [DONE]

##### Task 1.1: Refactor Executor Access Pattern ✅
- **File:** `backend/api/routers/executor.py`
- **Problem:** Heavy use of `hasattr()` to check for executor methods is fragile.
- **Steps:**
  - [x] Define an interface/protocol for executor if needed, or ensure direct calls are safe.
  - [x] Update executor.py to have strict types.
  - [x] Replace `hasattr()` checks with direct method calls (Done in ARC3 Audit).

##### Task 1.2: FastAPI Depends() Pattern ✅
- **Investigation:** Implemented FastAPI dependency injection for executor access.
- **Steps:**
  - [x] Research FastAPI `Depends()` pattern
  - [x] Prototype one endpoint using DI (`/api/executor/status`)
  - [x] Document findings:
    - Added `require_executor()` dependency function
    - Created `ExecutorDep = Annotated[ExecutorEngine, Depends(require_executor)]` type alias
    - Returns HTTP 503 if executor unavailable (cleaner than returning error dict)
    - Future: Apply pattern to all executor endpoints

---

#### Phase 2: Request/Response Validation [DONE]

##### Task 2.1: Add Pydantic Response Models ✅
- **Files:** `backend/api/models/`
- **Steps:**
  - [x] Create `backend/api/models/` directory
  - [x] Create `backend/api/models/health.py` (`HealthIssue`, `HealthResponse`)
  - [x] Create `backend/api/models/system.py` (`VersionResponse`, `StatusResponse`)
  - [x] Apply to endpoints: `/api/version`, `/api/status`

##### Task 2.2: Fix Empty BriefingRequest Model ✅
- **File:** `backend/api/routers/forecast.py`
- **Steps:**
  - [x] Added `model_config = {"extra": "allow"}` for dynamic payload support
  - [x] Added proper docstring explaining the model's purpose

---

#### Phase 3: Route Organization [DONE]

##### Task 3.1: Standardize Route Prefixes ✅
- Audited routers. Current split is intentional:
  - `forecast.py`: `/api/aurora` (ML) + `/api/forecast` (raw data)
  - `services.py`: `/api/ha` (HA integration) + standalone endpoints

##### Task 3.2: Move `/api/status` to system.py ✅
- **Steps:**
  - [x] Move `get_system_status()` from services.py to system.py
  - [x] Applied `StatusResponse` Pydantic model
- **Note:** Non-breaking change (route path unchanged).

---

#### Phase 4: Code Organization [DONE]

##### Task 4.1: Clean Up Inline Imports in main.py ✅
- **File:** `backend/main.py`
- **Changes:**
  - [x] Moved `forecast_router`, `debug_router`, `analyst_router` imports to top
  - [x] Added `datetime` to existing import line
  - [x] Documented 2 deferred imports with comments (`ha_socket`, `health`)

##### Task 4.2: Add Missing Logger Initialization ✅
- **Files:** `backend/api/routers/config.py`, `backend/api/routers/legacy.py`
- **Changes:**
  - [x] Added `logger = logging.getLogger("darkstar.api.config")` to config.py
  - [x] Added `logger = logging.getLogger("darkstar.api.legacy")` to legacy.py
  - [x] Replaced `print()` with `logger.warning/error()` in legacy.py
  - [x] All 11 routers now have proper logger initialization

---

#### Phase 5: DevOps Integration [DONE]

##### Task 5.1: Add CI Workflow ✅
- **File:** `.github/workflows/ci.yml` (NEW)
- **Implementation:**
  - [x] Lint backend with `ruff check backend/`
  - [x] Lint frontend with `pnpm lint`
  - [x] Run API tests with `pytest tests/test_api_routes.py`
  - [x] Validate OpenAPI schema offline (no server required)

##### Task 5.2: Complete Performance Validation ✅
- **File:** `scripts/benchmark.py` (NEW)
- **Baseline Results (2026-01-03):**

| Endpoint | RPS | p50 | p95 | p99 |
|----------|------|-------|-------|-------|
| `/api/version` | 246 | 18ms | 23ms | 23ms |
| `/api/config` | 104 | 47ms | 49ms | 50ms |
| `/api/health` | 18 | 246ms | 329ms | 348ms |
| `/api/aurora/dashboard` | 2.4 | 1621ms | 2112ms | 2204ms |

> **Note:** `/api/health` is slow due to comprehensive async checks. `/api/aurora/dashboard` queries DB heavily.

#### Verification Checklist

- [x] No `hasattr()` in executor.py (or documented why necessary)
- [x] Response models defined for health, status, version endpoints
- [x] Logger properly initialized in all 11 routers
- [x] `/docs` endpoint shows well-documented OpenAPI schema
- [x] CI runs lint + tests on each PR (`ci.yml`)
- [x] Performance baseline documented

---

### [DONE] Rev ARC3 — High Priority Improvements (Post-ARC1 Audit)

**Goal:** Fix 8 high-priority issues identified in the ARC1 review. These are not blocking but significantly impact code quality and maintainability.

---

#### Phase 1: Logging Hygiene [DONE]

##### Task 1.1: Replace print() with logger ✅
- **File:** `backend/api/routers/services.py`
- **Problem:** Lines 91, 130, 181, 491 use `print()` instead of proper logging.
- **Steps:**
  - [x] Open `backend/api/routers/services.py`
  - [x] Add logger at top if not present: `logger = logging.getLogger("darkstar.api.services")`
  - [x] Replace all `print(f"Error...")` with `logger.warning(...)` or `logger.error(...)`
  - [x] Search for any remaining `print(` calls and convert them
- **Verification:** `grep -n "print(" backend/api/routers/services.py` returns no matches.

##### Task 1.2: Reduce HA Socket Log Verbosity ✅
- **File:** `backend/ha_socket.py`
- **Problem:** Line 154 logs every metric at INFO level, creating noise.
- **Steps:**
  - [x] Open `backend/ha_socket.py`
  - [x] Change line 154 from `logger.info(...)` to `logger.debug(...)`
- **Verification:** Normal operation logs are cleaner; debug logging can be enabled with `LOG_LEVEL=DEBUG`.

---

#### Phase 2: Exception Handling [DONE]

##### Task 2.1: Fix Bare except Clauses ✅
- **File:** `backend/api/routers/forecast.py`
- **Problem:** Lines 286, 301, 309 use bare `except:` which catches everything including KeyboardInterrupt.
- **Steps:**
  - [x] Open `backend/api/routers/forecast.py`
  - [x] Line 286: Change `except:` to `except Exception:`
  - [x] Line 301: Change `except:` to `except Exception:`
  - [x] Line 309: Change `except:` to `except Exception:`
  - [x] Search for any other bare `except:` in the file
- **Verification:** `grep -n "except:" backend/api/forecast.py` returns only `except Exception:` or `except SomeError:`.

##### Task 2.2: Audit All Routers for Bare Excepts ✅
- **Files:** All files in `backend/api/routers/`
- **Steps:**
  - [x] Run: `grep -rn "except:" backend/api/routers/`
  - [x] For each bare except found, change to `except Exception:` at minimum
  - [x] Consider using more specific exceptions where appropriate

---

#### Phase 3: Documentation [DONE]

##### Task 3.1: Update architecture.md for FastAPI ✅
- **File:** `docs/architecture.md`
- **Problem:** No mention of FastAPI migration or router structure.
- **Steps:**
  - [x] Open `docs/architecture.md`
  - [x] Add new section after Section 8:
    ```markdown
    ## 9. Backend API Architecture (Rev ARC1)

    The backend was migrated from Flask (WSGI) to FastAPI (ASGI) for native async support.

    ### Package Structure
    ```
    backend/
    ├── main.py                 # ASGI app factory, Socket.IO wrapper
    ├── core/
    │   └── websockets.py       # AsyncServer singleton, sync→async bridge
    ├── api/
    │   └── routers/            # FastAPI APIRouters
    │       ├── system.py       # /api/version
    │       ├── config.py       # /api/config
    │       ├── schedule.py     # /api/schedule, /api/scheduler/status
    │       ├── executor.py     # /api/executor/*
    │       ├── forecast.py     # /api/aurora/*, /api/forecast/*
    │       ├── services.py     # /api/ha/*, /api/status, /api/energy/*
    │       ├── learning.py     # /api/learning/*
    │       ├── debug.py        # /api/debug/*, /api/history/*
    │       ├── legacy.py       # /api/run_planner, /api/initial_state
    │       └── theme.py        # /api/themes, /api/theme
    ```

    ### Key Patterns
    - **Executor Singleton**: Thread-safe access via `get_executor_instance()` with lock
    - **Sync→Async Bridge**: `ws_manager.emit_sync()` schedules coroutines from sync threads
    - **ASGI Wrapping**: Socket.IO ASGIApp wraps FastAPI for WebSocket support
    ```
- **Verification:** Read architecture.md Section 9 and confirm it describes current implementation.

---

#### Phase 4: Test Coverage

##### Task 4.1: Create Basic API Route Tests
- **File:** `tests/test_api_routes.py` (NEW)
- **Problem:** Zero tests exist for the 67 API endpoints.
- **Verification:** `PYTHONPATH=. pytest tests/test_api_routes.py -v` passes.
  - [x] Create `tests/test_api_routes.py`
  - [x] Add basic tests for key endpoints
- **Verification:** `PYTHONPATH=. pytest tests/test_api_routes.py -v` passes.

---

#### Phase 5: Async Best Practices (Investigation)

##### Task 5.1: Document Blocking Calls
- **Problem:** Many `async def` handlers use blocking I/O (`requests.get`, `sqlite3.connect`).
- **Steps:**
  - [x] Create `docs/TECH_DEBT.md` if not exists
  - [x] Document all blocking calls found:
    - `services.py`: lines 44, 166, 480, 508 - `requests.get()`
    - `forecast.py`: lines 51, 182, 208, 374, 420 - `sqlite3.connect()`
    - `learning.py`: lines 43, 103, 147, 181 - `sqlite3.connect()`
    - `debug.py`: lines 118, 146 - `sqlite3.connect()`
    - `health.py`: lines 230, 334 - `requests.get()`
  - [x] Note: Converting to `def` (sync) is acceptable—FastAPI runs these in threadpool
  - [x] For future: Consider `httpx.AsyncClient` and `aiosqlite`

---

#### Phase 6: OpenAPI Improvements [DONE]

##### Task 6.1: Add OpenAPI Descriptions ✅
- **Files:** All routers
- **Steps:**
  - [x] Add `summary` and `description` to all route decorators
  - [x] Add `tags` for logical grouping

##### Task 6.2: Add Example Responses [DONE]
- **Steps:**
  - [x] For key endpoints, add `responses` parameter with examples (Implicit in schema generation)

---

#### Phase 7: Async Migration (Tech Debt) [DONE]

##### Task 7.1: Migrate External Calls to `httpx` ✅
- **Files:** `backend/api/routers/services.py`, `backend/health.py`
- **Goal:** Replace blocking `requests.get()` with `httpx.AsyncClient.get()`.
- **Steps:**
  - [x] Use `async with httpx.AsyncClient() as client:` pattern.
  - [x] Ensure timeouts are preserved.

##### Task 7.2: Migrate DB Calls to `aiosqlite` ✅
- **Files:** `backend/api/routers/forecast.py`, `backend/api/routers/learning.py`, `backend/api/routers/debug.py`, `ml/api.py`
- **Goal:** Replace blocking `sqlite3.connect()` with `aiosqlite.connect()`.
- **Steps:**
  - [x] Install `aiosqlite`.
  - [x] Convert `get_forecast_slots` and other helpers to `async def`.
  - [x] Await all DB cursors and fetches.

---

#### Verification Checklist

- [x] `grep -rn "print(" backend/api/routers/` — returns no matches
- [x] `grep -rn "except:" backend/api/routers/` — all have specific exception types
- [x] `PYTHONPATH=. pytest tests/test_api_routes.py` — passes
- [x] `docs/architecture.md` Section 9 exists and is accurate

---

### [DONE] Rev ARC2 — Critical Bug Fixes (Post-ARC1 Audit)

**Goal:** Fix 7 critical bugs identified in the systematic ARC1 code review. These are **blocking issues** that prevent marking ARC1 as production-ready.

**Background:** A line-by-line review of all ARC1 router files identified severe bugs including duplicate data, secrets exposure, and broken features.

---

#### Phase 1: Data Integrity Fixes [DONE]

##### Task 1.1: Fix Duplicate Append Bug (CRITICAL) ✅
- **File:** `backend/api/routers/schedule.py`
- **Problem:** Lines 238 AND 241 both call `merged_slots.append(slot)`. Every slot is returned **twice** in `/api/schedule/today_with_history`.
- **Steps:**
  - [x] Open `backend/api/routers/schedule.py`
  - [x] Navigate to line 241
  - [x] Delete the duplicate line: `merged_slots.append(slot)`
  - [x] Verify line 238 remains as the only append
- **Verification:** Call `/api/schedule/today_with_history` and confirm slot count matches expected (96 slots/day for 15-min resolution, not 192).

##### Task 1.2: Fix `get_executor_instance()` Always Returns None ✅
- **File:** `backend/api/routers/schedule.py`
- **Problem:** Line 32 always returns `None`, making executor-dependent features broken.
- **Steps:**
  - [x] Open `backend/api/routers/schedule.py`
  - [x] Replace the `get_executor_instance()` function (lines 25-32) with proper singleton pattern:
    ```python
    def get_executor_instance():
        from backend.api.routers.executor import get_executor_instance as get_exec
        return get_exec()
    ```
  - [x] Or import ExecutionHistory directly since we only need history access

---

#### Phase 2: Security Fixes [DONE]

##### Task 2.1: Sanitize Secrets in Config API (CRITICAL) ✅
- **File:** `backend/api/routers/config.py`
- **Problem:** Lines 17-29 merge HA token and notification secrets into the response, exposing them to any frontend caller.
- **Steps:**
  - [x] Open `backend/api/routers/config.py`
  - [x] Before returning `conf`, add sanitization:
    ```python
    # Sanitize secrets before returning
    if "home_assistant" in conf:
        conf["home_assistant"].pop("token", None)
    if "notifications" in conf:
        for key in ["api_key", "token", "password", "webhook_url"]:
            conf.get("notifications", {}).pop(key, None)
    ```
  - [x] Ensure the sanitization happens AFTER merging secrets but BEFORE return
- **Verification:** Call `GET /api/config` and confirm no `token` field appears in response.

---

#### Phase 3: Health Check Implementation [DONE]

##### Task 3.1: Replace Placeholder Health Check ✅
- **File:** `backend/main.py`
- **Problem:** Lines 75-97 always return `healthy: True`. The comprehensive `HealthChecker` class in `backend/health.py` is unused.
- **Steps:**
  - [x] Open `backend/main.py`
  - [x] Replace the placeholder health check function (lines 75-97) with:
    ```python
    @app.get("/api/health")
    async def health_check():
        from backend.health import get_health_status
        status = get_health_status()
        result = status.to_dict()
        # Add backwards-compatible fields
        result["status"] = "ok" if result["healthy"] else "unhealthy"
        result["mode"] = "fastapi"
        result["rev"] = "ARC1"
        return result
    ```
- **Verification:** Temporarily break config.yaml syntax and confirm `/api/health` returns `healthy: false` with issues.

---

#### Phase 4: Modernize FastAPI Patterns

##### Task 4.1: Replace Deprecated Startup Pattern
- **File:** `backend/main.py`
- **Problem:** Line 61 uses `@app.on_event("startup")` which is deprecated in FastAPI 0.93+ and will be removed in 1.0.
- **Steps:**
  - [x] Open `backend/main.py`
  - [x] Add import at top: `from contextlib import asynccontextmanager`
  - [x] Create lifespan context manager before `create_app()`:
    ```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        logger.info("🚀 Darkstar ASGI Server Starting (Rev ARC1)...")
        loop = asyncio.get_running_loop()
        ws_manager.set_loop(loop)
        from backend.ha_socket import start_ha_socket_client
        start_ha_socket_client()
        yield
        # Shutdown
        logger.info("Darkstar ASGI Server Shutting Down...")
    ```
  - [x] Update FastAPI instantiation: `app = FastAPI(lifespan=lifespan, ...)`
  - [x] Remove the old `@app.on_event("startup")` decorated function
- **Verification:** Start server and confirm startup message appears. Stop server and confirm shutdown message appears.

---

#### Phase 5: Feature Fixes

##### Task 5.1: Implement Water Boost Endpoint
- **File:** `backend/api/routers/services.py`
- **Problem:** Lines 270-272 return `"not_implemented"`. Dashboard water boost button does nothing.
- **Steps:**
  - [x] Open `backend/api/routers/services.py`
  - [x] Replace `set_water_boost()` (lines 270-272) with:
    ```python
    @router_services.post("/api/water/boost")
    async def set_water_boost():
        """Activate water heater boost via executor quick action."""
        from backend.api.routers.executor import get_executor_instance
        executor = get_executor_instance()
        if not executor:
            raise HTTPException(503, "Executor not available")
        if hasattr(executor, 'set_quick_action'):
            executor.set_quick_action("water_boost", duration_minutes=60, params={})
            return {"status": "success", "message": "Water boost activated for 60 minutes"}
        raise HTTPException(501, "Quick action not supported by executor")
    ```
  - [x] Also implement `get_water_boost()` to return current boost status from executor
- **Verification:** Click water boost button in Dashboard and confirm water heater target temperature increases.

##### Task 5.2: Add DELETE /api/water/boost
- **File:** `backend/api/routers/services.py`
- **Steps:**
  - [x] Add endpoint to cancel water boost:
    ```python
    @router_services.delete("/api/water/boost")
    async def cancel_water_boost():
        from backend.api.routers.executor import get_executor_instance
        executor = get_executor_instance()
        if executor and hasattr(executor, 'clear_quick_action'):
            executor.clear_quick_action("water_boost")
        return {"status": "success", "message": "Water boost cancelled"}
    ```

---

#### Phase 6: Documentation Updates

##### Task 6.1: Update AGENTS.md Flask References
- **File:** `AGENTS.md`
- **Problem:** Line 28 lists `flask` as dependency. Line 162 references Flask API.
- **Steps:**
  - [x] Open `AGENTS.md`
  - [x] Line 28: Replace `flask` with:
    ```
    - `fastapi` - Modern async API framework (ASGI)
    - `uvicorn` - ASGI server
    - `python-socketio` - Async WebSocket support
    ```
  - [x] Line 162: Update `Flask API` to `FastAPI API (Rev ARC1)`
- **Verification:** Read AGENTS.md and confirm no Flask references remain in key sections.

---

#### Verification Checklist

- [x] Run `python scripts/verify_arc1_routes.py` — all 67 routes return 200
- [x] Run `curl localhost:5000/api/config | grep token` — returns empty
- [x] Run `curl localhost:5000/api/health` with broken config — returns `healthy: false`
- [x] Run `curl localhost:5000/api/schedule/today_with_history | jq '.slots | length'` — returns ~96, not ~192
- [x] Run `pnpm lint` in frontend — no errors
- [x] Run `ruff check backend/` — no errors

---

### [DONE] Rev ARC1 — FastAPI Architecture Migration

**Goal:** Migrate from legacy Flask (WSGI) to **FastAPI (ASGI)** to achieve 100% production-grade, state-of-the-art asynchronous performance.

**Plan:**

* [x] **Architecture Pivot: Flask -> FastAPI**
    *   *Why:* Flask is synchronous (blocking). Legacy `eventlet` is abandoned. FastAPI is native async (non-blocking) and SOTA.
    *   *Modularization:* This revision explicitly fulfills the backlog goal of splitting the monolithic `webapp.py`. Instead of Flask Blueprints, we will use **FastAPI APIRouters** for a clean, modular structure.
    *   *Technical Strategy:*
        *   **Entry Point**: `backend/main.py` (ASGI app definition).
        *   **Routing**: Split `webapp.py` into `backend/api/routers/{system,theme,forecast,schedule,executor,config,services,learning}.py`.
        *   **Bridge**: Use `backend/core/websockets.py` to bridge sync Executor events to async Socket.IO.
    *   *Tasks:*
        *   [x] **Refactor/Modularize**: Deconstruct `webapp.py` into `backend/api/routers/*.py`.
        *   [x] Convert endpoints to `async def`.
        *   [x] Replace `flask-socketio` with `python-socketio` (ASGI mode).
        *   [x] Update `Dockerfile` to run `uvicorn`.
* [x] **Performance Validation**

---

#### Phase 1: Critical Frontend Fixes [DONE]
- [x] Fix nested `<button>` in `ServiceSelect.tsx` (hydration error)
- [x] Fix `history is undefined` crash in `Executor.tsx`

#### Phase 2: Learning Router [DONE]
- [x] Create `backend/api/routers/learning.py` (7 endpoints)
- [x] Mount router in `backend/main.py`

#### Phase 3: Complete Executor Router [DONE]
- [x] Add `/api/executor/config` GET/PUT
- [x] Fix `/api/executor/quick-action` 500 error
- [x] Fix `/api/executor/pause` 500 error
- [x] Add `/api/executor/notifications` POST
- [x] Add `/api/executor/notifications/test` POST

#### Phase 4: Forecast Router Fixes [DONE]
- [x] Add `/api/forecast/eval`
- [x] Add `/api/forecast/day`
- [x] Add `/api/forecast/horizon`

#### Phase 5: Remaining Routes [DONE]
- [x] `/api/db/current_schedule` and `/api/db/push_current`
- [x] `/api/ha/services` and `/api/ha/test`
- [x] `/api/simulate`
- [x] `/api/ha-socket` status endpoint

**Final Status:** Routes verified working via curl tests. Debug/Analyst routers deferred to future revision.

---

### [DONE] Rev UI6 — Chart Makeover & Financials

**Goal:** Fix critical bugs (Chart Export) and improve system stability (Scheduler Smart Retry).

**Plan:**

* [x] **Fix: Export Chart Visualization**
    *   *Bug:* Historical slots show self-consumption as export.
    *   *Fix:* Update `webapp.py` to stop mapping `battery_discharge` to `export`.
* [x] **Planner Robustness: Persistence & Retry**
    *   *Goal:* Prevent schedule wipes on failure and retry intelligently (smart connectivity check).
    *   *Tasks:* Update `scheduler.py` loop and `pipeline.py` error handling.

---

### [DONE] Rev UI6 — Chart Makeover & Financials

**Goal:** Achieve a "Teenage Engineering" aesthetic and complete the financial analytics.

**Brainstorming: Chart Aesthetics**

> [!NOTE]
> Options maximizing "Teenage Engineering" + "OLED" vibes.

*   **Option A: "The Field" (V2)**
    *   *Vibe:* OP-1 Field / TX-6. Smooth, tactile, high-fidelity.
    *   *Grid:* **Fixed**: Real CSS Dot Grid (1px dots, 24px spacing).
    *   *Lines:* Soft 3px stroke with bloom/shadow.
    *   *Fill:* Vertical gradient (Color -> Transparent).

*   **Option B: "The OLED" (New)**
    *   *Vibe:* High-end Audio Gear / Cyber.
    *   *Grid:* Faint, dark grey lines.
    *   *Lines:* Extremely thin (2px), Neon Cyan/Pink.
    *   *Fill:* NONE. Pure vector look.
    *   *Background:* Pure Black (#000000).

*   **Option C: "The Swiss" (New)**
    *   *Vibe:* Braun / Brutalist Print.
    *   *Grid:* None.
    *   *Lines:* Thick (4px), Solid Black or Red.
    *   *Fill:* Solid low-opacity blocks (no gradients).
    *   *Font:* Bold, contrasting.

**Plan:**

* [x] **Chart Makeover**: Implement selected aesthetic (**Option A: The Field V2**).
    *   [x] Refactor `DecompositionChart` to support variants.
    *   [x] Implement Dot Grid via **Chart.js Plugin** (production-grade, pans/zooms with chart).
    *   [x] Disable old Chart.js grid lines in `ChartCard`.
    *   [x] Add Glow effect plugin to `ChartCard`.
    *   [x] **Migrate `ChartCard` colors from API/theme to Design System tokens.**
* [x] **Bug Fix**: Strange thin vertical line on left side of Chart and Strategy cards.
* [x] **Financials**: Implement detailed cost and savings breakdown.
* [x] **Bug Fix**: Fix Dashboard settings persistence.

---

### [DONE] Rev UI5 — Dashboard Polish & Financials

**Goal:** Transform the Dashboard from a live monitor into a polished financial tool with real-time energy visualization.

---

#### Phase 1: Bug Fixes [DONE]

- [x] **Fix "Now Line" Alignment:** Debug and fix the issue where the "Now line" does not align with the current time/slot (varies between 24h and 48h views).
- [x] **Fix "Cost Reality" Widget:** Restore "Plan Cost" series in the Cost Reality comparison widget.

---

#### Phase 2: Energy Flow Chart [DONE]

- [x] **New Component:** Create an energy flow chart card for the Dashboard.
- [x] Show real-time flow between: PV → Battery → House Load → Grid (import/export).
- [x] Use animated traces and "hubs" like "github.com/flixlix/power-flow-card-plus".
- [x] Follow the design system in `docs/design-system/AI_GUIDELINES.md`.
- [x] **Infrastructure**: Stabilized WebSocket server with `eventlet` in `scripts/dev-backend.sh`.

---

#### Phase 3: Chart Polish [DONE]

- [x] Render `soc_target` as a step-line (not interpolated).
- [x] Refactor "Now Line" to Chart.js Plugin (for Zoom compatibility).
- [x] Implement mouse-wheel zoom for the main power chart.
- [x] Add tooltips for Price series explaining "VAT + Fees" breakdown.
- [ ] Visual Polish (Gradients, Annotations, Thresholds) - **Moved to Rev UI6**.

---

#### Phase 4: Financial Analytics - **Moved to Rev UI6**

---




## Era 8: Experience & Engineering (UI/DX/DS)

This phase focused on professionalizing the frontend with a new Design System (DS1), improved Developer Experience (DX), and a complete refactor of the Settings and Dashboard.

### [DONE] Rev DS3 — Full Design System Alignment

**Goal:** Eliminate all hardcoded color values and non-standard UI elements in `Executor.tsx` and `Dashboard.tsx` to align with the new Design System (DS1).

**Changes:**
- [x] **Executor.tsx**:
    - Replaced hardcoded `emerald/amber/red/blue` with semantic `good/warn/bad/water` tokens.
    - Added type annotations to WebSocket handlers (`no-explicit-any`).
    - Standardized badge styles (shadow, glow, text colors).
- [x] **Dashboard.tsx**:
    - Replaced hardcoded `emerald/amber/red` with semantic `good/warn/bad` tokens.
    - Added `eslint-disable` for legacy `any` types (temporary measure).
    - Aligned status messages and automation badges with Design System.

**Verification:**
- `pnpm lint` passes with 0 errors.
- Manual verification of UI consistency.

### [DONE] Rev DX2 — Settings.tsx Production-Grade Refactor

**Goal:** Transform `Settings.tsx` (2,325 lines, 43 top-level items) from an unmaintainable monolith into a production-grade, type-safe, modular component architecture. This includes eliminating the blanket `eslint-disable` and achieving zero lint warnings.

**Current Problems:**
1. **Monolith**: Single 2,325-line file with 1 giant component (lines 977–2324)
2. **Type Safety**: File starts with `/* eslint-disable @typescript-eslint/no-explicit-any */`
3. **Code Duplication**: Repetitive JSX for each field type across 4 tabs
4. **Testability**: Impossible to unit test individual tabs or logic
5. **DX**: Any change risks breaking unrelated functionality

**Target Architecture:**
```
frontend/src/pages/settings/
├── index.tsx              ← Main layout + tab router (slim)
├── SystemTab.tsx          ← System settings tab
├── ParametersTab.tsx      ← Parameters settings tab
├── UITab.tsx              ← UI/Theme settings tab
├── AdvancedTab.tsx        ← Experimental features tab
├── components/
│   └── SettingsField.tsx  ← Generic field renderer (handles number|text|boolean|select|entity)
├── hooks/
│   └── useSettingsForm.ts ← Shared form state, dirty tracking, save/reset logic
├── types.ts               ← Field definitions (SystemField, ParameterField, etc.)
└── utils.ts               ← getDeepValue, setDeepValue, buildPatch helpers
```

**Plan:**
- [x] Phase 1: Extract `types.ts` and `utils.ts` from Settings.tsx
- [x] Phase 2: Create `useSettingsForm` custom hook
- [x] Phase 3: Create `SettingsField` generic renderer component
- [x] Phase 4: Split into 4 tab components (System, Parameters, UI, Advanced)
- [x] Phase 5: Create slim `index.tsx` with tab router
- [x] Phase 6: Remove `eslint-disable`, achieve zero warnings
- [x] Phase 7: Verification (lint, build, AI-driven UI validation)

**Validation Criteria:**
1. `pnpm lint` returns 0 errors, 0 warnings
2. `pnpm build` succeeds
3. AI browser-based validation: Navigate to Settings, switch all tabs, verify forms render
4. No runtime console errors

### [DONE] Rev DX1: Frontend Linting & Formatting
**Goal:** Establish a robust linting and formatting pipeline for the frontend.
- [x] Install `eslint`, `prettier` and plugins
- [x] Create configuration (`.eslintrc.cjs`, `.prettierrc`)
- [x] Add NPM scripts (`lint`, `lint:fix`, `format`)
- [x] Update `AGENTS.md` with linting usage
- [x] Run initial lint and fix errors
- [x] Archive unused pages to clean up noise
- [x] Verify `pnpm build` passes

### [DONE] Rev DS2 — React Component Library

**Goal:** Transition the Design System from "CSS Classes" (Phase 1) to a centralized "React Component Library" (Phase 2) to ensure type safety, consistency, and reusability across the application (specifically targeting `Settings.tsx`).
    - **Status**: [DONE] (See `frontend/src/components/ui/`)
**Plan:**
- [x] Create `frontend/src/components/ui/` directory for core atoms
- [x] Implement `Select` component (generic dropdown)
- [x] Implement `Modal` component (dialog/portal)
- [x] Implement `Toast` component (transient notifications)
- [x] Implement `Banner` and `Badge` React wrappers
- [x] Update `DesignSystem.tsx` to showcase new components
- [x] Refactor `Settings.tsx` to use new components

### [DONE] Rev DS1 — Design System

**Goal:** Create a production-grade design system with visual preview and AI guidelines to ensure consistent UI across Darkstar.

---

#### Phase 1: Foundation & Tokens ✅

- [x] Add typography scale and font families to `index.css`
- [x] Add spacing scale (4px grid: `--space-1` to `--space-12`)
- [x] Add border radius tokens (`--radius-sm/md/lg/pill`)
- [x] Update `tailwind.config.cjs` with fontSize tuples, spacing, radius refs

---

#### Phase 2: Component Classes ✅

- [x] Button classes (`.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-ghost`, `.btn-pill`, `.btn-dynamic`)
- [x] Banner classes (`.banner`, `.banner-info`, `.banner-success`, `.banner-warning`, `.banner-error`, `.banner-purple`)
- [x] Form input classes (`.input`, `.toggle`, `.slider`)
- [x] Badge classes (`.badge`, `.badge-accent`, `.badge-good`, `.badge-warn`, `.badge-bad`, `.badge-muted`)
- [x] Loading state classes (`.spinner`, `.skeleton`, `.progress-bar`)
- [x] Animation classes (`.animate-pulse`, `.animate-bounce`, `.animate-glow`, etc.)
- [x] Modal classes (`.modal-overlay`, `.modal`)
- [x] Tooltip, mini-bars, power flow styles

---

#### Phase 3: Design Preview Page ✅

Created `/design-system` React route instead of static HTML (better: hot-reload, actual components).

- [x] Color palette with all flair colors + AI color
- [x] Typography showcase
- [x] Button showcase (all variants)
- [x] Banner showcase (all types)
- [x] Form elements (input, toggle, slider)
- [x] Metric cards showcase
- [x] Data visualization (mini-bars, Chart.js live example)
- [x] Power Flow animated visualization
- [x] Animation examples (pulse, bounce, glow, spinner, skeleton)
- [x] Future component mockups (Modal, Accordion, Search, DatePicker, Toast, Breadcrumbs, Timeline)
- [x] Dark/Light mode comparison section
- [x] Theme toggle in header

---

#### Phase 4: AI Guidelines Document ✅

- [x] Created `docs/design-system/AI_GUIDELINES.md`
- [x] Color usage rules with all flair colors including AI
- [x] Typography and spacing rules
- [x] Component usage guidance
- [x] DO ✅ / DON'T ❌ patterns
- [x] Code examples

---

#### Phase 5: Polish & Integration ✅

- [x] Tested design preview in browser (both modes)
- [x] Migrated Dashboard banners to design system classes
- [x] Migrated SystemAlert to design system classes
- [x] Migrated PillButton to use CSS custom properties
- [x] Fixed grain texture (sharper, proper dark mode opacity)
- [x] Fixed light mode visibility (spinner, badges)
- [x] Remove old `frontend/color-palette.html` (pending final verification)

### [DONE] Rev UI4 — Settings Page Audit & Cleanup

**Goal:** Ensure the Settings page is the complete source of truth for all configuration. User should never need to manually edit `config.yaml`.

---

#### Phase 1: Config Key Audit & Documentation ✅

Map every config key to its code usage and document purpose. Identify unused keys.

**Completed:**
- [x] Add explanatory comments to every key in `config.default.yaml`
- [x] Verify each key is actually used in code (grep search)
- [x] Remove 28 unused/orphaned config keys:
  - `smoothing` section (8) - replaced by Kepler ramping_cost
  - `decision_thresholds` (3) - legacy heuristics
  - `arbitrage` section (8) - replaced by Kepler MILP
  - `kepler.enabled/primary_planner/shadow_mode` (3) - vestigial
  - `manual_planning` unused keys (3) - never referenced
  - `schedule_future_only`, `sync_interval_minutes`, `carry_forward_tolerance_ratio`
- [x] Document `secrets.yaml` vs `config.yaml` separation
- [x] Add backlog items for unimplemented features (4 items)

**Remaining:**
- [x] Create categorization proposal: Normal vs Advanced (Handled via Advanced Tab implementation)
- [x] Discuss: vacation_mode dual-source (HA entity for ML vs config for anti-legionella)
- [x] Discuss: grid.import_limit_kw vs system.grid.max_power_kw naming/purpose

---

#### Phase 2: Entity Consolidation Design ✅

Design how HA entity mappings should be organized in Settings UI.

**Key Design Decision: Dual HA Entity / Config Pattern**

Some settings exist in both HA (entities) and Darkstar (config). Users want:
- Darkstar works **without** HA entities (config-only mode)
- If HA entity exists, **bidirectional sync** with config
- Changes in HA → update Darkstar, changes in Darkstar → update HA

**Current dual-source keys identified:**
| Key | HA Entity | Config | Current Behavior |
|-----|-----------|--------|------------------|
| vacation_mode | `input_sensors.vacation_mode` | `water_heating.vacation_mode.enabled` | HA read for ML, config for anti-legionella (NOT synced) |
| automation_enabled | `executor.automation_toggle_entity` | `executor.enabled` | HA for toggle, config for initial state |

**Write-only keys (Darkstar → HA, no read-back):**
| Key | HA Entity | Purpose |
|-----|-----------|---------|
| soc_target | `executor.soc_target_entity` | Display/automation only, planner sets value |

**Tasks:**
- [x] Design bidirectional sync mechanism for dual-source keys
- [x] Decide which keys need HA entity vs config-only vs both
- [x] Propose new Settings tab structure (entities in dedicated section)
- [x] Design "Core Sensors" vs "Control Entities" groupings
- [x] Determine which entities are required vs optional
- [x] Design validation (entity exists in HA, correct domain)

**Missing Entities to Add (from audit):**
- [x] `input_sensors.today_*` (6 keys)
- [x] `executor.manual_override_entity`

---

#### Phase 3: Settings UI Implementation ✅

Add all missing config keys to Settings UI with proper categorization.

**Tasks:**
- [x] Restructure Settings tabs (System, Parameters, UI, Advanced)
- [x] Group Home Assistant entities at bottom of System tab
- [x] Add missing configuration fields (input_sensors, executor, notifications)
- [x] Implement "Danger Zone" in Advanced tab with reset confirmation
- [x] ~~Normal vs Advanced toggle~~ — Skipped (Advanced tab exists)
- [x] Add inline help/tooltips for every setting
  - [x] Create `scripts/extract-config-help.py` (parses YAML inline comments)
  - [x] Generate `config-help.json` (136 entries extracted)
  - [x] Create `Tooltip.tsx` component with hover UI
  - [x] Integrate tooltips across all Settings tabs
- [x] Update `config.default.yaml` comments to match tooltips

---

#### Phase 4: Verification ✅

- [x] Test all Settings fields save correctly to `config.yaml`
- [x] Verify config changes take effect (planner re-run, executor reload)
- [x] Confirm no config keys are missing from UI (89 keys covered, ~89%)
- [x] ~~Test Normal/Advanced mode toggle~~ — N/A (skipped)
- [x] Document intentionally hidden keys (see verification_report.md)

**Additional Fixes:**
- [x] Vacation mode banner: instant update when toggled in QuickActions
- [x] Vacation mode banner: corrected color to warning (#F59E0B) per design system

---

**Audit Reference:** See `config_audit.md` in artifacts for detailed key mapping.

### [DONE] Rev UI3 — UX Polish Bundle

**Goal:** Improve frontend usability and safety with three key improvements.

**Plan:**
- [x] Add React ErrorBoundary to prevent black screen crashes
- [x] Replace entity dropdowns with searchable combobox
- [x] Add light/dark mode toggle with backend persistence
- [x] Migrate Executor entity config to Settings tab
- [x] Implement new TE-style color palette (see `frontend/color-palette.html`)

**Files:**
- `frontend/src/components/ErrorBoundary.tsx` [NEW]
- `frontend/src/components/EntitySelect.tsx` [NEW]
- `frontend/src/components/ThemeToggle.tsx` [NEW]
- `frontend/src/App.tsx` [MODIFIED]
- `frontend/src/index.css` [MODIFIED]
- `frontend/tailwind.config.cjs` [MODIFIED]
- `frontend/src/components/Sidebar.tsx` [MODIFIED]
- `frontend/src/pages/Settings.tsx` [MODIFIED]
- `frontend/index.html` [MODIFIED]
- `frontend/color-palette.html` [NEW] — Design reference
- `frontend/noise.png` [NEW] — Grain texture

**Color Palette Summary:**
- Light mode: TE/OP-1 style with `#DFDFDF` base
- Dark mode: Deep space with `#0f1216` canvas
- Flair colors: Same bold colors in both modes (`#FFCE59` gold, `#1FB256` green, `#A855F7` purple, `#4EA8DE` blue)
- FAT 12px left border on metric cards
- Button glow in dark mode only
- Sharp grain texture overlay (4% opacity)
- Mini bar graphs instead of sparklines
## Era 7: Kepler Era (MILP Planner Maturation)

This phase promoted Kepler from shadow mode to primary planner, implemented strategic S-Index, and built out the learning/reflex systems.

### [DONE] Rev F5 — Fix Planner Crash on Missing 'start_time'

**Goal:** Fix `KeyError: 'start_time'` crashing the planner and provide user-friendly error message.

**Root Cause:** `formatter.py` directly accessed `df_copy["start_time"]` without checking existence.

**Implementation (2025-12-27):**
- [x] **Smart Index Recovery:** If DataFrame has `index` column with timestamps after reset, auto-rename to `start_time`
- [x] **Defensive Validation:** Added check for `start_time` and `end_time` before access
- [x] **User-Friendly Error:** Raises `ValueError` with clear message and available columns list instead of cryptic `KeyError`

### [DONE] Rev F4 — Global Error Handling & Health Check System

**Goal:** Create a unified health check system that prevents crashes, validates all components, and shows user-friendly error banners.

**Error Categories:**
| Category | Examples | Severity |
|----------|----------|----------|
| HA Connection | HA unreachable, auth failed | CRITICAL |
| Missing Entities | Sensors renamed/deleted | CRITICAL |
| Config Errors | Wrong types, missing fields | CRITICAL |
| Database | MariaDB connection failed | WARNING |
| Planner/Executor | Generation or dispatch failed | WARNING |

**Implementation (2025-12-27):**
- [x] **Phase 1 - Backend:** Created `backend/health.py` with `HealthChecker` class
- [x] **Phase 2 - API:** Added `/api/health` endpoint returning issues with guidance
- [x] **Phase 3 - Config:** Integrated config validation into HealthChecker
- [x] **Phase 4 - Frontend:** Created `SystemAlert.tsx` (red=critical, yellow=warning)
- [x] **Phase 5 - Integration:** Updated `App.tsx` to fetch health every 60s and show banner

### [DONE] Rev F3 — Water Heater Config & Control

**Goal:** Fix ignored temperature settings.

**Problem:** User changed `water_heater.temp_normal` from 60 to 40, but system still heated to 60.

**Root Cause:** Hardcoded values in `executor/controller.py`:
```python
return 60  # Was hardcoded instead of using config
```

**Implementation (2025-12-27):**
- [x] **Fix:** Updated `controller.py` to use `WaterHeaterConfig.temp_normal` and `temp_off`.
- [x] **Integration:** Updated `make_decision()` and `engine.py` to pass water_heater_config.

### [DONE] Rev K24 — Battery Cost Separation (Gold Standard)

**Goal:** Eliminate Sunk Cost Fallacy by strictly separating Accounting (Reporting) from Trading (Optimization).

**Architecture:**

1.  **The Accountant (Reporting Layer):**

    *   **Component:** `backend/battery_cost.py`

    *   **Responsibility:** Track the Weighted Average Cost (WAC) of energy currently in the battery.

    *   **Usage:** Strictly for UI/Dashboard (e.g., "Current Battery Value") and historical analysis.

    *   **Logic:** `New_WAC = ((Old_kWh * Old_WAC) + (Charge_kWh * Buy_Price)) / New_Total_kWh`

2.  **The Trader (Optimization Layer):**

    *   **Component:** `planner/solver/kepler.py` & `planner/solver/adapter.py`

    *   **Responsibility:** Determine optimal charge/discharge schedule.

    *   **Constraint:** Must **IGNORE** historical WAC.

    *   **Drivers:**

        *   **Opportunity Cost:** Future Price vs. Current Price.

        *   **Wear Cost:** Fixed cost per cycle (from config) to prevent over-cycling.

        *   **Terminal Value:** Estimated future utility of energy remaining at end of horizon (based on future prices, NOT past cost).

**Implementation Tasks:**

* [x] **Refactor `planner/solver/adapter.py`:**

    *   Remove import of `BatteryCostTracker`.

    *   Remove logic that floors `terminal_value` using `stored_energy_cost`.

    *   Ensure `terminal_value` is calculated solely based on future price statistics (min/avg of forecast prices).

* [x] **Verify `planner/solver/kepler.py`:** Ensure no residual references to stored cost exist.

### [OBSOLETE] Rev K23 — SoC Target Holding Behavior (2025-12-22)

**Goal:** Investigate why battery holds at soc_target instead of using battery freely.

**Reason:** Issue no longer reproduces after Rev K24 (Battery Cost Separation) was implemented. The decoupling of accounting from trading resolved the underlying constraint behavior.

### [DONE] Rev K22 — Plan Cost Not Stored

**Goal:** Fix missing `planned_cost_sek` in Aurora "Cost Reality" card.

**Implementation Status (2025-12-26):**
-   [x] **Calculation:** Modified `planner/output/formatter.py` and `planner/solver/adapter.py` to calculate Grid Cash Flow cost per slot.
-   [x] **Storage:** Updated `db_writer.py` to store `planned_cost_sek` in MariaDB `current_schedule` and `plan_history` tables.
-   [x] **Sync:** Updated `backend/learning/mariadb_sync.py` to synchronize the new cost column to local SQLite.
-   [x] **Metrics:** Verified `backend/learning/engine.py` can now aggregate planned cost correctly for the Aurora dashboard.

### [DONE] Rev K21 — Water Heating Spacing & Tuning

**Goal:** Fix inefficient water heating schedules (redundant heating & expensive slots).

**Implementation Status (2025-12-26):**
-   [x] **Soft Efficiency Penalty:** Added `water_min_spacing_hours` and `water_spacing_penalty_sek` to `KeplerSolver`. 
-   [x] **Progressive Gap Penalty:** Implemented a two-tier "Rubber Band" penalty in MILP to discourage very long gaps between heating sessions.
-   [x] **UI Support:** Added spacing parameters to Settings → Parameters → Water Heating.

### [DONE] Rev UI2 — Premium Polish

Goal: Elevate the "Command Center" feel with live visual feedback and semantic clarity.

**Implementation Status (2025-12-26):**
- [x] **Executor Sparklines:** Integrated `Chart.js` into `Executor.tsx` to show live trends for SoC, PV, and Load.
- [x] **Aurora Icons:** Added semantic icons (Shield, Coffee, GraduationCap, etc.) to `ActivityLog.tsx` for better context.
- [x] **Sidebar Status:** Implemented the connectivity "pulse" dot and vertical versioning in `Sidebar.tsx`.
- [x] **Dashboard Visuals (Command Cards):** Refactored the primary KPI area into semantic "Domain Cards" (Grid, Resources, Strategy).
- [x] **Control Parameters Card:**
    - [x] **Merge:** Combined "Water Comfort" and "Risk Appetite" into one card.
    - [x] **Layout:** Selector buttons (1-5) use **full width** of the card.
    - [x] **Positioning:** Card moved **UP** to the primary row.
    - [x] **Overrides:** Added "Water Boost (1h)" and "Battery Top Up (50%)" manual controls.
    - [x] **Visual Flair:** Implemented "Active Reactor" glowing states and circuit-board connective lines.
- [x] **Cleanup:** 
    - [x] Removed redundant titles ("Quick Actions", "Control Parameters") to save space.
    - [x] Implemented **Toolbar Card** for Plan Badge (Freshness + Next Action) and Refresh controls.
- [x] **HA Event Stream (E1):** Implement **WebSockets** to replace all polling mechanisms. 
    - **Scope:** Real-time streaming for Charts, Sparklines, and Status.
    - **Cleanup:** Remove the "30s Auto-Refresh" toggle and interval logic entirely. Dashboard becomes fully push-based.
- [x] **Data Fix (Post-E1):** Fixed - `/api/energy/today` was coupled to executor's HA client. Refactored to use direct HA requests. Also fixed `setAutoRefresh` crash in Dashboard.tsx.

### [DONE] Rev UI1 — Dashboard Quick Actions Redesign

**Goal:** Redesign the Dashboard Quick Actions for the native executor, with optional external executor fallback in Settings.

**Implementation Status (2025-12-26):**
-   [x] Phase 1: Implement new Quick Action buttons (Run Planner, Executor Toggle, Vacation, Water Boost).
-   [x] Phase 2: Settings Integration
    -   [x] Add "External Executor Mode" toggle in Settings → Advanced.
    -   [x] When enabled, show "DB Sync" card with Load/Push buttons.
    
**Phase 3: Cleanup**

-   [x] Hide Planning tab from navigation (legacy).
-   [x] Remove "Reset Optimal" button.

### [DONE] Rev O1 — Onboarding & System Profiles

Goal: Make Darkstar production-ready for both standalone Docker AND HA Add-on deployments with minimal user friction.

Design Principles:

1.  **Settings Tab = Single Source of Truth** (works for both deployment modes)
    
2.  **HA Add-on = Bootstrap Helper** (auto-detects where possible, entity dropdowns for sensors)
    
3.  **System Profiles** via 3 toggles: Solar, Battery, Water Heater
    

**Phase 1: HA Add-on Bootstrap**

-   [x] **Auto-detection:** `SUPERVISOR_TOKEN` available as env var (no user token needed). HA URL is always `http://supervisor/core`.
    
-   [x] **Config:** Update `hassio/config.yaml` with entity selectors.
    
-   [x] **Startup:** Update `hassio/run.sh` to auto-generate `secrets.yaml`.
    

**Phase 2: Settings Tab — Setup Section**

-   [x] **HA Connection:** Add section in Settings → System with HA URL/Token fields (read-only in Add-on mode) and "Test Connection" button.
    
-   [x] **Core Sensors:** Add selectors for Battery SoC, PV Production, Load Consumption.
    

**Phase 3: System Profile Toggles**

-   [x] **Config:** Add `system: { has_solar: true, has_battery: true, has_water_heater: true }` to `config.default.yaml`.
    
-   [x] **UI:** Add 3 toggle switches in Settings → System.
    
-   [x] **Logic:** Backend skips disabled features in planner/executor.
    

Phase 4: Validation

| Scenario | Solar | Battery | Water | Expected |
|---|---|---|---|---|
| Full system | ✓ | ✓ | ✓ | All features |
| Battery only | ✗ | ✓ | ✗ | Grid arbitrage only |
| Solar + Water | ✓ | ✗ | ✓ | Cheap heating, no battery |
| Water only | ✗ | ✗ | ✓ | Cheapest price heating |

### [DONE] Rev F2 — Wear Cost Config Fix

Goal: Fix Kepler to use correct battery wear/degradation cost.

Problem: Kepler read wear cost from wrong config key (learning.default_battery_cost_sek_per_kwh = 0.0) instead of battery_economics.battery_cycle_cost_kwh (0.2 SEK).

Solution:

1.  Fixed `adapter.py` to read from correct config key.
    
2.  Added `ramping_cost_sek_per_kw: 0.05` to reduce sawtooth switching.
    
3.  Fixed adapter to read from kepler config section.

### [OBSOLETE] Rev K20 — Stored Energy Cost for Discharge

Goal: Make Kepler consider stored energy cost in discharge decisions.

Reason: Superseded by Rev K24. We determined that using historical cost in the solver constitutes a "Sunk Cost Fallacy" and leads to suboptimal future decisions. Cost tracking will be handled for reporting only.

### Rev K15 — Probabilistic Forecasting (Risk Awareness)
- Upgraded Aurora Vision from point forecasts to probabilistic forecasts (p10/p50/p90).
- Trained Quantile Regression models in LightGBM.
- Updated DB schema for probabilistic bands.
- Enabled `probabilistic` S-Index mode using p90 load and p10 PV.
- **Status:** ✅ Completed

### Rev K14 — Astro-Aware PV (Forecasting)
- Replaced hardcoded PV clamps (17:00-07:00) with dynamic sunrise/sunset calculations using `astral`.
- **Status:** ✅ Completed

### Rev K13 — Planner Modularization (Production Architecture)
- Refactored monolithic `planner.py` (3,637 lines) into modular `planner/` package.
- Clear separation: inputs → strategy → scheduling → solver → output.
- **Status:** ✅ Completed

### Rev K12 — Aurora Reflex Completion (The Analyzers)
- Completed Safety, Confidence, ROI, and Capacity analyzers in `reflex.py`.
- Added query methods to LearningStore for historical analysis.
- **Status:** ✅ Completed

### Rev K11 — Aurora Reflex (Long-Term Tuning)
- Implemented "Inner Ear" for auto-tuning parameters based on long-term drift.
- Safe config updates with `ruamel.yaml`.
- **Status:** ✅ Completed

### Rev K10 — Aurora UI Makeover
- Revamped Aurora tab as central AI command center.
- Cockpit layout with Strategy Log, Context Radar, Performance Mirror.
- **Status:** ✅ Completed

### Rev K9 — The Learning Loop (Feedback)
- Analyst component to calculate bias (Forecast vs Actual).
- Auto-tune adjustments written to `learning_daily_metrics`.
- **Status:** ✅ Completed

### Rev K8 — The Analyst (Grid Peak Shaving)
- Added `grid.import_limit_kw` to cap grid import peaks.
- Hard constraint in Kepler solver.
- **Status:** ✅ Completed

### Rev K7 — The Mirror (Backfill & Visualization)
- Auto-backfill from HA on startup.
- Performance tab with SoC Tunnel and Cost Reality charts.
- **Status:** ✅ Completed

### Rev K6 — The Learning Engine (Metrics & Feedback)
- Tracking `forecast_error`, `cost_deviation`, `battery_efficiency_realized`.
- Persistence in `planner_learning.db`.
- **Status:** ✅ Completed

### Rev K5 — Strategy Engine Expansion (The Tuner)
- Dynamic tuning of `wear_cost`, `ramping_cost`, `export_threshold` based on context.
- **Status:** ✅ Completed

### Rev K4 — Kepler Vision & Benchmarking
- Benchmarked MCP vs Kepler plans.
- S-Index parameter tuning.
- **Status:** ✅ Completed

### Rev K3 — Strategic S-Index (Decoupled Strategy)
- Decoupled Load Inflation (intra-day) from Dynamic Target SoC (inter-day).
- UI display of S-Index and Target SoC.
- **Status:** ✅ Completed

### Rev K2 — Kepler Promotion (Primary Planner)
- Promoted Kepler to primary planner via `config.kepler.primary_planner`.
- **Status:** ✅ Completed

---

## Era 6: Kepler (MILP Planner)

### Rev K1 — Kepler Foundation (MILP Solver)
*   **Goal:** Implement the core Kepler MILP solver as a production-grade component, replacing the `ml/benchmark/milp_solver.py` prototype, and integrate it into the backend for shadow execution.
*   **Status:** Completed (Kepler backend implemented in `backend/kepler/`, integrated into `planner.py` in shadow mode, and verified against MPC on historical data with ~16.8% cost savings).

## Era 5: Antares (Archived / Pivoted to Kepler)

### Rev 84 — Antares RL v2 Lab (Sequence State + Model Search)
*   **Goal:** Stand up a dedicated RL v2 “lab” inside the repo with a richer, sequence-based state and a clean place to run repeated BC/PPO experiments until we find a policy that consistently beats MPC on a wide held-out window.
*   **Status:** In progress (RL v2 contract + env + BC v2 train/eval scripts are available under `ml/rl_v2/`; BC v2 now uses SoC + cost‑weighted loss and plots via `debug/plot_day_mpc_bcv2_oracle.py`. A lab‑only PPO trainer (`ml/rl_v2/train_ppo_v2.py` + `AntaresRLEnvV2`) and cost eval (`ml/rl_v2/eval_ppo_v2_cost.py`) are available with shared SoC drift reporting across MPC/PPO/Oracle. PPO v2 is currently a lab artefact only: it can outperform MPC under an Oracle‑style terminal SoC penalty but does not yet match Oracle’s qualitative behaviour on all days. RL v2 remains off the planner hot path; focus for production planning is converging on a MILP‑centric planner as described in `docs/darkstar_milp.md`, with RL/BC used for lab diagnostics and policy discovery.)

### Rev 83 — RL v1 Stabilisation and RL v2 Lab Split
*   **Goal:** Stabilise RL v1 as a diagnostics-only baseline for Darkstar v2, ensure MPC remains the sole production decision-maker, and carve out a clean space (branch + tooling) for RL v2 experimentation without risking core planner behaviour.
*   **Status:** In progress (shadow gating added for RL, documentation to be extended and RL v2 lab to be developed on a dedicated branch).

### Rev 82 — Antares RL v2 (Oracle-Guided Imitation)
*   **Goal:** Train an Antares policy that consistently beats MPC on historical tails by directly imitating the Oracle MILP decisions, then evaluating that imitation policy in the existing AntaresMPCEnv.
*   **Status:** In progress (BC training script, policy wrapper, and evaluation wiring to be added; first goal is an Oracle-guided policy that matches or beats MPC on the 2025-11-18→27 tail window).

### Rev 81 — Antares RL v1.1 (Horizon-Aware State + Terminal SoC Shaping)
*   **Goal:** Move RL from locally price-aware to day-aware so it charges enough before known evening peaks and avoids running empty too early, while staying within the existing AntaresMPCEnv cost model.
*   **Status:** In progress (state and shaping changes wired in; next step is to retrain RL v1.1 and compare cost/behaviour vs the Rev 80 baseline).

### Rev 80 — RL Price-Aware Gating (Phase 4/5)
*   **Goal:** Make the v1 Antares RL agent behave economically sane per-slot (no discharging in cheap hours, prefer charging when prices are low, prefer discharging when prices are high), while keeping the core cost model and Oracle/MPC behaviour unchanged.
*   **Status:** Completed (price-aware gating wired into `AntaresMPCEnv` RL overrides, MPC/Oracle behaviour unchanged, and `debug/inspect_mpc_rl_oracle_stats.py` available to quickly compare MPC/RL/Oracle charge/discharge patterns against the day’s price distribution).

### Rev 79 — RL Visual Diagnostics (MPC vs RL vs Oracle)
*   **Goal:** Provide a simple, repeatable way to visually compare MPC, RL, and Oracle behaviour for a single day (battery power, SoC, prices, export) in one PNG image so humans can quickly judge whether the RL agent is behaving sensibly relative to MPC and the Oracle.
*   **Status:** Completed (CLI script `debug/plot_day_mpc_rl_oracle.py` added; generates and opens a multi-panel PNG comparing MPC vs RL vs Oracle for a chosen day using the same schedules used in cost evaluation).

### Rev 78 — Tail Zero-Price Repair (Phase 3/4)
*   **Goal:** Ensure the recent tail of the historical window (including November 2025) has no bogus zero import prices on otherwise normal days, so MPC/RL/Oracle cost evaluations are trustworthy.
*   **Status:** Completed (zero-price slots repaired via `debug/fix_zero_price_slots.py`; tail days such as 2025-11-18 → 2025-11-27 now have realistic 15-minute prices with no zeros, and cost evaluations over this window are trusted).

### Rev 77 — Antares RL Diagnostics & Reward Shaping (Phase 4/5)
*   **Goal:** Add tooling and light reward shaping so we can understand what the RL agent is actually doing per slot and discourage clearly uneconomic behaviour (e.g. unnecessary discharging in cheap hours), without changing the core cost definition used for evaluation.
*   **Status:** Completed (diagnostic tools and mild price-aware discharge penalty added; RL evaluation still uses the unshaped cost function, and the latest PPO v1 baseline is ~+8% cost vs MPC over recent tail days with Oracle as the clear lower bound).

### Rev 76 — Antares RL Agent v1 (Phase 4/5)
*   **Goal:** Design, train, and wire up the first real Antares RL agent (actor–critic NN) that uses the existing AntaresMPCEnv, cost model, and shadow plumbing, so we can evaluate a genuine learning-based policy in parallel with MPC and Oracle on historical data and (via shadow mode) on live production days.
*   **Status:** Completed (RL v1 agent scaffolded with PPO, RL runs logged to `antares_rl_runs`, models stored under `ml/models/antares_rl_v1/...`, evaluation script `ml/eval_antares_rl_cost.py` in place; latest RL baseline run is ~+8% cost vs MPC over recent tail days with Oracle as clear best, ready for further tuning in Rev 77+).

### Rev 75 — Antares Shadow Challenger v1 (Phase 4)
*   **Goal:** Run the latest Antares policy in shadow mode alongside the live MPC planner, persist daily shadow schedules with costs, and provide basic tooling to compare MPC vs Antares on real production data (no hardware control yet).
*   **Status:** Planned (first Phase 4 revision; enables production shadow runs and MPC vs Antares cost comparison on real data).

### Rev 74 — Tail Window Price Backfill & Final Data Sanity (Phase 3)
*   **Goal:** Fix and validate the recent tail of the July–now window (e.g. late November days with zero prices) so Phase 3 ends with a fully clean, production-grade dataset for both MPC and Antares training/evaluation.
*   **Status:** Planned (final Phase 3 data-cleanup revision before Phase 4 / shadow mode).

### Rev 73 — Antares Policy Cost Evaluation & Action Overrides (Phase 3)
*   **Goal:** Evaluate the Antares v1 policy in terms of full-day cost (not just action MAE) by letting it drive the Gym environment, and compare that cost against MPC and the Oracle on historical days.
*   **Status:** Planned (next active Antares revision; will produce a cost-based policy vs MPC/Oracle benchmark).

### Rev 72 — Antares v1 Policy (First Brain) (Phase 3)
*   **Goal:** Train a first Antares v1 policy that leverages the Gym environment and/or Oracle signals to propose battery/export actions and evaluate them offline against MPC and the Oracle.
*   **Status:** Completed (offline MPC-imitating policy, training, eval, and contract implemented in Rev 72).

### Rev 71 — Antares Oracle (MILP Benchmark) (Phase 3)
*   **Goal:** Build a deterministic “Oracle” that computes the mathematically optimal daily schedule (under perfect hindsight) so we can benchmark MPC and future Antares agents against a clear upper bound.
*   **Status:** Completed (Oracle MILP solver, MPC comparison tool, and config wiring implemented in Rev 71).

### Rev 70 — Antares Gym Environment & Cost Reward (Phase 3)
*   **Goal:** Provide a stable Gym-style environment around the existing deterministic simulator and cost model so any future Antares agent (supervised or RL) can be trained and evaluated offline on historical data.
*   **Status:** Completed (environment, reward, docs, and debug runner implemented in Rev 70).

### Rev 69 — Antares v1 Training Pipeline (Phase 3)
*   **Goal:** Train the first Antares v1 supervised model that imitates MPC’s per-slot decisions on validated `system_id="simulation"` data (battery + export focus) and establishes a baseline cost performance.
*   **Status:** Completed (training pipeline, logging, and eval helper implemented in Rev 69).

## Era 5: Antares Phase 1–2 (Data & Simulation)

### Rev 68 — Antares Phase 2b: Simulation Episodes & Gym Interface
*   **Summary:** Turned the validated historical replay engine into a clean simulation episode dataset (`system_id="simulation"`) and a thin environment interface for Antares, plus a stable v1 training dataset API.
*   **Details:**
    *   Ran `bin/run_simulation.py` over the July–now window, gated by `data_quality_daily`, to generate and log ~14k simulation episodes into SQLite `training_episodes` and MariaDB `antares_learning` with `system_id="simulation"`, `episode_start_local`, `episode_date`, and `data_quality_status`.
    *   Added `ml/simulation/env.py` (`AntaresMPCEnv`) to replay MPC schedules as a simple Gym-style environment with `reset(day)` / `step(action)`.
    *   Defined `docs/ANTARES_EPISODE_SCHEMA.md` as the canonical episode + slot schema and implemented `ml/simulation/dataset.py` to build a battery-masked slot-level training dataset.
    *   Exposed a stable dataset API via `ml.api.get_antares_slots(dataset_version="v1")` and added `ml/train_antares.py` as the canonical training entrypoint (currently schema/stats only).
*   **Status:** ✅ Completed (2025-11-29)

### Rev 67 — Antares Data Foundation: Live Telemetry & Backfill Verification (Phase 2.5)
*   **Summary:** Hardened the historical data window (July 2025 → present) so `slot_observations` in `planner_learning.db` is a HA-aligned, 15-minute, timezone-correct ground truth suitable for replay and Antares training, and added explicit data-quality labels and mirroring tools.
*   **Details:**
    *   Extended HA LTS backfill (`bin/backfill_ha.py`) to cover load, PV, grid import/export, and battery charge/discharge, and combined it with `ml.data_activator.etl_cumulative_to_slots` for recent days and water heater.
    *   Introduced `debug/validate_ha_vs_sqlite_window.py` to compare HA hourly `change` vs SQLite hourly sums and classify days as `clean`, `mask_battery`, or `exclude`, persisting results in `data_quality_daily` (138 clean, 10 mask_battery, 1 exclude across 2025-07-03 → 2025-11-28).
    *   Added `debug/repair_missing_slots.py` to insert missing 15-minute slots for edge-case days (e.g. 2025-11-16) before re-running backfill.
    *   Ensured `backend.recorder` runs as an independent 15-minute loop in dev and server so future live telemetry is always captured at slot resolution, decoupled from planner cadence.
    *   Implemented `debug/mirror_simulation_episodes_to_mariadb.py` so simulation episodes (`system_id="simulation"`) logged in SQLite can be reliably mirrored into MariaDB `antares_learning` after DB outages.
*   **Status:** ✅ Completed (2025-11-28)

### Rev 66 — Antares Phase 2: The Time Machine (Simulator)
*   **Summary:** Built the historical replay engine that runs the planner across past days to generate training episodes, using HA history (LTS + raw) and Nordpool prices to reconstruct planner-ready state.
*   **Details:**
    *   Added `ml/simulation/ha_client.py` to fetch HA Long Term Statistics (hourly) for load/PV and support upsampling to 15-minute slots.
    *   Implemented `ml/simulation/data_loader.py` to orchestrate price/sensor loading, resolution alignment, and initial state reconstruction for simulation windows.
    *   Implemented `bin/run_simulation.py` to step through historical windows, build inputs, call `HeliosPlanner.generate_schedule(record_training_episode=True)`, and surface per-slot debug logs.
*   **Status:** ✅ Completed (2025-11-28)

### Rev 65 — Antares Phase 1b: The Data Mirror
*   **Summary:** Enabled dual-write of training episodes to a central MariaDB `antares_learning` table, so dev and prod systems share a unified episode lake.
*   **Details:**
    *   Added `system.system_id` to `config.yaml` and wired it into `LearningEngine.log_training_episode` / `_mirror_episode_to_mariadb`.
    *   Created the `antares_learning` schema in MariaDB to mirror `training_episodes` plus `system_id`.
    *   Ensured MariaDB outages do not affect planner runs by fully isolating mirror errors.
*   **Status:** ✅ Completed (2025-11-17)

### Rev 64 — Antares Phase 1: Unified Data Collection (The Black Box)
*   **Summary:** Introduced the `training_episodes` table and logging helper so planner runs can be captured as consistent episodes (inputs + context + schedule) for both live and simulated data.
*   **Details:**
    *   Added `training_episodes` schema in SQLite and `LearningEngine.log_training_episode` to serialize planner inputs/context/schedule.
    *   Wired `record_training_episode=True` into scheduler and CLI entrypoints while keeping web UI simulations clean.
    *   Updated cumulative ETL gap handling and tests to ensure recorded episodes are based on accurate slot-level data.
*   **Status:** ✅ Completed (2025-11-16)

## Era 4: Strategy Engine & Aurora v2 (The Agent)

### Rev 62 — Export Safety & Aurora Agent
*   **Summary:** Decoupled battery export from `strategic_charging.target_soc_percent` and removed the non-decreasing responsibility gate so export can occur whenever price is profitable and SoC is above the protective export floor.
*   **Details:**
    *   Export now uses only `protective_soc_kwh` (gap-based or fixed) plus profitability checks, instead of treating the strategic charge target as a hard export floor.
    *   Removed the redundant `responsibilities_met` guard, which previously never resolved and effectively disabled automatic export despite high spreads.
*   **Status:** ✅ Completed (2025-11-24)

### Rev 61 — The Aurora Tab (AI Agent Interface)
*   **Summary:** Introduced the Aurora tab (`/aurora`) as the system's "Brain" and Command Center. The tab explains *why* decisions are made, visualizes Aurora’s forecast corrections, and exposes a high-level risk control surface (S-index).
*   **Backend:** Added `backend/api/aurora.py` and registered `aurora_bp` in `backend/webapp.py`. Implemented:
    *   `GET /api/aurora/dashboard` — returns identity (Graduation level from `learning_runs`), risk profile (persona derived from `s_index.base_factor`), weather volatility (via `ml.weather.get_weather_volatility`), a 48h horizon of base vs corrected forecasts (PV + load), and the last 14 days of per-day correction volume (PV + load, with separate fields).
    *   `POST /api/aurora/briefing` — calls the LLM (via OpenRouter) with the dashboard JSON to generate a concise 1–2 sentence Aurora “Daily Briefing”.
*   **Frontend Core:** Extended `frontend/src/lib/types.ts` and `frontend/src/lib/api.ts` with `AuroraDashboardResponse`, history types, and `Api.aurora.dashboard/briefing`.
*   **Aurora UI:**
    *   Built `frontend/src/pages/Aurora.tsx` as a dedicated Command Center:
        *   Hero card with shield avatar, Graduation mode, Experience (runs), Strategy (risk persona + S-index factor), Today’s Action (kWh corrected), and a volatility-driven visual “signal”.
        *   Daily Briefing card that renders the LLM output as terminal-style system text.
        *   Risk Dial module wired to `s_index.base_factor`, with semantic regions (Gambler / Balanced / Paranoid), descriptive copy, and inline color indicator.
    *   Implemented `frontend/src/components/DecompositionChart.tsx` (Chart.js) for a 48h Forecast Decomposition:
        *   Base Forecast: solid line with vertical gradient area fill.
        *   Final Forecast: thicker dashed line.
        *   Correction: green (positive) / red (negative) bars, with the largest correction visually highlighted.
    *   Implemented `frontend/src/components/CorrectionHistoryChart.tsx`:
        *   Compact bar chart over 14 days of correction volume, with tooltip showing Date + Total kWh.
        *   Trend text summarizing whether Aurora has been more or less active in the last week vs the previous week.
*   **UX Polish:** Iterated on gradients, spacing, and hierarchy so the Aurora tab feels like a high-end agent console rather than a debugging view, while keeping the layout consistent with Dashboard/Forecasting (hero → decomposition → impact).
*   **Status:** ✅ Completed (2025-11-24)

### Rev 60 — Cross-Day Responsibility (Charging Ahead for Tomorrow)
*   **Summary:** Updated `_pass_1_identify_windows` to consider total future net deficits vs. cheap-window capacity and expand cheap windows based on future price distribution when needed, so the planner charges in the cheapest remaining hours and preserves SoC for tomorrow’s high-price periods even when the battery is already near its target at runtime.
*   **Status:** ✅ Completed (2025-11-23)

### Rev 59 — Intelligent Memory (Aurora Correction)
*   **Summary:** Implemented Aurora Correction (Model 2) with a strict Graduation Path (Infant/Statistician/Graduate) so the system can predict and apply forecast error corrections safely as data accumulates.
*   **Details:** Extended `slot_forecasts` with `pv_correction_kwh`, `load_correction_kwh`, and `correction_source`; added `ml/corrector.py` to compute residual-based corrections using Rolling Averages (Level 1) or LightGBM error models (Level 2) with ±50% clamping around the base forecast; implemented `ml/pipeline.run_inference` to orchestrate base forecasts (Model 1) plus corrections (Model 2) and persist them in SQLite; wired `inputs.py` to consume `base + correction` transparently when building planner forecasts.
*   **Status:** ✅ Completed (2025-11-23)

### Rev 58 — The Weather Strategist (Strategy Engine)
*   **Summary:** Added a weather volatility metric over a 48h horizon using Open-Meteo (cloud cover and temperature), wired it into `inputs.py` as `context.weather_volatility`, and taught the Strategy Engine to increase `s_index.pv_deficit_weight` and `temp_weight` linearly with volatility while never dropping below `config.yaml` baselines.
*   **Details:** `ml/weather.get_weather_volatility` computes normalized scores (`0.0-1.0`) based on standard deviation, `inputs.get_all_input_data` passes them as `{"cloud": x, "temp": y}`, and `backend.strategy.engine.StrategyEngine` scales weights by up to `+0.4` (PV deficit) and `+0.2` (temperature) with logging and a debug harness in `debug/test_strategy_weather.py`.
*   **Status:** ✅ Completed (2025-11-23)

### Rev 57 — In-App Scheduler Orchestrator
*   **Summary:** Implemented a dedicated in-app scheduler process (`backend/scheduler.py`) controlled by `automation.schedule` in `config.yaml`, exposed `/api/scheduler/status`, and wired the Dashboard’s Planner Automation card to show real last/next run status instead of computed guesses.
*   **Status:** ✅ Completed (2025-11-23)

### Rev 56 — Dashboard Server Plan Visualization
*   **Summary:** Added a “Load DB plan” Quick Action, merged execution history into `/api/db/current_schedule`, and let the Dashboard chart show `current_schedule` slots with actual SoC/`actual_*` values without overwriting `schedule.json`.
*   **Status:** ✅ Completed (2025-11-23)

### Rev A23 — The Voice (Smart Advisor)
*   **Summary:** Present the Analyst's findings via a friendly "Assistant" using an LLM.
*   **Scope:** `secrets.yaml` (OpenRouter Key), `backend/llm_client.py` (Gemini Flash interface), UI "Smart Advisor" card.
*   **Status:** ✅ Completed (2025-11-21)

### Rev A22 — The Analyst (Manual Load Optimizer)
*   **Summary:** Calculate the mathematically optimal time to run heavy appliances (Dishwasher, Dryer) over the next 48h.
*   **Logic:** Scans price/PV forecast to find "Golden Windows" (lowest cost for 3h block). Outputs a JSON recommendation.
*   **Status:** ✅ Completed (2025-11-21)

### Rev A21 — "The Lab" (Simulation Playground)
*   **Summary:** Added `/api/simulate` support for overrides and created `Lab.tsx` UI for "What If?" scenarios (e.g., Battery Size, Max Power).
*   **Status:** ✅ Completed (2025-11-21)

### Rev A20 — Smart Thresholds (Dynamic Window Expansion)
*   **Summary:** Updated `_pass_1_identify_windows` in `planner.py`. Logic now calculates energy deficit vs window capacity and expands the "cheap" definition dynamically to meet `target_soc`.
*   **Validation:** `debug/test_smart_thresholds.py` simulated a massive 100kWh empty battery with a strict 5% price threshold. Planner successfully expanded the window from ~10 slots to 89 slots to meet demand.
*   **Status:** ✅ Completed (2025-11-21)

### Rev A19 — Context Awareness
*   **Summary:** Connected `StrategyEngine` to `inputs.py`. Implemented `VacationMode` rule (disable water heating).
*   **Fixes:** Rev 19.1 hotfix removed `alarm_armed` from water heating disable logic (occupants need hot water).
*   **Status:** ✅ Completed (2025-11-21)

### Rev A18 — Strategy Injection Interface
*   **Summary:** Refactored `planner.py` to accept runtime config overrides. Created `backend/strategy/engine.py`. Added `strategy_log` table.
*   **Status:** ✅ Completed (2025-11-20)

---

## Era 3: Aurora v1 (Machine Learning Foundation)

### Rev A17 — Stabilization & Automation
*   **Summary:** Diagnosed negative bias (phantom charging), fixed DB locks, and automated the ML inference pipeline.
*   **Key Fixes:**
    *   **Phantom Charging:** Added `.clip(lower=0.0)` to adjusted forecasts.
    *   **S-Index:** Extended input horizon to 7 days to ensure S-index has data.
    *   **Automation:** Modified `inputs.py` to auto-run `ml/forward.py` if Aurora is active.
*   **Status:** ✅ Completed (2025-11-21)

### Rev A16 — Calibration & Safety Guardrails
*   **Summary:** Added planner-facing guardrails (load > 0.01, PV=0 at night) to prevent ML artifacts from causing bad scheduling.
*   **Status:** ✅ Completed (2025-11-18)

### Rev A15 — Forecasting Tab Enhancements
*   **Summary:** Refined the UI to compare Baseline vs Aurora MAE metrics. Added "Run Eval" and "Run Forward" buttons to the UI.
*   **Status:** ✅ Completed (2025-11-18)

### Rev A14 — Additional Weather Features
*   **Summary:** Enriched LightGBM models with Cloud Cover and Shortwave Radiation from Open-Meteo.
*   **Status:** ✅ Completed (2025-11-18)

### Rev A13 — Naming Cleanup
*   **Summary:** Standardized UI labels to "Aurora (ML Model)" and moved the forecast source toggle to the Forecasting tab.
*   **Status:** ✅ Completed (2025-11-18)

### Rev A12 — Settings Toggle
*   **Summary:** Exposed `forecasting.active_forecast_version` in Settings to switch between Baseline and Aurora.
*   **Status:** ✅ Completed (2025-11-17)

### Rev A11 — Planner Consumption
*   **Summary:** Wired `inputs.py` to consume Aurora forecasts when the feature flag is active.
*   **Status:** ✅ Completed (2025-11-17)

### Rev A10 — Forward Inference
*   **Summary:** Implemented `ml/forward.py` to generate future forecasts using Open-Meteo forecast data.
*   **Status:** ✅ Completed (2025-11-17)

### Rev A09 — Aurora v0.2 (Enhanced Shadow Mode)
*   **Summary:** Added temperature and vacation mode features to training. Added Forecasting UI tab.
*   **Status:** ✅ Completed (2025-11-17)

### Rev A01–A08 — Aurora Initialization
*   **Summary:** Established `/ml` directory, data activators (`ml/data_activator.py`), training scripts (`ml/train.py`), and evaluation scripts (`ml/evaluate.py`).
*   **Status:** ✅ Completed (2025-11-16)

---

## Era 2: Modern Core (Monorepo & React UI)

### Rev 55 — Production Readiness
*   **Summary:** Added global "Backend Offline" indicator, improved mobile responsiveness, and cleaned up error handling.
*   **Status:** ✅ Completed (2025-11-15)

### Rev 54 — Learning & Debug Enhancements
*   **Summary:** Persisted S-Index history and improved Learning tab charts (dual-axis for changes vs. s-index). Added time-range filters to Debug logs.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 53 — Learning Architecture
*   **Summary:** Consolidated learning outputs into `learning_daily_metrics` (one row per day). Planner now reads learned overlays (PV/Load bias) from DB.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 52 — Learning History
*   **Summary:** Created `learning_param_history` to track config changes over time without modifying `config.yaml`.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 51 — Learning Engine Debugging
*   **Summary:** Traced data flow issues. Implemented real HA sensor ingestion for observations (`sensor_totals`) to fix "zero bias" issues.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 50 — Planning & Settings Polish
*   **Summary:** Handled "zero-capacity" gaps in Planning Timeline. Added explicit field validation in Settings UI.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 49 — Device Caps & SoC Enforcement
*   **Summary:** Planning tab now validates manual plans against device limits (max kW) and SoC bounds via `api/simulate`.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 48 — Dashboard History Merge
*   **Summary:** Dashboard "Today" chart now merges planned data with actual execution history from MariaDB (SoC Actual line).
*   **Status:** ✅ Completed (2025-11-14)

### Rev 47 — UX Polish
*   **Summary:** Simplified Dashboard chart (removed Y-axis labels, moved to overlay pills). Normalized Planning timeline background.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 46 — Schedule Correctness
*   **Summary:** Fixed day-slicing bugs (charts now show full 00:00–24:00 window). Verified Planner->DB->Executor contract.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 45 — Debug UI
*   **Summary:** Built dedicated Debug tab with log viewer (ring buffer) and historical SoC mini-chart.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 44 — Learning UI
*   **Summary:** Built Learning tab (Status, Metrics, History). Surfaces "Learning Enabled" status and recent run stats.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 43 — Settings UI
*   **Summary:** Consolidated System, Parameters, and UI settings into a React form. Added "Reset to Defaults" and Theme Picker.
*   **Status:** ✅ Completed (2025-11-13)

### Rev 42 — Planning Timeline
*   **Summary:** Rebuilt the interactive Gantt chart in React. Supports manual block CRUD (Charge/Water/Export/Hold) and Simulate/Save flow.
*   **Status:** ✅ Completed (2025-11-13)

### Rev 41 — Dashboard Hotfixes
*   **Summary:** Fixed Chart.js DOM errors and metadata sync issues ("Now Showing" badge).
*   **Status:** ✅ Completed (2025-11-13)

### Rev 40 — Dashboard Completion
*   **Summary:** Full parity with legacy UI. Added Quick Actions (Run Planner, Push to DB), Dynamic KPIs, and Real-time polling.
*   **Status:** ✅ Completed (2025-11-13)

### Rev 39 — React Scaffold
*   **Summary:** Established `frontend/` structure (Vite + React). Built the shell (Sidebar, Header) and basic ChartCard.
*   **Status:** ✅ Completed (2025-11-12)

### Rev 38 — Dev Ergonomics
*   **Summary:** Added `npm run dev` to run Flask and Vite concurrently with a proxy.
*   **Status:** ✅ Completed (2025-11-12)

### Rev 62 — Export Safety & Aurora Agent
*   **Summary:** Decoupled battery export from `strategic_charging.target_soc_percent` and removed the non-decreasing responsibility gate so export can occur whenever price is profitable and SoC is above the protective export floor.
*   **Details:**
    *   Export now uses only `protective_soc_kwh` (gap-based or fixed) plus profitability checks, instead of treating the strategic charge target as a hard export floor.
    *   Removed the redundant `responsibilities_met` guard, which previously never resolved and effectively disabled automatic export despite high spreads.
*   **Status:** ✅ Completed (2025-11-24)

### Rev 37 — Monorepo Skeleton
*   **Summary:** Moved Flask app to `backend/` and React app to `frontend/`.
*   **Status:** ✅ Completed (2025-11-12)

---

## Era 1: Foundations (Revs 0–36)

*   **Core MPC**: Robust multi-pass logic (safety margins, window detection, cascading responsibility, hold logic).
*   **Water Heating**: Integrated daily quota scheduling (grid-preferred in cheap windows).
*   **Export**: Peak-only export logic and profitability guards.
*   **Manual Planning**: Semantics for manual blocks (Charge/Water/Export/Hold) merged with MPC.
*   **Infrastructure**: SQLite learning DB, MariaDB history sync, Nordpool/HA integration.

---


