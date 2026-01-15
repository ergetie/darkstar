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

> **Source:** Items marked with `(REVIEW-2026-01-04)` are from Comprehensive Codebase Review dated 2026-01-04.

---

---
## USER ADDED BACKLOG ITEMS (NEEDS TO BE RE-WRITTEN)

- Hide water power sensor in power flow card when not enabled
- Support multiple heating sources
- Remove live system card
- Toggle for soc_target entity (some inverters dont use it)
- Support different inverter profiles
- Hard to read chartCard on mobile due to big tool tip
- A beta tester (Kristoffer) reports this: "I Fronius Modbus integrationen behöver sätta Storage Control Mode samt ange värde på i watt på entitet för charge, discharge etc. Man har flertalet val under storage contol mode. Det kanske skulle varamöjligt att lsa med extra helpers och trigga automationer baserat på förändringar och översätta A till W men det känns lite för komplext. Du räknar ju redan idag ut hur många Watt som det skall laddas med så om du kunde få till det direkt i darkstar, skulle vara bäst att använda samma entiter men att du hade en switch som angav om man använde A eller W?" This is for "max_charge_current" and "max_discharge_current" entities for example.
- Add both "input_sensors:
  grid_import_power: sensor.their_import_sensor
  grid_export_power: sensor.their_export_sensor"
  To the UI!
- 
---

## 🔴 High Priority

### [UI] Advisor Overhaul

**Goal:** Redesign and improve the Advisor feature to provide more actionable and reliable energy insights.

**Notes:** Current version is disabled/hidden as it needs a complete overhaul. Should integrate better with Kepler schedules and Aurora forecasts.

---

### [UI/Settings] Support dual grid power sensors

**Goal:** Some users have a split import and export grid power sensors, we need support for both dual sensors and a single sensor with positive and negative values.


### [AURORA] Support multiple MPPT strings

**Goal:** Some users have multiple MPPT strings, we need to support this in the Aurora forecast.

### [BACKEND] Busy port allocation

**Goal:** Some users report that the backend service is not starting because the port is already in use by another add-on. How do we make this more dynamic?

## 🟡 Medium Priority

### [Refactor] Move inputs.py to Proper Module

**Goal:** Move `inputs.py` from project root to a proper module location (e.g., `planner/inputs.py` or `core/inputs.py`) for cleaner project structure.

**Current State:** 
- `inputs.py` is a 42KB file in project root
- 29 files import from it across `backend/`, `bin/`, `tests/`, `ml/`
- Contains config loading, HA sensor fetching, Nordpool API, and data utilities

**Impact:**
- All 29 importing files need path updates
- Relative imports in tests and scripts need adjustment
- Python path considerations for different entry points

**Implementation:**
1. Create `core/` module with `__init__.py`
2. Move `inputs.py` → `core/inputs.py`
3. Update all imports: `from inputs import` → `from core.inputs import`
4. Update any relative path references
5. Verify all entry points work (`uvicorn`, `bin/run_planner.py`, tests)

**Effort:** 3-4 hours (careful refactor + testing all entry points)

---

### [Testing] Add CI/CD Automation (REVIEW-2026-01-04)

**Goal:** Automate linting, testing, and build verification on every push/PR to catch regressions before merge.

**Current State:** 
- CI/CD only builds Home Assistant add-on on tag push
- No automated testing
- No lint checks in CI
- No vulnerability scanning

**Proposed GitHub Actions Workflows:**

1. **`.github/workflows/test.yml`** (Run on every push/PR)
   ```yaml
   - Frontend: pnpm lint, pnpm test
   - Backend: ruff check ., pytest --cov
   - Report coverage to Codecov/Coveralls
   ```

2. **`.github/workflows/security.yml`** (Weekly + on PR)
   ```yaml
   - pip-audit (Python vulnerabilities)
   - pnpm audit (npm vulnerabilities)
   - ruff check --select=S (security lints)
   ```

3. **`.github/workflows/build.yml`** (On PR)
   ```yaml
   - Build Docker image
   - Verify startup (docker run + health check)
   ```

**Benefits:**
- Catch bugs before merge
- Enforce code quality standards
- Security vulnerability alerts

**Effort:** 2-3 hours (create workflows + test)

---

