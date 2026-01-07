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


---

### [PLANNED] REV // PUB01 — Public Beta Release

**Goal:** Transition Darkstar to a production-grade public beta release. This includes scrubbing sensitive data from history, hardening API security, aligning Home Assistant Add-on infrastructure with FastAPI, and creating a professional onboarding experience for external users.

#### Phase 1: Security & Hygiene [PLANNED]
- [ ] **Scrub Git History**: Use `git filter-repo` to remove sensitive strings (`Japandi1`, JWT tokens, OpenRouter keys) from all commits/blobs.
- [ ] **Verify History**: Run `git log --all -S "Japandi1"` and verify no results remain.
- [ ] **API Hardening**: Modify `backend/api/routers/config.py` to ensure `secrets.yaml` keys are NEVER accidentally merged or saved into `config.yaml` during UI settings updates.
- [ ] **Legal**: Create root `LICENSE` file (AGPL-3.0).
- [ ] **Support Templates**: Add `.github/ISSUE_TEMPLATE/` (bug_report.md, feature_request.md) and `.github/PULL_REQUEST_TEMPLATE.md`.

#### Phase 2: Documentation & Onboarding [PLANNED]
- [ ] **README Banner**: Add high-visibility "BETA: Human supervision required" warning at the top of README.
- [ ] **README Removal**: Delete "Design System" sections and internal developer-only mentions.
- [ ] **README Add-on Button**: Add "My Home Assistant" Add-on button for one-click repository installation.
- [ ] **README Badges**: Add dynamic badges for GitHub Actions Build status and License.
- [ ] **Setup Guide**: Create `docs/SETUP_GUIDE.md` walking through HA Entity Mapping, Battery Specs, and Initial Calibration.
- [ ] **Operations Guide**: Create `docs/OPERATIONS.md` documenting Backup/Restore procedures for `planner_learning.db` and how to read critical logs.
- [ ] **Architecture Sync**: Search and replace all legacy "Flask" or "eventlet" references with "FastAPI" and "Uvicorn" in `DEVELOPER.md` and `AGENTS.md`.

#### Phase 3: Infrastructure & Backend Polish [PLANNED]
- [ ] **HA Add-on Runner**: Update `darkstar/run.sh` to use `uvicorn backend.main:app` instead of legacy `flask run`.
- [ ] **Run Script Audit**: Update `darkstar/run.sh` PID management to correctly monitor the FastAPI background task.
- [ ] **Container Health**: Add `HEALTHCHECK` directive to root `Dockerfile` using `curl -f http://localhost:5000/api/health`.
- [ ] **Compose Sync**: Align `docker-compose.yml` healthcheck test command with the new FastAPI health endpoint.
- [ ] **Deprecation Cleanup**: Delete `backend/scheduler.py` (replaced by in-process service in ARC8).
- [ ] **Entrypoint Audit**: Audit `backend/run.py`; remove if redundant with `uvicorn` CLI.
- [ ] **Settings UI Sync**: Verify `grid.import_limit_kw` and `price_smoothing` keys are exposed and editable in the `Settings.tsx` interface.

#### Phase 4: Release Orchestration [PLANNED]
- [ ] **Unified Versioning**: Set version to `3.0.0-beta.1` across `package.json`, `darkstar/config.yaml`, `darkstar/run.sh`, and `entrypoint.sh`.
- [ ] **Coverage Tracking**: Install `pytest-cov` and configure `pyproject.toml` to report backend test coverage.
- [ ] **CI/CD Verification**: Manually trigger `build-addon.yml` and verify `amd64` and `aarch64` images publish successfully to GHCR.
- [ ] **Formal Release**: Create GitHub Release `v3.0.0-beta.1` with a summary of the FastAPI/Kepler leap.

