---
name: darkstar-release
description: Version Release Supervisor for Darkstar. Use when the user wants to release a new version.
---

Release a new version of Darkstar.

**IMPORTANT**: Do NOT modify `docs/RELEASE_NOTES.md` or use this skill unless explicitly instructed by the user to prepare for a release.

---

## Phase 1: Validation

**Do one command at a time. No `&&` chaining.**

1. **Git Hygiene**: Check if `git status` is clean. If not, **STOP** and inform user.
2. **Lint & Test**:
   - `cd frontend && pnpm lint`
   - `uv run ruff check .`
   - `uv run pyright`
   - `uv run python -m pytest -q`
3. **Failure Check**: If any check fails, **STOP** and inform user.

---

## Phase 2: Update Version & Release Notes

1. **Create/Update Release Notes**: Update `docs/RELEASE_NOTES.md` with changes for the new version. Use git commit history and project context. Only include user-relevant information. Let the user review before proceeding to the next step/task.

2. **Update Version in 8 Locations**:
   - `/docs/RELEASE_NOTES.md`
   - `/package.json` (root)
   - `/VERSION` (root)
   - `/config.yaml` (root)
   - `/config.default.yaml` (root)
   - `darkstar/config.yaml` (HA add-on manifest)
   - `darkstar/run.sh` (startup banner)
   - `frontend/package.json`

3. **Verification**: Confirm all files updated with the new version string.

---

## Phase 3: Git Operations

1. **Stage changes**: `git add .`
2. **Commit**: `git commit -m "chore(release): bump to vX.Y.Z"`
3. **Tag**: `git tag vX.Y.Z`
4. **Push**: `git push origin main --tags`

---

## Phase 4: CI/CD Notification

Inform user:
- Tags pushed. GitHub Actions (`build-addon.yml`) will now:
  - Build multi-arch Docker images
  - Automatically create the GitHub Release with notes from `docs/RELEASE_NOTES.md`
- **Warn**: Do NOT manually create a release in the GitHub UI (avoids double builds)

---

## Output On Success

```
## Release vX.Y.Z Complete

**Version bumped in 8 locations**
**Tag created and pushed**
**GitHub Actions building...**

Release notes: docs/RELEASE_NOTES.md
```

---

## Guardrails

- Always validate before making changes
- Stop on any validation failure
- Do not proceed if git is dirty
- Ensure all 8 version locations are updated
- Use semantic versioning (vX.Y.Z)