### [Database] Add Migration Framework (REVIEW-2026-01-04)

**Goal:** Enable safe, version-controlled database schema evolution without manual SQL.

**Current State:** 
- SQLite schema changes are manual
- No migration tracking
- Risk of schema drift between environments

**Implementation Options:**

1. **Alembic** (Standard Python migrations)
   - Pros: Industry standard, autogenerate migrations, version tracking
   - Cons: Adds dependency, learning curve
   - Setup: `pip install alembic`, `alembic init`, create initial migration

2. **Simple Version Table** (Lightweight custom solution)
   - Add `schema_version` table with single row
   - Store migration scripts in `migrations/` directory (001_initial.sql, 002_add_battery_cost.sql, etc.)
   - Custom Python script applies pending migrations
   - Pros: Simple, no dependencies
   - Cons: Manual migration writing, no rollback

**Recommendation:** Start with Alembic for long-term maintainability.

**Database File:** `planner_learning.db`

**Tables to Manage:**
- `slot_plans`, `execution_log`, `slot_forecasts`, `vacation_state`, `battery_cost`

**Effort:** 3-4 hours (setup Alembic + create initial migration + docs)

---

### [Dependencies] Audit and Update Outdated Packages (REVIEW-2026-01-04)

**Goal:** Update dependencies to latest stable versions for security patches and new features.

**Current State:** Dependency versions not audited recently.

**Commands to Run:**
```bash
# Frontend
cd frontend && pnpm outdated

# Backend
pip list --outdated
```

**Review Considerations:**
- **React 19**: Bleeding edge, verify stability before production
- **FastAPI**: Check for breaking changes in 0.109+ → latest
- **LightGBM**: Check for model compatibility if updating
- **Chart.js**: Review changelog for breaking changes

**Process:**
1. Run `pnpm outdated` and `pip list --outdated`
2. Review changelogs for major version bumps
3. Update in batches (frontend, backend, ML separately)
4. Run full test suite after each batch
5. Manual smoke testing for UI changes

**Effort:** 2-4 hours (depending on breaking changes)

---

---

### [Frontend] Accessibility Audit (REVIEW-2026-01-04)

**Goal:** Ensure WCAG AA compliance for broader user base including users with disabilities.

**Current State:** 
- Modern UI with good visual design
- Accessibility not explicitly tested
- No ARIA labels verified
- Keyboard navigation not tested
- Color contrast not verified

**Audit Process:**

1. **Automated Tools:**
   - Chrome DevTools Lighthouse: Accessibility score
   - axe DevTools extension: Scan all pages
   - WAVE extension: Visual accessibility feedback

2. **Manual Testing:**
   - Keyboard navigation (Tab, Enter, Esc)
   - Screen reader testing (NVDA/JAWS on Windows, VoiceOver on Mac)
   - Color contrast checker (WebAIM)
   - Focus indicators visible
   - Form labels present

3. **Common Issues to Check:**
   - Images without alt text
   - Buttons without accessible names
   - Form inputs without labels
   - Insufficient color contrast
   - Missing skip links
   - Div/span used instead of semantic HTML

**Fixes:**
- Add ARIA labels to icon buttons
- Ensure all form inputs have labels
- Add skip navigation link
- Verify color contrast ratios (min 4.5:1 for text)
- Use semantic HTML (`<button>`, `<nav>`, `<main>`, etc.)

**Effort:** 4-6 hours (audit + fixes)

---

---

---

### [Backend] Split services.py Router (REVIEW-2026-01-04)

**Goal:** Improve maintainability by splitting the large `services.py` router (740 LOC) into focused modules.

**Current State:** `backend/api/routers/services.py` contains two distinct responsibilities:
1. Home Assistant integration endpoints (`/api/ha/*`)
2. Energy data endpoints (`/api/energy/*`, `/api/water/*`)

**Proposed Split:**

1. **`backend/api/routers/ha.py`** - Home Assistant Integration
   - `/api/ha/entity/{entity_id}`
   - `/api/ha/average`
   - `/api/ha/entities`
   - `/api/ha/services`
   - `/api/ha/connection/test`
   - `/api/ha/socket/status`

