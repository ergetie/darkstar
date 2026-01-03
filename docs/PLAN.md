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

#### Phase 1: [STATUS]
* [ ] Step 1
* [ ] Step 2

#### Phase 2: [STATUS]
* [ ] Step 1
* [ ] Step 2

```

---

## 📜 Revision Stream

### [PLANNED] Rev ARC7 — Performance Architecture (Dashboard Speed)

**Goal:** Transform Dashboard load time from **1600ms → <200ms** through strategic caching, lazy loading, and WebSocket push architecture. Optimized for Raspberry Pi / Home Assistant add-on deployments.

**Background:** Performance profiling identified `/api/ha/average` (1635ms) as the main bottleneck, with `/api/aurora/dashboard` (461ms) and `/api/schedule` (330ms) as secondary concerns. The Dashboard makes 11 parallel API calls on load.

---

#### Phase 1: Smart Caching Layer [PLANNED]

**Goal:** Implement TTL-based caching for data that doesn't change frequently.

##### Task 1.1: Create Cache Infrastructure
- [ ] Create `backend/core/cache.py` with `TTLCache` class
- [ ] Support configurable TTL per cache key
- [ ] Add cache invalidation via WebSocket events
- [ ] Thread-safe implementation for async context

##### Task 1.2: Cache Nordpool Prices (Critical)
- [ ] Cache `/api/nordpool` data for 1 hour (updates once daily after 13:00)
- [ ] Invalidate at 13:30 CET daily (when new prices arrive)
- [ ] This affects Aurora, Schedule, and Energy endpoints

##### Task 1.3: Cache HA Average Data
- [ ] Cache `/api/ha/average` result for 60 seconds (was fetching 24h history every request!)
- [ ] Investigate: Why is one sensor taking 1600ms? Should use batch fetch if fetching multiple.

##### Task 1.4: Cache Schedule in Memory
- [ ] Keep `schedule.json` in RAM after first load
- [ ] Invalidate on: planner run, manual save, DB sync
- [ ] Push invalidation via `schedule_updated` WebSocket event

---

#### Phase 2: Lazy Loading Architecture [PLANNED]

**Goal:** Show Dashboard instantly, load non-critical data progressively.

##### Task 2.1: Categorize Dashboard Data by Priority
| Priority | Data | Strategy |
|----------|------|----------|
| **Critical** | Schedule, SoC, Executor Status | Load immediately |
| **Important** | Config, Scheduler Status | Load immediately |
| **Deferred** | HA Average, Energy Today, Water Today | Lazy load after render |
| **Background** | Aurora Dashboard, Learning Status | Lazy load with skeleton |

##### Task 2.2: Refactor Dashboard.tsx Data Fetching
- [ ] Split `fetchAllData()` into `fetchCriticalData()` + `fetchDeferredData()`
- [ ] Call critical fetch on mount, deferred after 100ms delay
- [ ] Add skeleton loaders for deferred sections

##### Task 2.3: Add Loading States to Components
- [ ] `AdvisorCard`: Show skeleton while Aurora loads
- [ ] Stats row: Show "—" while HA Average loads
- [ ] Use CSS shimmer animation for skeleton states

---

#### Phase 3: WebSocket Push Architecture [PLANNED]

**Goal:** Push data changes to Dashboard instead of polling.

##### Task 3.1: Extend WebSocket Events
- [ ] Add `schedule_updated` event (emitted after planner run)
- [ ] Add `config_updated` event (emitted after config save)
- [ ] Add `executor_state` event (emitted on pause/resume/action)

##### Task 3.2: Frontend Subscription to Push Events
- [ ] Subscribe to `schedule_updated` → refresh schedule display
- [ ] Subscribe to `config_updated` → refresh config-dependent UI
- [ ] Avoid full `fetchAllData()` on every event (targeted refresh)

##### Task 3.3: Schedule Push on Planner Run
- [ ] In `PlannerPipeline.generate_schedule()`, emit `schedule_updated` at end
- [ ] Include summary in event: `{ planned_at, slot_count, status }`
- [ ] Dashboard receives push, updates without user refresh

---

#### Phase 4: Dashboard Bundle API (Optional) [PLANNED]

**Goal:** Reduce 11 HTTP round-trips to 1 for critical data.

##### Task 4.1: Create `/api/dashboard/bundle` Endpoint
- [ ] Returns: `{ status, config, schedule, executor_status, scheduler_status }`
- [ ] Single server-side aggregation vs 5 separate calls
- [ ] Reduces HTTP overhead especially on slow networks

##### Task 4.2: Update Frontend to Use Bundle
- [ ] Replace 5 critical API calls with single bundle call
- [ ] Keep deferred calls separate (they load async anyway)
- [ ] Fallback to individual calls if bundle fails

---

#### Phase 5: HA Integration Optimization [PLANNED]

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

- [ ] Dashboard loads in <200ms (critical path)
- [ ] Non-critical data appears within 500ms (lazy loaded)
- [ ] Schedule updates push via WebSocket (no manual refresh needed)
- [ ] Nordpool prices cached for 1 hour
- [ ] HA Average cached for 60 seconds
- [ ] Works smoothly on Raspberry Pi 4

---

*All completed revisions have been moved to [CHANGELOG_PLAN.md](CHANGELOG_PLAN.md).*

