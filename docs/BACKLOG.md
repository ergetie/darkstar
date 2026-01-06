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

## 🔴 High Priority

### [Docs] Update Flask→FastAPI References (REVIEW-2026-01-04)

**Goal:** Update all documentation references from old Flask+eventlet architecture to current FastAPI+uvicorn implementation.

**Current State:** Documentation mentions Flask, `eventlet`, `webapp.py`, and old subprocess scheduler in several places.

**Locations to Update:**
- `AGENTS.md` Line 52: References Flask (should be FastAPI)
- `AGENTS.md` Line 59: Mentions `python backend/run.py` and `eventlet` (should be `uvicorn backend.main:app`)
- `AGENTS.md` Line 144: References `webapp.py` (should be `main.py`)
- `DEVELOPER.md` Lines 52-59: Describes Flask backend with eventlet WebSocket server
- `DEVELOPER.md` Lines 144-147: References old backend structure (`backend/webapp.py`)
- `DEVELOPER.md`: Mentions scheduler.py as separate process (now in-process via ARC8)

**Impact:** Confusing for new developers, may lead to setup errors.

**Effort:** 15-30 minutes (find/replace + verification)

---

### [Security] SEC-001: Separation of Secrets and Config (REVIEW-2026-01-04)

**Goal:** Prevent sensitive credentials (secrets.yaml) from being inadvertently saved into config.yaml via the Settings API.

**Current State:** The backend merges secrets into the config for the frontend to display. If the user saves settings, the frontend sends back the full config (including secrets), and the backend writes it to `config.yaml`. This duplicates secrets and risks committing them to version control if config.yaml is not ignored (it typically is, but still bad practice).

**Expected Behavior:** The backend should strip secrets from the payload before saving to `config.yaml`, OR the frontend should manage secrets via a dedicated API endpoint.

**Security Impact:** Medium severity - secrets could leak to version control if `.gitignore` misconfigured.

**Implementation Options:**
1. **Strip on Save**: Modify `POST /api/config/save` to strip secrets from payload before writing
2. **Dedicated Endpoint**: Create `POST /api/secrets` endpoint for secret management
3. **Hybrid**: Read-only secrets in config endpoint, separate write endpoint for secrets

**Location:** `backend/api/routers/config.py`

**Effort:** 1-2 hours (design decision + implementation + testing)

---

## 🟡 Medium Priority

### [Testing] Add Coverage Tracking (REVIEW-2026-01-04)

**Goal:** Track test coverage metrics to identify untested code paths and set coverage goals.

**Current State:** 
- Test suite exists with 187 tests across 31 files
- No coverage tracking configured
- Coverage metrics not reported in CI/CD

**Implementation:**
- ✅ Add `pytest-cov>=4.1.0` to `requirements-dev.txt` (DONE)
- Add coverage configuration to `pyproject.toml`:
  ```toml
  [tool.coverage.run]
  source = ["backend", "ml", "planner", "executor"]
  omit = ["*/tests/*", "*/debug/*", "*/__pycache__/*"]
  
  [tool.coverage.report]
  exclude_lines = ["pragma: no cover", "if TYPE_CHECKING:", "raise NotImplementedError"]
  ```
- Run with: `pytest --cov=backend --cov=ml --cov=planner --cov-report=html --cov-report=term`
- Set coverage goal: **Target 80%+ overall coverage**

**Benefits:**
- Identify untested edge cases
- Prevent coverage regression
- Confidence in refactoring

**Effort:** 1 hour (setup) + ongoing (write missing tests)

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

### [Docs] Add API Documentation Link (REVIEW-2026-01-04)

**Goal:** Make it easy for users/developers to discover the auto-generated FastAPI API documentation.

**Current State:** FastAPI generates OpenAPI docs at `/docs` and `/redoc` but this isn't documented in README.