2. **`backend/api/routers/energy.py`** - Energy Data
   - `/api/energy/today`
   - `/api/energy/range`
   - `/api/water/today`
   - `/api/water/boost` (GET, POST, DELETE)
   - `/api/performance`

3. **Extract Shared Utilities:**
   - `_fetch_ha_history_avg()` → `backend/utils/ha.py`
   - Config loading helpers → reuse from `inputs.py`

**Benefits:**
- Easier to navigate
- Clearer separation of concerns
- Reduced merge conflicts

**Effort:** 2 hours (refactor + update imports + test)

---

### [Planner] Implement Export Toggle (enable_export)

**Goal:** Allow users to disable grid export entirely via config.

**Current State:** `export.enable_export` exists in config but is not read by Kepler solver.

**Notes:** Kepler currently handles export via MILP constraints. Need to add constraint that sets max export = 0 when disabled.

**Source:** Existing backlog item + REVIEW-2026-01-04 (unused config key)

---

### [Analytics] Implement Monthly Cost Analysis (IS THIS ALREADY DONE?)

**Goal:** Use `pricing.subscription_fee_sek_per_month` to show total monthly costs.

**Current State:** Config key exists but is not used anywhere in code.

**Potential Uses:**
- Calculate true break-even for battery/solar ROI
- Show monthly cost projection on Dashboard
- Include in Cost Reality comparisons

**Source:** Existing backlog item + REVIEW-2026-01-04 (unused config key)

---

### [ML] Add Model Versioning (REVIEW-2026-01-04)

**Goal:** Track which ML model version made which forecast for debugging and A/B testing.

**Current State:** 
- LightGBM models stored as pickle files in `ml/models/`
- No version metadata
- No tracking of which model generated which forecast

**Implementation:**

1. **Model Metadata File:**
   ```python
   # ml/models/load_forecast_v3.metadata.json
   {
     "model_name": "load_forecast",
     "version": "3",
     "trained_at": "2026-01-04T12:00:00Z",
     "training_data_range": "2025-01-01 to 2026-01-01",
     "features": ["hour", "day_of_week", "temperature", ...],
     "metrics": {
       "mae": 0.45,
       "rmse": 0.67,
       "r2": 0.92
     },
     "git_commit": "abc123def",
     "config_hash": "md5hash"
   }
   ```

2. **Log Model Version:**
   - Add `model_version` column to `slot_forecasts` table
   - Log version when storing forecasts in `planner/observability/recorder.py`

3. **API Endpoint:**
   - `GET /api/aurora/models` - List available models with metadata
   - `GET /api/aurora/models/{name}/history` - Compare model versions over time

**Benefits:**
- Debug forecast accuracy regressions
- A/B test new models
- Rollback to previous model if needed

**Effort:** 3-4 hours (implement versioning + update recorder + add API)

---

---

## 🟢 Low Priority

### [Docs] Add Migration Guide (v1→v2) (REVIEW-2026-01-04)

**Goal:** Help existing Darkstar v1 users migrate to v2 (Kepler architecture).

**Current State:** No migration guide exists.

**Content:**
- Breaking changes (heuristic planner → Kepler MILP)
- Config file changes
- Database migration (if applicable)
- What to expect (different schedules, better optimization)
- Rollback plan if needed

**Effort:** 2 hours (write guide)

---

### [Testing] Add E2E Tests (REVIEW-2026-01-04)

**Goal:** Add end-to-end tests to catch UI regressions and integration bugs.

**Current State:** 
- Backend has 187 unit/integration tests
- Frontend has vitest configured but minimal usage
- No E2E tests for user flows

**Implementation:**

1. **Choose Framework:** Playwright (recommended) or Cypress
2. **Critical User Flows to Test:**
   - Dashboard loads and displays schedule
   - Executor pause/resume works
   - Settings save and validation
   - Water boost activation
   - Manual planner run

3. **Setup:**
   ```bash
   cd frontend
   pnpm add -D @playwright/test
   npx playwright install
   ```

4. **Example Test:**
   ```typescript
   test('dashboard displays schedule', async ({ page }) => {
     await page.goto('http://localhost:5173');
     await expect(page.locator('h1')).toContainText('Dashboard');
     await expect(page.locator('.chart-card')).toBeVisible();
   });
   ```

**Benefits:**
- Catch UI regressions
- Confidence in refactoring
- Documentation of expected behavior

