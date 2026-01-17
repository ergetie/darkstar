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
| **ARC** | Architecture | ARC1-ARC* |

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

## REVISION STREAM:

---

### [DONE] REV // PERF1 — MILP Solver Performance Optimization

**Goal:** Reduce Kepler MILP solver execution time from 22s to <5s by switching from soft pairwise spacing penalties to a hardened linear spacing constraint.

**Context:** 
Profiling confirmed the water heating "spacing penalty" (O(T×S) pairwise constraints) was the primary bottleneck (0.47s benchmark). Switch to a "Hard Constraint" formulation (`sum(heat[t-S:t]) + start[t]*S <= S`) reduced benchmark time to 0.07s (**6.7x speedup**). This formulation prunes the search space aggressively and scales linearly O(T).

**Trade-off:** This removes the ability to "pay" to violate spacing. Users must configure `water_min_spacing_hours` < `water_heating_max_gap_hours` to ensure top-ups are possible when comfort requires it.

#### Phase 1: Investigation [DONE]
* [x] **Document Current Behavior:** Confirmed O(T×S) complexity is ~2000 constraints.
* [x] **Benchmark:**
  - Baseline (Soft): 0.47s
  - Control (None): 0.11s
  - Optimized (Hard): 0.07s
* [x] **Decision:** Proceed with Hard Constraint formulation.

#### Phase 2: Implementation [DONE]
**Goal:** Deploy the O(T) Hard Constraint logic.

* [x] **Code Changes:**
  - Modify `planner/solver/kepler.py`: Replace `water_spacing_penalty` logic with the new linear constraint.
  - Simplify `KeplerConfig`: Deprecate `water_spacing_penalty_sek` (or use it as a boolean toggle).
  - Update `planner/solver/types.py` docstrings.

* [x] **Testing:**
  - Unit tests: Verify strict spacing behavior (heater CANNOT start if within window).
  - Integration test: Verify planner solves full problem in <5s.
  - Regression test: Verify basic water heating accumulation still met.

#### Phase 3: Validation [DONE]
**Goal:** Verify production-readiness.

* [x] **Performance Verification:**
  - Run `scripts/profile_deep.py` → Target Planner <5s.
  - Stress test 1000-slot horizon.

* [x] **Documentation:**
  - Update `docs/ARCHITECTURE.md` with new constraint formulation.
  - Update `config.default.yaml` comments to explain the rigid nature of spacing.

**Exit Criteria:**
- [x] Planner execution time < 5s
- [x] Water heating obeys spacing strictly
- [x] Tests pass
---

### [DONE] REV // F13 — Socket.IO Conditional Debug

**Goal:** Refactor verbose Socket.IO logging to be **conditional** (e.g. `?debug=true`) rather than removing it completely, enabling future debugging without code changes.

**Context:** REV F11 added extensive instrumentation. Removing it entirely risks losing valuable diagnostics for future environment-specific issues (Ingress, Proxy, Etc).

**Cleanup Scope:**
- [x] Wrap `console.log` statements in `socket.ts` with a `debug` flag check.
- [x] Implement `?debug=true` URL parameter detection to enable this flag.
- [x] Keep `eslint-disable` comments (necessary for debug casting).
- [x] Update `docs/DEVELOPER.md` with instructions on how to enable debug mode.

---

### [DONE] REV // F19 — Config YAML Leaking Between Comments

**Goal:** Investigate and fix the bug where configuration keys are inserted between comments or incorrectly nested in the YAML file.

**Context:**
Users reported that after some operations (likely UI saves or auto-migrations), config keys like `grid_meter_type` or `inverter_profile` are ending up inside commented sections or in the wrong hierarchy, breaking the YAML structure or making it hard to read.

**Plan:**

#### Phase 1: Investigation [DONE]
* [x] Reproduce the behavior by performing various UI saves and triggered migrations.
* [x] Audit `backend/api/routers/config.py` save logic (ruamel.yaml configuration).
* [x] Audit `backend/config_migration.py` and `darkstar/run.sh` YAML handling.

#### Phase 2: Implementation & Cleanup [DONE]
* [x] Implement backend type coercion based on `config.default.yaml`.
* [x] Remove obsolete keys (`schedule_future_only`) and re-anchor `end_date`.
* [x] Fix visual artifacts and typos in `config.yaml`.
* [x] Verify preservation of structure in `ruamel.yaml` dumps.

