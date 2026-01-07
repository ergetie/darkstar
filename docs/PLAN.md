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

### [PLANNED] REV // PUB01 — Public Beta Release

**Goal:** Transition Darkstar to a production-grade public beta release. This involves scrubbing the specific MariaDB password from history, hardening API security against secret leakage, aligning Home Assistant Add-on infrastructure with FastAPI, and creating comprehensive onboarding documentation.

#### Phase 1: Security & Hygiene [DONE]
**Goal:** Ensure future configuration saves are secure and establish legal footing.
- [x] **API Security Hardening**: Update `backend/api/routers/config.py` (and relevant service layers) to implement a strict exclusion filter. 
  - *Requirement:* When saving the dashboard settings, the system MUST NOT merge any keys from `secrets.yaml` into the writable `config.yaml`.
- [x] **Legal Foundation**: Create root `LICENSE` file containing the AGPL-3.0 license text (syncing with the mentions in README).

#### Phase 2: Professional Documentation [PLANNED]
**Goal:** Provide a "wow" first impression and clear technical guidance for new users.
- [ ] **README Visual Overhaul**: 
  - Add high-visibility "BETA" banner at the top.
  - Add GitHub Action status badges and License badge.
  - Implement a "My Home Assistant" Add-on button linking to `https://my.home-assistant.io/redirect/supervisor_add_repo/?repository_url=...`.
  - Remove "Design System" technical section (lines 141-150).
- [ ] **Create Setup Guide (`docs/SETUP_GUIDE.md`)**:
  - Detailed flow for Home Assistant Long-Lived Access Token creation.
  - Spreadsheet-style mapping of required sensors (Battery SoC, Grid Power, etc.).
  - Calibration guide for battery efficiency and charge/discharge limits.
- [ ] **Create Operations Guide (`docs/OPERATIONS.md`)**:
  - Guide on backing up `data/planner_learning.db` (The ML brain).
  - Instructions for identifying issues in `darkstar.log`.
  - How to perform a manual "Emergency Stop" vs "Pause".
- [ ] **Architecture Doc Sync**: Global find-and-replace for "Flask" -> "FastAPI" and "eventlet" -> "Uvicorn" in all `.md` files to prevent confusing external developers.

#### Phase 3: Infrastructure & Service Alignment [PLANNED]
**Goal:** Finalize the migration from legacy Flask architecture to the new async FastAPI core in the production environment.
- [ ] **Add-on Runner Migration**: Refactor `darkstar/run.sh`.
  - *Task:* Change the legacy `exec python3 -m flask run` command to `exec uvicorn backend.main:app --host 0.0.0.0 --port 5000`.
  - *Task:* Ensure environment variables passed from the HA Supervisor are correctly picked up by Uvicorn.
- [ ] **Container Health Monitoring**: 
  - Add `HEALTHCHECK` directive to root `Dockerfile`.
  - *Command:* `curl -f http://localhost:5000/api/health || exit 1`.
  - Sync `docker-compose.yml` healthcheck test to match.
- [ ] **Legacy Code Removal**:
  - Delete `backend/scheduler.py` (Legacy standalone script, superseded by `SchedulerService`).
  - Audit `backend/run.py` (Local entry point); replace usage with standard `uvicorn` commands in dev scripts.
- [ ] **Settings UI Verification**: 
  - Verify `price_smoothing_factor` and `grid_peak_penalty` are correctly rendered in the Settings Tab UI.

#### Phase 4: Versioning & CI/CD Validation [PLANNED]
**Goal:** Orchestrate the final build and release.
- [ ] **Atomic Version Bump**: Set version `3.0.0-beta.1` in:
  - `frontend/package.json`
  - `darkstar/config.yaml` (Add-on manifest)
  - `scripts/docker-entrypoint.sh` (Banner text)
  - `darkstar/run.sh` (Banner text)
- [ ] **Multi-Arch Build Verification**: 
  - Manually trigger `.github/workflows/build-addon.yml`.
  - Verify successful container image push to GHCR for both `linux/amd64` and `linux/arm64`.
- [ ] **GitHub Release Creation**: 
  - Generate a formal GitHub Release `v3.0.0-beta.1`.
  - Write release notes focusing on the "Kepler" MILP engine and "FastAPI" performance gains.

