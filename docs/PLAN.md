# Darkstar Energy Manager: Active Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Revision Naming Conventions

| Prefix | Area | Examples |
|--------|------|----------|
| **K** | Kepler (MILP solver) | K1-K19 |
| **E** | Executor | E1 |
| **A** | Aurora (ML) | A25-A29 |
| **H** | History/DB | H1 |
| **O** | Onboarding | O1 |
| **UI** | User Interface | UI1, UI2 |
| **DS** | Design System | DS1 |
| **F** | Fixes/Bugfixes | F1-F6 |
| **DX** | Developer Experience | DX1 |
| **ARC** | Architecture | ARC1 |

---

## 🤖 AI Instructions (Read First)

1.  **Structure:** This file is a **chronological stream**. Newest items are at the **bottom**.
    
2.  **No Reordering:** Never move items. Only update their status or append new items.
    
3.  **Status Protocol:**
    
    -   Update the status tag in the Header: `### [STATUS] Rev ID — Title`
        
    -   Allowed Statuses: `[DRAFT]`, `[PLANNED]`, `[IN PROGRESS]`, `[DONE]`, `[PAUSED]`, `[OBSOLETE]`.
        
4.  **New Revisions:** Always use the template below.
    
5.  **Cleanup:** When this file gets too long (>15 completed items), move the oldest `[DONE]` items to `CHANGELOG.md`.
    

### Revision Template


```

### [STATUS] Rev ID — Title

**Goal:** Short description of the objective.
**Plan:**

* [ ] Step 1
* [ ] Step 2

```

---

## 📜 Revision Stream

*All completed revisions have been moved to [CHANGELOG_PLAN.md](CHANGELOG_PLAN.md).*§


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

### [DONE] Rev ARC1 — Architecture Modernization (FastAPI)

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

#### Route Verification & Debug (2026-01-02)

**Initial Status:** 30/67 routes working (44.8%). See `scripts/verify_arc1_routes.py`.

##### Phase 1: Critical Frontend Fixes [DONE]
- [x] Fix nested `<button>` in `ServiceSelect.tsx` (hydration error)
- [x] Fix `history is undefined` crash in `Executor.tsx`

##### Phase 2: Learning Router [DONE]
- [x] Create `backend/api/routers/learning.py` (7 endpoints)
- [x] Mount router in `backend/main.py`

##### Phase 3: Complete Executor Router [DONE]
- [x] Add `/api/executor/config` GET/PUT
- [x] Fix `/api/executor/quick-action` 500 error
- [x] Fix `/api/executor/pause` 500 error
- [x] Add `/api/executor/notifications` POST
- [x] Add `/api/executor/notifications/test` POST

##### Phase 4: Forecast Router Fixes [DONE]
- [x] Add `/api/forecast/eval`
- [x] Add `/api/forecast/day`
- [x] Add `/api/forecast/horizon`

##### Phase 5: Remaining Routes [DONE]
- [x] `/api/db/current_schedule` and `/api/db/push_current`
- [x] `/api/ha/services` and `/api/ha/test`
- [x] `/api/simulate`
- [x] `/api/ha-socket` status endpoint

**Final Status:** Routes verified working via curl tests. Debug/Analyst routers deferred to future revision.

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
- **Verification:** `grep -n "except:" backend/api/routers/forecast.py` returns only `except Exception:` or `except SomeError:`.

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

### [PLANNED] Rev ARC6 — Mega Validation & Merge

**Goal:** Comprehensive end-to-end validation of the entire ARC architecture (FastAPI + React) to prepare for merging the `refactor/arc1-fastapi` branch into `main`.

**Plan:**
* [ ] **Full Regression Suite**
    *   Verify all 67 API routes behave identically to legacy behavior.
    *   Validate all WebSocket events (live data, health).
    *   Verify Design System UI/UX consistency (Rev UI6).
* [ ] **Production Readiness**
    *   Performance benchmark (requests/sec).
    *   Security sweep (secrets, auth).
    *   Final `ruff` and `pyright` pass (100% clean).
* [ ] **Merge Preparation**
    *   Squash/Cleanup commit history.
    *   Update `CHANGELOG.md`.
    *   Merge to `main` and tag release.

---