---

### [PLANNED] REV // UI6 — ChartCard Overlay & Data Toggle

**Goal:** Refactor the `ChartCard` to prioritize visibility of planned actions and forecasts, with a toggleable overlay for actual historical data.

**Context:**
Currently, the charts can become cluttered when mixing planned and actual data. The user wants to ALWAYS see the plan (forecasts, scheduled actions, target SoC) as the primary view, but be able to toggle "Actual" data (load, PV, grid, real SoC) as an overlay for comparison.

**Plan:**

#### Phase 1: Frontend Refactor [PLANNED]
* [ ] Modify `ChartCard.tsx` to separate "Planned/Forecast" series from "Actual" series.
* [ ] Add a UI toggle (e.g., "Show Actual Data") to the chart controls.
* [ ] Implement conditional rendering for actual data series based on the toggle state.

#### Phase 2: Design & Polish [PLANNED]
* [ ] Ensure "Actual" data overlays are visually distinct (e.g., using dashed lines, thinner lines, or lower opacity).
* [ ] Verify legend updates correctly when toggling.


---

### [PLANNED] REV // K22 — Configurable Effekttariff Penalty

**Goal:** Allow users to dynamically control the "Peak Power" (Effekttariff) penalty via Home Assistant, enabling complex logic (seasonal/time-based) to be handled externally.

**Plan:**

#### Phase 1: Configuration & Entities
* [ ] Add `grid.import_breach_penalty_sek` (Default: 5000.0) to `config.default.yaml`.
* [ ] Add `grid.import_breach_penalty_enabled` (Default: false) to `config.default.yaml` (**User requested default OFF**).
* [ ] Add override entities to `executor.config`.

#### Phase 2: Logic & Reactivity
* [ ] **Planner Logic:** In `adapter.py` (or pipeline), if `import_breach_penalty_enabled` is False, pass `0.0` as the penalty cost to Kepler. If True, pass the configured/overridden value.
* [ ] **Watcher Logic:** In `executor/engine.py`, monitor the `import_breach_penalty_enabled` entity. If it changes, **Trigger Immediate Re-plan**. This ensures the planner schedule always reflects the current fee state.
* [ ] Frontend: Add these controls to `Settings > Grid`.

---

### [DONE] REV // H2 — Structured Logging & Management

**Goal:** Switch to structured JSON logging for better observability and allow users to download/clear logs from the UI.

**Plan:**

#### Phase 1: Logging Config [DONE]
* [x] Install `python-json-logger`.
* [x] Update `backend/main.py`:
    - Configure `JSONFormatter`.
    - Configure `TimedRotatingFileHandler` (e.g., daily rotation, keep 7 days) to `data/darkstar.log`.

#### Phase 2: Management API & UI [DONE]
* [x] `GET /api/system/logs`: Download current log file.
* [x] `DELETE /api/system/logs`: Clear/Truncate main log file.
* [x] UI: Add "Download" and "Clear" buttons to Debug page.
* [x] UI: Add "Go Live" mode with polling and **autoscroll**.
* [x] UI: Increase log container height (600px) and remove "Historical SoC" card.
* [x] UI: Display file size and "Last Rotated" info if possible.

---

### [PLANNED] REV // ARC2 — Database Migration Framework

**Goal:** Introduce `Alembic` to manage database schema migrations safely and automatically.

**Plan:**

#### Phase 1: Setup
* [ ] Add `alembic` to `requirements.txt`.
* [ ] Initialize Alembic (`alembic init`).
* [ ] Configure `alembic.ini` to use `data/planner_learning.db` (and respect `DB_PATH` env var).
* [ ] Create `env.py` to import `Base` from `backend/learning/store.py` (or creating a proper SQLAlchemy Base).

#### Phase 2: Implementation
* [ ] Refactor `LearningStore` to use SQLAlchemy models (if not fully compatible).
* [ ] Create initial migration script (`alembic revision --autogenerate -m "baseline"`).
* [ ] Update `backend/main.py` startup event to run `alembic upgrade head` instead of the custom `_init_schema` logic.
* [ ] Verify existing databases can be "stamped" with the baseline version without data loss.

---

