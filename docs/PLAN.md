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

