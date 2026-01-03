# Darkstar Energy Manager: Backlog

This document contains ideas, improvements, and tasks that are not yet scheduled for implementation. Items here are moved to [PLAN.md](PLAN.md) when they become active priorities.

---

## 🤖 AI Instructions (Read First)

1.  **Structure:** This file is organized by category. Items do **not** have strict ordering.

2.  **Naming:** Use generic names (e.g., `Settings Cleanup`, `Chart Improvements`) until the item is promoted.

3.  **Promotion Flow:** 
    - When starting work on a backlog item, assign it a proper **Rev ID** following the [naming conventions in PLAN.md](PLAN.md#revision-naming-conventions).
    - Move the item to `PLAN.md` with status `[PLANNED]` or `[IN PROGRESS]`.
    - Delete the item from this file.

4.  **Categories:**
    - **Backlog** — Concrete tasks ready for implementation
    - **On Hold** — Paused work with existing code/design
    - **Future Ideas** — Brainstorming, needs design before implementation

5.  **Format:** Use the template below for new items.

### Backlog Item Template

```
### [Category] Item Title

**Goal:** What we want to achieve.

**Notes:** Context, constraints, or design considerations.
```

---

## 📋 Backlog

### [Planner] Investigate Unexpected Export in Schedule
**Moved to [PLAN.md](PLAN.md) (Rev P1)**

---

---

### [Planner] Implement Strategic Charging (Floor Price)

**Goal:** When electricity price drops below a threshold, charge battery opportunistically.

**Current State:** `strategic_charging.price_threshold_sek` is in config but NOT used in code. Only `target_soc_percent` is used (as SoC target for cheap window expansion).

**Expected Behavior:** If price < threshold, charge to target_soc_percent regardless of other logic.

---

### [Planner] Implement Export Toggle (enable_export)

**Goal:** Allow users to disable grid export entirely via config.

**Current State:** `export.enable_export` exists in config but is not read by Kepler solver.

**Notes:** Kepler currently handles export via MILP constraints. Need to add constraint that sets max export = 0 when disabled.

---

### [Analytics] Implement Monthly Cost Analysis (IS THIS ALREADY DONE?)

**Goal:** Use `pricing.subscription_fee_sek_per_month` to show total monthly costs.

**Current State:** Config key exists but is not used anywhere in code.

**Potential Uses:**
- Calculate true break-even for battery/solar ROI
- Show monthly cost projection on Dashboard
- Include in Cost Reality comparisons

---

### [UI] Improve SmartAdvisor Appliance Recommendations

**Goal:** Make the SmartAdvisor appliance scheduling feature more useful and reliable.

**Current State:** Feature exists but recommendations are not consistently helpful.

**Tasks:**
- Review and improve scheduling algorithm
- Better integration with price data and forecasts
- Consider showing savings estimates

---

### [Planner] Implement Configurable Effekttariff Penalty

**Goal:** Allow users to configure the peak power penalty instead of hardcoded 5000 SEK/kWh.

**Current State:** `grid.import_limit_kw` is a soft constraint with fixed `IMPORT_BREACH_PENALTY = 5000` in Kepler.

**Tasks:**
- Add `grid.import_breach_penalty_sek` config key
- Read from config in Kepler solver
- Expose in Settings UI

---

### [Docs] First-Time Setup Guide

**Goal:** Create a comprehensive setup guide in `README.md` for new users.

**Scope:**
- Post-installation steps (after Docker/HA Add-on is running)
- Configure HA connection
- Set up sensors
- Configure battery/solar/water heater parameters
- Verify system is working

**Notes:** Should cover both standalone Docker and HA Add-on paths.

---

### [UI] Chart Improvements (Polish)

**Goal:** Enhance all charts with better UX and visual polish.

**Tasks:**
- Render `soc_target` as a step-line series (not smooth)
- Add zoom support (mouse wheel + controls)
- Offset tooltips to avoid covering data points
- Ensure price series includes full 24h even if schedule is partial
- Mobile responsiveness improvements

**Notes:** Needs design brainstorm before implementation.

---

### [UI] UX/UI Review

**Goal:** Comprehensive review of all tabs for usability improvements.

**Scope:**
- Review each tab for clarity and flow
- Identify confusing UI elements
- Add info/explanation buttons or hover tooltips where needed
- Mobile responsiveness audit

---
---

### [Settings] Advanced Config Audit

**Goal:** Identify missing config keys that are not yet exposed in the UI and move advanced keys to the "Advanced" tab.

**Tasks:**
- Audit `config.yaml` for keys missing in `Settings.tsx`
- Identify keys in "System" or "Parameters" tabs that belong in "Advanced"
- Implement changes in `Settings.tsx`

---
### [Planner] Proactive PV Dump (Water Heating)

**Goal:** Schedule water heating to `temp_max` proactively when PV surplus is forecasted.

**Current State:** PV dump is only handled reactively via `excess_pv_heating` override in executor.

**Proposed Change:** Kepler solver should anticipate forecasted PV surplus at SoC=100% and pre-schedule water heating.

---

### [Backend] Migrate Away from Eventlet
**Moved to [PLAN.md](PLAN.md) (Rev P1)**

---

---



### [Ops] Database Consolidation

**Goal:** Merge SQLite databases from multiple environments into one unified dataset.

**Context:**
- Local dev machine has data
- CT107 (active server) has execution history
- CT114 (bleeding edge) has data too
- Need one clean database with no gaps

**Notes:** One-time ops task. Backup everything first!

---

### [Ops] MariaDB Sunset

**Goal:** Remove MariaDB dependency and make SQLite the only database.

**Current State:** System works with SQLite only. MariaDB is optional but adds complexity.

**Tasks:**
- Audit which features still use MariaDB
- Migrate any required data/features to SQLite
- Remove MariaDB connection code
- Update documentation

**Notes:** Needs investigation before implementation.

---

### [Backend] Refactor webapp.py into Flask Blueprints
**Moved to [PLAN.md](PLAN.md) (Rev ARC1 - Superseded by FastAPI Router Migration)**

**Current State:** All API endpoints, themes, forecasts, health checks, executor logic, and database code are in one file, making it hard to maintain and test.

**Proposed Structure:**
```
backend/api/
├── __init__.py
├── schedule.py      ← /api/schedule endpoints
├── executor.py      ← /api/executor endpoints
├── health.py        ← /api/health endpoint
├── learning.py      ← /api/learning endpoints
├── forecast.py      ← /api/forecast endpoints
├── themes.py        ← /api/themes endpoints
└── config.py        ← /api/config endpoints
```

**Notes:** `aurora.py` blueprint already exists as a good pattern to follow.

---

### [Backend] Add SQLite Connection Pooling

**Goal:** Reuse database connections instead of creating new ones for each request.

**Current State:** Each API request creates a new SQLite connection:
```python
with sqlite3.connect(engine.db_path, timeout=30.0) as conn:  # Every request!
```

**Impact:** May cause contention under high concurrency.

**Options:**
- Use `threading.local()` for thread-local connections
- Use `sqlalchemy` connection pooling (would require larger refactor)
- Use `aiosqlite` for async SQLite (if migrating from eventlet)

---

### [Ops] Update Docker HEALTHCHECK Endpoint

**Goal:** Use the comprehensive `/api/health` endpoint instead of `/api/status`.

**Current State:** Dockerfile uses:
```dockerfile
HEALTHCHECK ... CMD curl -f http://localhost:5000/api/status || exit 1
```

**Improvement:** `/api/health` performs comprehensive checks (config, HA connection, entities, database) so Docker can detect more issues.

**Change:**
```dockerfile
HEALTHCHECK ... CMD curl -f http://localhost:5000/api/health | grep -q '"healthy":true' || exit 1
```

---

### [Planner] Robustness: Schedule Persistence and Retry on Failure
**Moved to [PLAN.md](PLAN.md) (Rev P1)**

---

---

## ⏸️ On Hold

### Rev 63 — Export What-If Simulator

**Goal:** Deterministic way to answer "what if we export X kWh at tomorrow's price peak?" - show net SEK impact.

**Status:** On Hold (prototype exists but parked for Kepler pivot).

**Notes:** The current "Lab" tab was meant for this but needs complete redesign.

---

## 🔜 Future Ideas

### [Planner] Effekttariffer (Power Tariffs)

**Goal:** Support Swedish "effekttariff" (peak demand charges) in the planner.

**Concept:** Penalty for high grid import during certain hours. Planner needs to know about this to optimize import timing.

**Notes:** Needs design brainstorm. Would affect Kepler solver constraints.

---

### [Planner] Smart EV Integration

**Goal:** Prioritize home battery vs EV charging based on departure time.

**Inputs Needed:**
- EV departure time (user input or calendar integration)
- EV target SoC
- EV charger entity

**Notes:** Big feature. Requires careful UX design.

---

### [Lab] What-If Simulator Redesign

**Goal:** Redesign the Lab tab as a proper what-if simulator.

**Features:**
- Change battery size, PV array size, etc.
- See impact on daily/monthly costs
- Compare current vs hypothetical systems

**Notes:** Lab tab is currently hidden. Needs complete redesign before reactivation.

---

### [UI] Contextual Help System

**Goal:** Add info buttons and hover tooltips throughout the UI.

**Features:**
- Small (i) icons next to complex settings
- Hover for quick explanation
- Click for detailed help modal

---

### [Aurora] Multi-Model Forecasting

**Goal:** Separate ML models for different contexts.

**Ideas:**
- Season-specific models (summer/winter)
- Weekday vs weekend models
- Holiday-aware models

---

### [Admin] Admin Tools

**Goal:** Add admin tooling for system maintenance.

**Features:**
- Force ML Retrain button
- Clear Learning Cache button  
- Reset Learning for Today button (Debug tool)

---



### [Planner] Investigate Charge vs PV Logic
**Moved to [PLAN.md](PLAN.md) (Rev P1)**

---

---


---

### [Security] SEC-001: Separation of Secrets and Config

**Goal:** Prevent sensitive credentials (secrets.yaml) from being inadvertently saved into config.yaml via the Settings API.

**Current State:** The backend merges secrets into the config for the frontend to display. If the user saves settings, the frontend sends back the full config (including secrets), and the backend writes it to `config.yaml`. This duplicates secrets and risks committing them to version control if config.yaml is not ignored (it typically is, but still bad practice).

**Expected Behavior:** The backend should strip secrets from the payload before saving to `config.yaml`, OR the frontend should manage secrets via a dedicated API endpoint.

---