**Implementation:**
Add to `README.md` under "Dashboard" section:
```markdown
## 📱 Dashboard & API

Access the web UI at **http://localhost:5000**

**API Documentation:**
- OpenAPI Interactive Docs: http://localhost:5000/docs (Swagger UI)
- ReDoc Documentation: http://localhost:5000/redoc (Alternative UI)
- OpenAPI Schema: http://localhost:5000/openapi.json
```

**Also Update:** `docs/DEVELOPER.md` with API documentation section explaining:
- How to use /docs for testing endpoints
- Authentication (if applicable)
- WebSocket endpoints (not in OpenAPI, document separately)

**Effort:** 5-10 minutes

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

### [Docker] Add Health Check (REVIEW-2026-01-04)

**Goal:** Enable container orchestration tools (Docker Swarm, Kubernetes) to detect if the container is healthy.

**Current State:** No HEALTHCHECK directive in Dockerfile.

**Implementation:**
Add to `Dockerfile`:
```dockerfile
# After EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:5000/api/health || exit 1
```

**Also Update:** `docker-compose.yml` if present:
```yaml
services:
  darkstar:
    # ... existing config ...
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

**Note:** Ensure `curl` is available in the Docker image (or use `wget` or Python `requests` alternative).

**Effort:** 30 minutes (add + test)

---

### [Docs] Add Backup/Restore Guide (REVIEW-2026-01-04)

**Goal:** Provide users with clear instructions for backing up critical data and restoring after failures.

**Current State:** No documented backup strategy for `planner_learning.db`.

**Critical Data to Backup:**
- `planner_learning.db` - Historical forecasts, execution logs, learned parameters
- `schedule.json` - Current schedule (regenerated, but useful for debugging)
- `config.yaml` - User configuration
- `secrets.yaml` - Credentials
- ML models in `ml/models/` - Trained LightGBM models

**Backup Strategy:**

1. **Manual Backup:**
   ```bash
   # Create backup directory
   mkdir -p ~/darkstar-backups/$(date +%Y%m%d)
   
   # Backup database
   cp /opt/darkstar/planner_learning.db ~/darkstar-backups/$(date +%Y%m%d)/
   
   # Backup config (optional if tracked in git)
   cp /opt/darkstar/config.yaml ~/darkstar-backups/$(date +%Y%m%d)/
   cp /opt/darkstar/secrets.yaml ~/darkstar-backups/$(date +%Y%m%d)/
   
   # Backup ML models
   cp -r /opt/darkstar/ml/models/ ~/darkstar-backups/$(date +%Y%m%d)/
   ```

2. **Automated Backup (Cron):**
   ```bash
   # Add to crontab (daily at 3 AM)
   0 3 * * * /opt/darkstar/scripts/backup.sh
   ```

3. **Restore:**
   ```bash
   # Stop Darkstar
   systemctl stop darkstar
   
   # Restore database
   cp ~/darkstar-backups/20260104/planner_learning.db /opt/darkstar/
   
   # Restart
   systemctl start darkstar
   ```

**Documentation Location:** Create `docs/OPERATIONS.md` with backup/restore, monitoring, and troubleshooting.

**Effort:** 1 hour (write docs + create backup script)

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

### [Planner] Implement Strategic Charging (Floor Price)

**Goal:** When electricity price drops below a threshold, charge battery opportunistically.

**Current State:** `strategic_charging.price_threshold_sek` is in config but NOT used in code. Only `target_soc_percent` is used (as SoC target for cheap window expansion).

**Expected Behavior:** If price < threshold, charge to target_soc_percent regardless of other logic.

**Source:** Existing backlog item + REVIEW-2026-01-04 (unused config key)

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

### [Ops] MariaDB Sunset (REVIEW-2026-01-04)

**Goal:** Remove MariaDB dependency and make SQLite the only database.

**Current State:** System works with SQLite only. MariaDB is optional but adds complexity.

**Tasks:**
- Audit which features still use MariaDB
- Migrate any required data/features to SQLite
- Remove MariaDB connection code (`backend/learning/mariadb_sync.py`)
- Remove MariaDB from `requirements.txt` (`pymysql`)
- Update documentation (remove MariaDB setup instructions)

**Locations:**
- `backend/learning/mariadb_sync.py` - Optional sync service
- `docs/DEVELOPER.md` Line 21 - Lists MariaDB as required (should say "Optional")

**Benefits:**
- Simpler deployment
- Fewer dependencies
- One less thing to configure

**Effort:** 4 hours (audit + migrate/remove + test + docs)

**Source:** Existing backlog item + confirmed by REVIEW-2026-01-04

---

## 🟢 Low Priority

### [Docs] Add KEPLER_VISION.md (REVIEW-2026-01-04)

**Goal:** Create the long-term vision document for the Kepler MILP solver roadmap.

**Current State:** 
- Referenced in `GEMINI.md` as Single Source of Truth for "Long-term roadmap and design philosophy"
- File does not exist

**Content to Include:**
- Evolution from heuristic MPC to MILP
- Design philosophy (declarative optimization vs imperative logic)
- Future solver enhancements (e.g., multi-objective optimization, quadratic costs)
- Integration with Aurora ML (forecast uncertainty in constraints)
- Advanced features (EV charging, heat pump scheduling, dynamic tariffs)

**Effort:** 2 hours (write vision doc)

---

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

### [CI/CD] Add Dependabot/Snyk (REVIEW-2026-01-04)

**Goal:** Automated security vulnerability alerts for dependencies.

**Current State:** No automated security scanning.

**Implementation:**

1. **Dependabot (GitHub Native):**
   Create `.github/dependabot.yml`:
   ```yaml
   version: 2
   updates:
     - package-ecosystem: "pip"
       directory: "/"
       schedule:
         interval: "weekly"
     - package-ecosystem: "npm"
       directory: "/frontend"
       schedule:
         interval: "weekly"
   ```

2. **Snyk (Alternative):**
   - Sign up at snyk.io
   - Connect GitHub repo
   - Automatic PR scanning + alerts

**Benefits:**
- Security vulnerability alerts
- Automated dependency updates
- CVE tracking

**Effort:** 1 hour (setup GitHub integration)

---

### [UI] Contextual Help System (REVIEW-2026-01-04)

**Goal:** Add info buttons and hover tooltips throughout the UI to improve onboarding.

**Features:**
- Small (i) icons next to complex settings
- Hover for quick explanation
- Click for detailed help modal

**Implementation:**

1. **Create Tooltip Component:**
   ```tsx
   // frontend/src/components/HelpTooltip.tsx
   interface Props {
     title: string;
     content: string;
     learnMoreUrl?: string;
   }
   ```

2. **Add to Settings Fields:**
   ```tsx
   <label>
     S-Index Risk Appetite
     <HelpTooltip 
       title="Risk Appetite"
       content="Controls how conservative the planner is. 1=Safety first, 5=Maximize profit."
       learnMoreUrl="/docs/architecture#s-index"
     />
   </label>
   ```

3. **Style:**
   - Small (i) icon, subtle color
   - Tooltip appears on hover
   - Click opens modal with detailed explanation
   - Link to docs for deep dive

**Effort:** 6 hours (create component + add to ~20 settings)

**Source:** Existing backlog item + prioritized by REVIEW-2026-01-04

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

### [Docs] Version Bump Process Checklist (REVIEW-2026-01-04)

**Goal:** Ensure consistent releases with a documented checklist.

**Current State:** Version bump process documented in `AGENTS.md` and `DEVELOPER.md` but no formal checklist.

**Implementation:**
Add to `docs/DEVELOPER.md` under "Releases" section:

```markdown
### Release Checklist

