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
    
    -   Update the status tag in the Header: `### [STATUS] REV // ID00 — Title`
        
    -   Allowed Statuses: `[DRAFT]`, `[PLANNED]`, `[IN PROGRESS]`, `[DONE]`, `[PAUSED]`, `[OBSOLETE]`.
        
4.  **New Revisions:** Always use the template below.
    
5.  **Cleanup:** When this file gets too long (>15 completed items), move the oldest `[DONE]` items to `CHANGELOG.md`.
    

### Revision Template


```

### [STATUS] Rev ID — Title

**Goal:** Short description of the objective.
**Plan:**

#### Phase 1: [STATUS]
* [ ] Step 1
* [ ] Step 2

#### Phase 2: [STATUS]
* [ ] Step 1
* [ ] Step 2

```

---

## 📜 Revision Stream

### [IN PROGRESS] Rev ARC7 — Performance Architecture (Dashboard Speed)

**Goal:** Transform Dashboard load time from **1600ms → <200ms** through strategic caching, lazy loading, and WebSocket push architecture. Optimized for Raspberry Pi / Home Assistant add-on deployments.

**Background:** Performance profiling identified `/api/ha/average` (1635ms) as the main bottleneck, with `/api/aurora/dashboard` (461ms) and `/api/schedule` (330ms) as secondary concerns. The Dashboard makes 11 parallel API calls on load.

---

#### Phase 1: Smart Caching Layer [DONE]

**Goal:** Implement TTL-based caching for data that doesn't change frequently.

##### Task 1.1: Create Cache Infrastructure
- [x] Create `backend/core/cache.py` with `TTLCache` class
- [x] Support configurable TTL per cache key
- [x] Add cache invalidation via WebSocket events
- [x] Thread-safe implementation for async context

##### Task 1.2: Cache Nordpool Prices (Critical)
- [x] Cache `/api/nordpool` data for 1 hour (updates once daily after 13:00)
- [x] Invalidate at 13:30 CET daily (when new prices arrive)
- [x] This affects Aurora, Schedule, and Energy endpoints

##### Task 1.3: Cache HA Average Data
- [x] Cache `/api/ha/average` result for 60 seconds (was fetching 24h history every request!)
- [x] Investigate: Why is one sensor taking 1600ms? Should use batch fetch if fetching multiple.

##### Task 1.4: Cache Schedule in Memory
- [x] Keep `schedule.json` in RAM after first load
- [x] Invalidate on: planner run, manual save, DB sync
- [x] Push invalidation via `schedule_updated` WebSocket event

---

#### Phase 2: Lazy Loading Architecture [DONE]

**Goal:** Show Dashboard instantly, load non-critical data progressively.

##### Task 2.1: Categorize Dashboard Data by Priority
| Priority | Data | Strategy |
|----------|------|----------|
| **Critical** | Schedule, SoC, Executor Status | Load immediately |
| **Important** | Config, Scheduler Status | Load immediately |
| **Deferred** | HA Average, Energy Today, Water Today | Lazy load after render |
| **Background** | Aurora Dashboard, Learning Status | Lazy load with skeleton |

##### Task 2.2: Refactor Dashboard.tsx Data Fetching
- [x] Split `fetchAllData()` into `fetchCriticalData()` + `fetchDeferredData()`
- [x] Call critical fetch on mount, deferred after 100ms delay
- [x] Add skeleton loaders for deferred sections

##### Task 2.3: Add Loading States to Components
- [x] `AdvisorCard`: Show skeleton while Aurora loads
- [x] Stats row: Show "—" while HA Average loads
- [x] Use CSS shimmer animation for skeleton states

---

#### Phase 3: WebSocket Push Architecture [DONE]

**Goal:** Push data changes to Dashboard instead of polling.

##### Task 3.1: Extend WebSocket Events
- [x] Add `schedule_updated` event (emitted after planner run)
- [x] Add `config_updated` event (emitted after config save)
- [x] Add `executor_state` event (emitted on pause/resume/action)

##### Task 3.2: Frontend Subscription to Push Events
- [x] Subscribe to `schedule_updated` → refresh schedule display
- [x] Subscribe to `config_updated` → refresh config-dependent UI
- [x] Avoid full `fetchAllData()` on every event (targeted refresh)

##### Task 3.3: Schedule Push on Planner Run
- [x] In `PlannerPipeline.generate_schedule()`, emit `schedule_updated` at end
- [x] Include summary in event: `{ planned_at, slot_count, status }`
- [x] Dashboard receives push, updates without user refresh

