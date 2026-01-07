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