- [ ] Update version in `darkstar/config.yaml` (add-on manifest)
- [ ] Update version in `darkstar/run.sh` (startup banner)
- [ ] Update version in `frontend/package.json`
- [ ] Update `CHANGELOG.md` with release notes
- [ ] Commit: `git commit -m "chore: bump version to vX.Y.Z"`
- [ ] Tag: `git tag vX.Y.Z`
- [ ] Push: `git push origin main && git push origin vX.Y.Z`
- [ ] Verify CI/CD build succeeds (check GitHub Actions)
- [ ] Test Docker image: `docker pull ghcr.io/ergetie/darkstar:X.Y.Z`
- [ ] Test HA Add-on update
- [ ] Create GitHub release with changelog
```

**Effort:** 30 minutes (write checklist)

---

### [Backend] Remove Deprecated scheduler.py (MEGA-AUDIT-2026-01-04)

**Goal:** Remove the deprecated standalone scheduler file to prevent confusion and accidental usage.

**Current State:** 
- `backend/scheduler.py` is marked DEPRECATED in Rev ARC8
- Scheduler now runs in-process via `backend/services/scheduler_service.py`
- Old file still exists in repository

**Context:** 
Per ARC8 Phase 4, the standalone scheduler was replaced with an in-process async background task. The old file was kept for backward compatibility but should now be removed.

**Options:**
1. **Delete entirely** - Cleanest approach if truly deprecated
2. **Move to archive/** - Preserve for reference
3. **Keep with prominent warning** - If some users still depend on it

**Recommendation:** Move to `archive/backend_scheduler_deprecated.py` with a README explaining the migration.

**Files to Update:**
- Remove or move `backend/scheduler.py`
- Check if any scripts reference it (e.g., systemd services, Docker CMD)
- Update docs if they reference the old scheduler

**Effort:** 30 minutes

---

### [Backend] Audit backend/run.py Usage (REVIEW-2026-01-04)

**Goal:** Determine if `backend/run.py` is still needed or if it's redundant with `backend/main.py`.

**Current State:**
- `backend/run.py` exists as a Uvicorn wrapper
- `backend/main.py` is the standard ASGI entry point
- Unclear which is canonical

**Investigation Required:**
1. Check how production deployment uses it (Docker CMD, systemd)
2. Check if `pnpm run dev` scripts reference it
3. Determine if it adds value over `uvicorn backend.main:app`

**Outcomes:**
- **If needed:** Document its purpose clearly in comments
- **If redundant:** Remove it and update any references
- **If convenience wrapper:** Rename to `backend/uvicorn_wrapper.py` for clarity

**Effort:** 30 minutes (audit + decision + cleanup)

---

### [Code Quality] Fix Duplicate Code in learning/engine.py (MEGA-AUDIT-2026-01-04)

**Goal:** Remove code duplication in `backend/learning/engine.py` around line 250.

**Current State:** MEGA_AUDIT identified "tiny duplication of `return metrics`" near line 250.

**Context:** Low priority code quality cleanup during refactoring.

**Investigation:**
```bash
# Find the duplication
grep -n "return metrics" backend/learning/engine.py
```

**Fix Strategy:**
- Extract common logic into helper function if pattern repeats
- Or simplify control flow to have single return point
- Preserve functionality while reducing duplication

**Effort:** 15 minutes

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

### [Docs] First-Time Setup Guide

**Goal:** Create a comprehensive setup guide in `README.md` for new users.

**Scope:**
- Post-installation steps (after Docker/HA Add-on is running)
- Configure HA connection
- Set up sensors
- Configure battery/solar/water heater parameters
- Verify system is working

**Notes:** Should cover both standalone Docker and HA Add-on paths.

**Source:** Existing backlog item

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

### [Settings] Advanced Config Audit

**Goal:** Identify missing config keys that are not yet exposed in the UI and move advanced keys to the "Advanced" tab.

**Tasks:**
- Audit `config.yaml` for keys missing in `Settings.tsx`
- Identify keys in "System" or "Parameters" tabs that belong in "Advanced"
- Implement changes in `Settings.tsx`

**Source:** Existing backlog item

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

### [UI] Contextual Help System

**Goal:** Add info buttons and hover tooltips throughout the UI.

**Features:**
- Small (i) icons next to complex settings
- Hover for quick explanation
- Click for detailed help modal

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
