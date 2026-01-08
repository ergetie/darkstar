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

### [DONE] REV // PUB01 — Public Beta Release

**Goal:** Transition Darkstar to a production-grade public beta release. This involves scrubbing the specific MariaDB password from history, hardening API security against secret leakage, aligning Home Assistant Add-on infrastructure with FastAPI, and creating comprehensive onboarding documentation.

#### Phase 1: Security & Hygiene [DONE]
**Goal:** Ensure future configuration saves are secure and establish legal footing.
- [x] **API Security Hardening**: Update `backend/api/routers/config.py` (and relevant service layers) to implement a strict exclusion filter. 
  - *Requirement:* When saving the dashboard settings, the system MUST NOT merge any keys from `secrets.yaml` into the writable `config.yaml`.
- [x] **Legal Foundation**: Create root `LICENSE` file containing the AGPL-3.0 license text (syncing with the mentions in README).


#### Phase 2: Professional Documentation [DONE]
**Goal:** Provide a "wow" first impression and clear technical guidance for new users.
- [x] **README Enhancement**: 
  - Add high-visibility "PUBLIC BETA" banner.
  - Add GitHub Action status badges and AGPL-3.0 License badge.
  - Add "My Home Assistant" Add-on button.
  - Remove "Design System" internal section.
- [x] **QuickStart Refresh**: Update `README.md` to focus on the UI-centric Settings workflow.
- [x] **Setup Guide [NEW]**: Created `docs/SETUP_GUIDE.md` focusing on UI mapping and Add-on auto-discovery.
- [x] **Operations Guide [NEW]**: Created `docs/OPERATIONS.md` covering Dashboard controls, backups, and logs.
- [x] **Architecture Doc Sync**: Global find-and-replace for "Flask" -> "FastAPI" and "eventlet" -> "Uvicorn" in all `.md` files.

#### Phase 3: Infrastructure & Service Alignment [DONE]
**Goal:** Finalize the migration from legacy Flask architecture to the new async FastAPI core.
- [x] **Add-on Runner Migration**: Refactor `darkstar/run.sh`.
  - *Task:* Change the legacy `flask run` command to `uvicorn backend.main:app`.
  - *Task:* Ensure environment variables passed from the HA Supervisor are correctly used.
- [x] **Container Health Monitoring**: 
  - Add `HEALTHCHECK` directive to root `Dockerfile`. (Already in place)
  - Sync `docker-compose.yml` healthcheck.
- [x] **Legacy Code Removal**:
  - Delete `backend/scheduler.py` (Superseded by internal SchedulerService).
  - Audit and potentially remove `backend/run.py`.

#### Phase 3a: MariaDB Sunset [DONE]
**Goal:** Remove legacy MariaDB support and cleanup outdated project references.
- [x] Delete `backend/learning/mariadb_sync.py` and sync scripts in `bin/` and `debug/`.
- [x] Strip MariaDB logic from `db_writer.py` and `health.py`.
- [x] Remove "DB Sync" elements from Dashboard.
- [x] Simplify `api.ts` types.

#### Phase 3b: Backend Hygiene [DONE]
**Goal:** Audit and remove redundant backend components.
- [x] Audit and remove redundant `backend/run.py`.
- [x] Deduplicate logic in `learning/engine.py`.

#### Phase 3c: Documentation & Config Refinement [DONE]
**Goal:** Update documentation and finalize configuration.
- [x] Global scrub of Flask/Gunicorn references.
- [x] Standardize versioning guide and API documentation links.
- [x] Final configuration audit.
- [x] Refresh `AGENTS.md` and `DEVELOPER.md` to remove legacy Flask/eventlet/scheduler/MariaDB mentions.

#### Phase 4: Versioning & CI/CD Validation [DONE]
**Goal:** Orchestrate the final build and release.
- [x] **Atomic Version Bump**: Set version `2.4.0-beta` in:
  - `frontend/package.json`
  - `darkstar/config.yaml`
  - `scripts/docker-entrypoint.sh`
  - `darkstar/run.sh`
- [x] **CI Fix**: Resolve `pytz` dependency issue in GitHub Actions pipeline.
- [x] **Multi-Arch Build Verification**: 
  - Manually trigger `.github/workflows/build-addon.yml`.
  - Verify successful container image push to GHCR.
- [x] **GitHub Release Creation**: 
  - Generate a formal GitHub Release `v2.4.0-beta`.
- [x] **HA Ingress Fix (v2.4.1-beta)**: 
  - Fixed SPA base path issue where API calls went to wrong URL under HA Ingress.
  - Added dynamic `<base href>` injection in `backend/main.py` using `X-Ingress-Path` header.
  - Updated `frontend/src/lib/socket.ts` to use `document.baseURI` for WebSocket path.
  - Released and verified `v2.4.1-beta` — dashboard loads correctly via HA Ingress.

---

### [IN PROGRESS] REV // LCL01 — Legacy Heuristic Cleanup & Config Validation

**Goal:** Remove all legacy heuristic planner code (pre-Kepler). Kepler MILP becomes the sole scheduling engine. Add comprehensive config validation to catch misconfigurations at startup with clear user-facing errors (banners + toasts).

