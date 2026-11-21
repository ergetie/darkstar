---
name: darkstar-release
description: Version Release Supervisor for Darkstar. Use when the user wants to release a new version.
---

Release a new version of Darkstar.

**IMPORTANT**: Do NOT modify `docs/RELEASE_NOTES.md` or use this skill unless explicitly instructed by the user to prepare for a release.

Versioning: semantic `vX.Y.Z-beta` while in beta (minor for features, patch for fixes only).

---

## Phase 1: Validation

**Do one command at a time. No `&&` chaining.**

1. **Sync with origin**: `git fetch origin`, then `git status -sb`. CI commits dev `VERSION` bumps to `origin/main`, so local main is often behind. If behind, `git pull --ff-only`. If diverged, **STOP** and inform user.
2. **Git hygiene**: `git status --porcelain --untracked-files=no` must be empty. Untracked files (e.g. `scratch/`, other sessions' OpenSpec changes) are fine; they are never staged. If tracked files are modified, **STOP** and inform user.
3. **Lint & test**: `./scripts/lint.sh` (sets `UV_NO_SYNC=1` and `TZ`; runs ruff, pyright, pytest, frontend format/lint/tests). Run it in the background or with a long timeout. Any ad-hoc `uv run` must be prefixed with `UV_NO_SYNC=1`.
4. **Failure check**: If any check fails, or lint.sh modified tracked files (auto-fix/format), **STOP** and inform user.

---

## Phase 2: Release Notes & Version

1. **Release notes**: Add a section at the top of `docs/RELEASE_NOTES.md` from `git log <last-tag>..HEAD` and project context. User-relevant changes only, same style as previous entries.
   - Heading MUST be `## [vX.Y.Z-beta] - <Title> - YYYY-MM-DD` and the section MUST end with `---`. CI (`build-addon.yml`) extracts the GitHub Release body by this exact pattern.
   - **STOP and let the user review the notes before continuing.**
2. **Bump version in exactly these 4 files** (without the `v` prefix in the files):
   - `docs/RELEASE_NOTES.md` (heading above)
   - `package.json` (root)
   - `frontend/package.json`
   - `darkstar/config.yaml` (HA add-on manifest, `version:`)
3. **Do NOT touch**: `VERSION` (CI stamps it for dev and tag builds), `config.yaml` (local, never committed), `darkstar-dev/config.yaml` (CI-managed).
4. **Verify**: `git grep -n "<old-version>" -- package.json frontend/package.json darkstar/config.yaml` returns nothing, and `git diff --stat` shows only the 4 files.

---

## Phase 3: Git Operations

1. **Stage only the 4 files**: `git add docs/RELEASE_NOTES.md package.json frontend/package.json darkstar/config.yaml`. Never `git add .`.
2. **Ask the user before committing.** Then: `git commit -m "chore(release): bump to vX.Y.Z-beta"` (no attribution trailers).
3. **Tag**: `git tag -a vX.Y.Z-beta -m "vX.Y.Z-beta"`
4. **Ask the user before pushing.** Then push commit and tag: `git push origin main` and `git push origin vX.Y.Z-beta`. The pre-push hook runs the full test suite (~4 min) and needs the project venv on PATH; use a long timeout or run in background.

---

## Phase 4: CI/CD Notification

Inform user:
- Tag pushed. GitHub Actions (`build-addon.yml`) will:
  - Build multi-arch Docker images
  - Create the GitHub Release with notes from `docs/RELEASE_NOTES.md`
- **Warn**: Do NOT manually create a release in the GitHub UI (avoids double builds).
- Stable-channel users (add-on and in-app Docker updater) will now be offered this version.

---

## Output On Success

```
## Release vX.Y.Z-beta Complete

**Version bumped in 4 files**
**Tag created and pushed**
**GitHub Actions building...**

Release notes: docs/RELEASE_NOTES.md
```

---

## Guardrails

- Validate before changing anything; stop on any failure
- Never stage untracked files or `config.yaml`
- Ask before commit and before push, every time
- Release notes heading must match the CI extraction pattern