**Effort:** 8 hours (setup + write initial tests)

---

### [Logging] Structured JSON Logs (REVIEW-2026-01-04)

**Goal:** Use structured JSON logging for easier parsing and log aggregation.

**Current State:** Python `logging` module with text format.

**Implementation:**
```bash
pip install python-json-logger
```

```python
# backend/main.py
from pythonjsonlogger import jsonlogger

handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    '%(asctime)s %(name)s %(levelname)s %(message)s'
)
handler.setFormatter(formatter)
logging.root.addHandler(handler)
```

**Output:**
```json
{"asctime": "2026-01-04 12:00:00", "name": "darkstar.api", "levelname": "INFO", "message": "Dashboard loaded", "duration_ms": 45}
```

**Benefits:**
- Easy parsing with jq, Splunk, ELK
- Machine-readable
- Add contextual fields (request_id, user_id, etc.)

**Effort:** 2 hours (implement + test)

---

### [Backend] Add SQLite Connection Pooling (REVIEW-2026-01-04)

**Goal:** Reuse database connections instead of creating new ones for each request.

**Current State:** Each API request creates a new SQLite connection:
```python
with sqlite3.connect(engine.db_path, timeout=30.0) as conn:  # Every request!
```

**Impact:** May cause contention under high concurrency.

**Implementation Options:**

1. **Thread-Local Connections:**
   ```python
   import threading
   _thread_local = threading.local()
   
   def get_db():
       if not hasattr(_thread_local, "db"):
           _thread_local.db = sqlite3.connect(DB_PATH)
       return _thread_local.db
   ```

2. **Async with aiosqlite Pool:**
   ```python
   # For async routes only
   import aiosqlite
   
   async def get_db():
       async with aiosqlite.connect(DB_PATH) as db:
           yield db
   ```

3. **SQLAlchemy Connection Pool:**
   - Pros: Battle-tested, handles async
   - Cons: Large refactor, adds dependency

**Recommendation:** Start with thread-local for sync code, `aiosqlite` already used for async routes.

**Effort:** 3 hours (implement + test)

**Source:** Existing backlog item + confirmed by REVIEW-2026-01-04

---

---

---

---

---

### [UI] Improve SmartAdvisor Appliance Recommendations

**Goal:** Make the SmartAdvisor appliance scheduling feature more useful and reliable.

**Current State:** Feature exists but recommendations are not consistently helpful.

**Tasks:**
- Review and improve scheduling algorithm
- Better integration with price data and forecasts
- Consider showing savings estimates

**Source:** Existing backlog item

---

### [Planner] Implement Configurable Effekttariff Penalty

**Goal:** Allow users to configure the peak power penalty instead of hardcoded 5000 SEK/kWh.

**Current State:** `grid.import_limit_kw` is a soft constraint with fixed `IMPORT_BREACH_PENALTY = 5000` in Kepler.

**Tasks:**
- Add `grid.import_breach_penalty_sek` config key
- Read from config in Kepler solver
- Expose in Settings UI

**Source:** Existing backlog item

---

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

**Source:** Existing backlog item

---

### [UI] UX/UI Review

**Goal:** Comprehensive review of all tabs for usability improvements.

**Scope:**
- Review each tab for clarity and flow
- Identify confusing UI elements
- Add info/explanation buttons or hover tooltips where needed
- Mobile responsiveness audit

**Source:** Existing backlog item

---

---

### [Planner] Proactive PV Dump (Water Heating)

**Goal:** Schedule water heating to `temp_max` proactively when PV surplus is forecasted.

**Current State:** PV dump is only handled reactively via `excess_pv_heating` override in executor.

**Proposed Change:** Kepler solver should anticipate forecasted PV surplus at SoC=100% and pre-schedule water heating.

**Source:** Existing backlog item

---

### [Ops] Database Consolidation

**Goal:** Merge SQLite databases from multiple environments into one unified dataset.

**Context:**
- Local dev machine has data
- CT107 (active server) has execution history
- CT114 (bleeding edge) has data too
- Need one clean database with no gaps

**Notes:** One-time ops task. Backup everything first!

**Source:** Existing backlog item

---

## ⏸️ On Hold

