---
description: Version Release Supervisor
---

## Phase 1: Validation

IMPORTANT: DO ONE COMMAND AT THE TIME! NO "&&" ALLOWED!

1. **Git Hygiene**: Check if `git status` is clean. If not, **STOP**.
2. **Lint & Test**: Run the standard Lint & Test suite.
3. **Failure Check**: If tests fail, **STOP**.

## Phase 2: Update Version & Release Notes

1. **Mandatory: Create/Update Release Notes**: Update [docs/RELEASE_NOTES.md](file:///home/s/sync/documents/projects/darkstar/docs/RELEASE_NOTES.md) with changes for the new version (Update with latest changes from git commit history, only project related info that the USER might need!).
2. **Update Version & Notes** (5 locations):
   - `/VERSION` (root) — single source of truth, read at runtime by entrypoints and backend API
   - `/docs/RELEASE_NOTES.md`
   - `/package.json` (root)
   - `/frontend/package.json`
   - `darkstar/config.yaml` (HA add-on manifest — required by HA add-on store)
3. **Verification**: Run `grep -r "[new_version]" .` to confirm all files updated.

4. **STOP**: Let the user review before proceeding.

## Phase 3: Git Operations

1. **Stage changes**: `git add .` (Ensure `docs/RELEASE_NOTES.md` and all versioned files are staged)
2. **Commit**: `git commit -m "chore(release): bump to v[new_version]"`
3. **Tag**: `git tag v[new_version]`
4. **Push**: `git push origin main --tags`

## Phase 4: CI/CD Trigger

1. **Notify user**: "Tags pushed. GitHub Actions (`build-addon.yml`) will now:"
   - Build the Multi-arch Docker images.
   - **Automatically create the GitHub Release** with notes from `docs/RELEASE_NOTES.md`.