> **Breaking Change:** Users with misconfigured `water_heating.power_kw = 0` while `has_water_heater = true` will receive a warning, prompting them to fix their config.

#### Phase 1: Backend Config Validation [DONE ✓]
**Goal:** Add validation rules for `has_*` toggle consistency. Warn (not error) when configuration is inconsistent but non-system-breaking.

**Files Modified:**
- `planner/pipeline.py` - Expanded `_validate_config()` to check `has_*` toggles
- `backend/health.py` - Added validation to `_validate_config_structure()` for `/api/health`
- `backend/api/routers/config.py` - Added validation on `/api/config/save`
- `tests/test_config_validation.py` - 7 unit tests

**Validation Rules:**
| Toggle | Required Config | Severity | Rationale |
|--------|-----------------|----------|-----------|
| `has_water_heater: true` | `water_heating.power_kw > 0` | **WARNING** | Water scheduling silently disabled |
| `has_battery: true` | `battery.capacity_kwh > 0` | **ERROR** | Breaks MILP solver |
| `has_solar: true` | `system.solar_array.kwp > 0` | **WARNING** | PV forecasts will be zero |

**Implementation:**
- [x] In `planner/pipeline.py` `_validate_config()`:
  - [x] Check `has_water_heater` → `water_heating.power_kw > 0` (WARNING via logger)
  - [x] Check `has_battery` → `battery.capacity_kwh > 0` (ERROR raise ValueError)
  - [x] Check `has_solar` → `system.solar_array.kwp > 0` (WARNING via logger)
- [x] In `backend/health.py` `_validate_config_structure()`:
  - [x] Add same checks as HealthIssues with appropriate severity
- [x] In `backend/api/routers/config.py` `save_config()`:
  - [x] Validate config before saving, reject errors with 400, return warnings
- [x] Create `tests/test_config_validation.py`:
  - [x] Test water heater misconfiguration returns warning
  - [x] Test battery misconfiguration raises error
  - [x] Test solar misconfiguration returns warning
  - [x] Test valid config passes

#### Phase 2: Frontend Health Integration [DONE ✓]
**Goal:** Display health issues from `/api/health` in the Dashboard using `SystemAlert.tsx` banner. Add persistent toast for critical errors.

**Files Modified:**
- `frontend/src/pages/Dashboard.tsx` - Fetch health on mount, render SystemAlert
- `frontend/src/lib/api.ts` - Custom configSave with 400 error parsing
- `frontend/src/pages/settings/hooks/useSettingsForm.ts` - Warning toasts on config save

**Implementation:**
- [x] In `Dashboard.tsx`:
  - [x] Add `useState` for `healthStatus`
  - [x] Fetch `/api/health` on component mount via `useEffect`
  - [x] Render `<SystemAlert health={healthStatus} />` at top of Dashboard content
- [x] In `api.ts`:
  - [x] Custom `configSave` that parses 400 error response body for actual error message
- [x] In `useSettingsForm.ts`:
  - [x] Show warning toasts when config save returns warnings
  - [x] Show error toast with actual validation error message on 400

#### Phase 3: Legacy Code Removal [PLANNED]
**Goal:** Remove all legacy heuristic scheduling code. Kepler MILP is the sole planner.

**Files to DELETE:**
- [ ] `planner/scheduling/water_heating.py` (534 LOC) - Heuristic water scheduler
- [ ] `planner/scheduling/__init__.py` - Empty module init
- [ ] `planner/strategy/windows.py` (122 LOC) - Cheap window identifier
- [ ] `backend/kepler/adapter.py` - Compatibility shim
- [ ] `backend/kepler/solver.py` - Compatibility shim
- [ ] `backend/kepler/types.py` - Compatibility shim
- [ ] `backend/kepler/__init__.py` - Shim init

**Files to MODIFY:**
- [ ] `planner/pipeline.py`:
  - [ ] Remove import: `from planner.scheduling.water_heating import schedule_water_heating`
  - [ ] Remove import: `from planner.strategy.windows import identify_windows`
  - [ ] Remove fallback block at lines 246-261 (window identification + heuristic call)
- [ ] `tests/test_kepler_solver.py`:
  - [ ] Change: `from backend.kepler.solver import KeplerSolver`
  - [ ] To: `from planner.solver.kepler import KeplerSolver`
  - [ ] Change: `from backend.kepler.types import ...`
  - [ ] To: `from planner.solver.types import ...`
- [ ] `tests/test_kepler_k5.py`:
  - [ ] Same import updates as above

#### Phase 4: Verification [PLANNED]
**Goal:** Verify all changes work correctly and no regressions.

**Automated Tests:**
- [ ] Run backend tests: `PYTHONPATH=. python -m pytest tests/ -q`
- [ ] Run frontend lint: `cd frontend && pnpm lint`

**Manual Verification:**
- [ ] Test with valid production config → Planner runs successfully
- [ ] Test with `water_heating.power_kw: 0` → Warning in logs + banner in UI
- [ ] Test with `battery.capacity_kwh: 0` → Error at startup
- [ ] Test Dashboard shows SystemAlert banner for warnings
- [ ] Verify all legacy files are deleted (no orphan imports)

**Documentation:**
- [ ] Update this REV status to `[DONE]`
- [ ] Commit with: `feat(planner): remove legacy heuristics, add config validation`