---

#### Phase 4: Dashboard Bundle API [DONE]

**Goal:** Reduce 11 HTTP round-trips to 1 for critical data.

##### Task 4.1: Create `/api/dashboard/bundle` Endpoint
- [x] Returns: `{ status, config, schedule, executor_status, scheduler_status }`
- [x] Single server-side aggregation vs 5 separate calls
- [x] Reduces HTTP overhead especially on slow networks

##### Task 4.2: Update Frontend to Use Bundle
- [x] Replace 5 critical API calls with single bundle call
- [x] Keep deferred calls separate (they load async anyway)
- [x] Fallback to individual calls if bundle fails

---

#### Phase 5: HA Integration Optimization [DONE]

**Goal:** Understand and fix why HA calls are slow.

##### Task 5.1: Profile HA History API Call
- [ ] Investigate: Is `/api/ha/average` fetching 24h of data points?
- [ ] Check: Is it one HTTP call or many?
- [ ] Measure: HA server response time vs network latency

##### Task 5.2: Batch HA Sensor Reads
- [ ] `/api/energy/today` currently makes 6 sequential HA calls
- [ ] Batch into single `/api/states` call with filter
- [ ] Expected: 6 × 100ms → 1 × 150ms

##### Task 5.3: Consider HA WebSocket for Sensors
- [ ] HA WebSocket already pushes `live_metrics` (SoC, Power)
- [ ] Extend to push daily energy counters on state change
- [ ] Eliminates need for polling `/api/energy/today`

---

#### Verification Checklist

- [x] Dashboard loads in <200ms (critical path)
- [x] Non-critical data appears within 500ms (lazy loaded)
- [x] Schedule updates push via WebSocket (no manual refresh needed)
- [x] Nordpool prices cached for 1 hour
- [x] HA Average cached for 60 seconds
- [x] Works smoothly on Raspberry Pi 4

---

### [DONE] Rev ARC8 — In-Process Scheduler Architecture

**Goal:** Eliminate subprocess architecture by running the Scheduler and Planner as async background tasks inside the FastAPI process. This enables proper cache invalidation and WebSocket push because all components share the same memory space.

**Background:** The current architecture runs the planner via `subprocess.exec("backend/scheduler.py --once")`. This creates a separate Python process that cannot share the FastAPI process's cache or WebSocket connections. The result: cache invalidation and WebSocket events fail silently.

---

#### Phase 1: Async Planner Service [DONE]

**Goal:** Create an async-compatible planner service that can run in-process without blocking the event loop.

##### Task 1.1: Create `backend/services/planner_service.py`
- [x] Create new module `backend/services/planner_service.py`
- [x] Implement `PlannerService` class with async interface
- [x] Wrap blocking planner code with `asyncio.to_thread()` for CPU-bound work
- [x] Add `asyncio.Lock()` to prevent concurrent planner runs
- [x] Return structured result object (success, error, metadata)

##### Task 1.2: Integrate Cache Invalidation
- [x] After successful plan, call `await cache.invalidate("schedule:current")`
- [x] Emit `schedule_updated` WebSocket event with metadata
- [x] All in same process = shared memory = guaranteed delivery

##### Task 1.3: Error Handling & Recovery
- [x] Wrap planner execution in try/except
- [x] Log failures but don't crash the server
- [x] Return error status to caller
- [x] Emit `planner_error` WebSocket event for frontend notification

---

#### Phase 2: Background Scheduler Task [DONE]

**Goal:** Replace the standalone `scheduler.py` loop with an async background task managed by FastAPI's lifespan.

##### Task 2.1: Create `backend/services/scheduler_service.py`
- [x] Create new module `backend/services/scheduler_service.py`
- [x] Implement `SchedulerService` class with async loop
- [x] Use `asyncio.sleep()` instead of blocking `time.sleep()`
- [x] Handle graceful shutdown via cancellation

##### Task 2.2: Integrate with FastAPI Lifespan
- [x] Modify `backend/main.py` lifespan to start scheduler on startup
- [x] Stop scheduler gracefully on shutdown
- [x] Maintain existing HA WebSocket connection startup

##### Task 2.3: Migrate Scheduler Logic
- [x] Port interval calculation from `scheduler.py`
- [x] Port jitter logic
- [ ] Port ML training trigger (04:00 daily) — *deferred to Phase 4*
- [ ] Port Aurora Reflex daily job — *deferred to Phase 4*
- [x] Port smart retry logic on failure