### Rev 63 — Export What-If Simulator

**Goal:** Deterministic way to answer "what if we export X kWh at tomorrow's price peak?" - show net SEK impact.

**Status:** On Hold (prototype exists but parked for Kepler pivot).

**Notes:** The current "Lab" tab was meant for this but needs complete redesign.

---

## 🔜 Future Ideas

### [Planner] Effekttariffer (Power Tariffs) (REVIEW-2026-01-04)

**Goal:** Support Swedish "effekttariff" (peak demand charges) in the planner.

**Concept:** Penalty for high grid import during certain hours. Planner needs to know about this to optimize import timing.

**Design Considerations:**
- Peak demand window detection (typically 16:00-20:00 on weekdays)
- Monthly peak tracking
- Penalty cost modeling in Kepler objective function
- Config: `grid.peak_demand_tariff.enabled`, `grid.peak_demand_tariff.penalty_sek_per_kw`

**Impact:** High complexity - affects Kepler solver constraints and requires new state tracking.

**Effort:** 1-2 weeks (design + implement + test)

**Notes:** Needs design brainstorm. Would affect Kepler solver constraints.

**Source:** Existing backlog item + expanded by REVIEW-2026-01-04

---

### [Planner] Smart EV Integration (REVIEW-2026-01-04)

**Goal:** Prioritize home battery vs EV charging based on departure time.

**Inputs Needed:**
- EV departure time (user input or calendar integration)
- EV target SoC
- EV charger entity (Home Assistant switch/sensor)
- EV battery capacity

**Implementation:**
- Add EV as second battery in Kepler MILP
- Constraint: EV must reach target SoC by departure time
- Policy: Prefer charging EV during cheap windows, home battery if surplus
- UI: EV configuration tab, departure time scheduler

**Complexity:** High (new subsystem, requires MILP solver changes)

**ROI:** High for EV owners

**Effort:** 2-3 weeks (design + implement + test)

**Notes:** Big feature. Requires careful UX design.

**Source:** Existing backlog item + expanded by REVIEW-2026-01-04

---

### [Lab] What-If Simulator Redesign (REVIEW-2026-01-04)

**Goal:** Redesign the Lab tab as a proper what-if simulator.

**Features:**
- Change battery size, PV array size, etc.
- See impact on daily/monthly costs
- Compare current vs hypothetical systems
- ROI calculator for battery/solar upgrades

**Implementation:**
- Simulation engine: Run planner with modified config
- Historical playback: Replay past days with new config
- Comparison dashboard: Side-by-side metrics

**Complexity:** High (new feature set)

**Effort:** 2 weeks (design + implement)

**Notes:** Lab tab is currently hidden. Needs complete redesign before reactivation.

**Source:** Existing backlog item + expanded by REVIEW-2026-01-04

---

### [Aurora] Multi-Model Forecasting (REVIEW-2026-01-04)

**Goal:** Separate ML models for different contexts to improve forecast accuracy.

**Ideas:**
- Season-specific models (summer/winter) - Different PV patterns
- Weekday vs weekend models - Different load patterns
- Holiday-aware models - Special day detection

**Implementation:**
- Model selector in `ml/forward.py`
- Context detection (date, season, holiday calendar)
- Ensemble predictions (average multiple models)

**Challenges:**
- More models to train and maintain
- Switching logic complexity
- Storage overhead

**Effort:** 1-2 weeks (implement + retrain models)

**Source:** Existing backlog item + expanded by REVIEW-2026-01-04

---

### [Admin] Admin Tools (REVIEW-2026-01-04)

**Goal:** Add admin tooling for system maintenance and troubleshooting.

**Features:**
- Force ML Retrain button (trigger `ml/train.py` via API)
- Clear Learning Cache button (delete cached forecasts)
- Reset Learning for Today button (Debug tool - clear today's telemetry)
- View Logs (stream logs to UI)
- Database Stats (table sizes, row counts)
- Health Check Details (expanded view beyond /api/health)

**Implementation:**
- New `/admin` page in frontend (protected route)
- Admin API endpoints in `backend/api/routers/admin.py`
- Authentication/authorization (if multi-user)

**Effort:** 1 week (design + implement)

**Source:** Existing backlog item + expanded by REVIEW-2026-01-04

---