---

#### Phase 3: API Endpoint Refactor [DONE]

**Goal:** Update `/api/run_planner` to use the in-process planner service instead of subprocess.

##### Task 3.1: Refactor `/api/run_planner`
- [x] Remove subprocess logic from `legacy.py`
- [x] Call `await planner_service.run_once()`
- [x] Return structured response with timing and status
- [x] Cache invalidation happens automatically via planner service

##### Task 3.2: Add `/api/scheduler/trigger` Endpoint
- [ ] New endpoint to manually trigger next scheduled run — *deferred to Phase 4*

##### Task 3.3: Enhance `/api/scheduler/status`
- [x] Return live status from `scheduler_service` (not just file)
- [x] Include: running, last_run, next_run, current_task
- [x] Add `is_running` boolean for UI state

---

#### Phase 4: Cleanup & Deprecation [DONE]

**Goal:** Remove legacy subprocess code and ensure clean architecture.

##### Task 4.1: Deprecate Standalone Scheduler Mode
- [x] Keep `scheduler.py` for backwards compatibility but mark deprecated
- [x] Add deprecation warning if run directly
- [x] Update `Dockerfile` to not start separate scheduler process — *N/A: already correct*
- [x] Update `docker-compose.yml` if applicable — *N/A: already correct*

##### Task 4.2: Remove Subprocess WebSocket Workarounds
- [x] Remove `invalidate_and_push_sync()` complexity (no longer needed)
- [x] ~~Remove `cache_sync`~~ — **Kept**: still needed by `inputs.py` for Nordpool caching
- [x] Simplify `websockets.py` to async-only interface (kept `emit_sync` for Executor thread)

##### Task 4.3: Update Documentation
- [x] Update `docs/architecture.md` with new scheduler architecture
- [x] Update `AGENTS.md` if scheduler instructions changed — *N/A: no changes needed*
- [x] Add architecture diagram showing in-process flow


---

#### Phase 5: Testing & Verification [DONE]

**Goal:** Comprehensive testing of the new architecture.

##### Task 5.1: Lint & Test Verification
- [x] `ruff check backend/` passes (0 errors)
- [x] `pnpm lint` passes (frontend, 0 errors)
- [x] `pytest tests/` passes (187 tests)
- [x] Performance tests pass (4 tests)

##### Task 5.2: Unit Tests
- [x] Test `PlannerService.run_once()` success path
- [x] Test `PlannerService.run_once()` failure handling
- [x] Test `SchedulerService` start/stop lifecycle
- [x] Test cache invalidation on planner completion

##### Task 5.3: Integration Tests
- [x] Test `/api/run_planner` triggers in-process execution
- [x] Test WebSocket `schedule_updated` event is emitted
- [x] Test Dashboard receives update without manual refresh
- [x] Test scheduler respects interval and jitter settings

##### Task 5.4: Performance Verification
- [x] Confirm planner runs in threadpool (doesn't block API)
- [x] Measure API latency during planner execution
- [x] Stress test: Multiple simultaneous `/api/run_planner` calls

##### Task 5.5: Fix Missing Historic Data [DONE]
- [x] Implement `aiosqlite` query in `backend/api/routers/schedule.py`
- [x] Calculate `actual_charge_kw` and `water_heating_kw` from energy
- [x] Remove sync `ExecutionHistory` import

##### Task 5.6: Fix Solar Forecast Display [DONE]
- [x] Add logging to `schedule.py` for forecast map diagnostics
- [x] Verify `slot_forecasts` table content
- [x] Ensure `pvForecast` fallback logic is robust in backend

##### Task 5.7: Fix Pause UI Lag [DONE]
- [x] Update `QuickActions.tsx` to refresh data on pause toggle
- [x] Verify banner appears immediately

---

#### Verification Checklist

- [x] Planner runs in-process (not subprocess)
- [x] Cache invalidation works immediately after planner
- [x] WebSocket `schedule_updated` reaches frontend
- [x] Dashboard chart updates without manual refresh
- [x] Scheduler loop runs as FastAPI background task
- [x] Graceful shutdown stops scheduler cleanly
- [x] API remains responsive during planner execution
- [/] All existing planner features work (ML training, Reflex, retry) — *deferred to later phase*

---

*All completed revisions have been moved to [CHANGELOG_PLAN.md](CHANGELOG_PLAN.md).*

