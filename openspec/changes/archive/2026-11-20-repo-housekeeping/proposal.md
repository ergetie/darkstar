# Proposal

## Why

The repository is not yet ready for outside contributors or for users judging which inverters are proven. Stray debug dumps and an unused `conductor/` tree are tracked, there are no contributor, conduct or security files, inverter profiles carry no "tested" signal (the README says "Supported" for everything), and there is no browser-level test proving the built UI boots. These are small, related hygiene items and are cleared together.

## What Changes

- Remove stray tracked files with `git rm`: `history_debug_dump.json`, `msg_bad`, `data/history.db` (0 B), `frontend/package.json.bak`, six `frontend/lint*.txt` dumps, and the whole `conductor/` directory (15 files). Delete the untracked, git-excluded local `.agent/skills/conductor` too. Add `.gitignore` entries only where no existing pattern covers them.
- Add `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SECURITY.md`, `.github/ISSUE_TEMPLATE/` (bug report, inverter profile request, `config.yml`) and `.github/pull_request_template.md`. No email addresses; reporting goes through GitHub private reporting and maintainers.
- Add optional profile metadata `status: tested | community` (default `community`). Backend parses, validates and exposes it in `GET /api/profiles`; `profiles/schema.yaml` documents it. All shipped profiles (deye, fronius, sungrow, generic) are marked `tested`. The frontend shows a badge in the onboarding profile picker and the Settings profile picker.
- Update `docs/inverter-profiles/CREATING_INVERTER_PROFILES.md` (new profiles start as `community`), the README "Works with" table (Status = Tested; add Turbo Energy) and `docs/SETUP_GUIDE.md` mode-string cheat sheet wording.
- Add a Playwright browser smoke test (`@playwright/test` 1.64.0 devDependency, `pnpm test:e2e`, separate from vitest) that runs the real backend with Home Assistant unavailable against the built frontend, plus a CI job.
- Delete three `docs/BACKLOG.md` entries this change covers.

## Capabilities

### New Capabilities
- `inverter-profile-status`: the `tested | community` status of an inverter profile, from YAML through validation and API to the picker badges.
- `browser-smoke-test`: an automated Playwright smoke test of the built UI against the real backend with Home Assistant unavailable, run locally and in CI.
- `contributor-guidelines`: the contributor, conduct, security, issue and pull request files that make the repository ready for outside contributors.
- `repo-hygiene`: the repository tracks no stray debug dumps, backup files or unused tooling directories.

### Modified Capabilities

(none)

## Impact

- Backend: `executor/profiles.py`, `backend/api/routers/executor.py` (response gains `status` through `list_profiles()`), `profiles/*.yaml`, `profiles/schema.yaml`.
- Frontend: `frontend/src/pages/settings/types.ts`, `frontend/src/components/onboarding/steps.tsx`, the Settings profile picker (`SystemTab.tsx` and its option rendering), `frontend/package.json` and `pnpm-lock.yaml` (new devDependency `@playwright/test`), new `frontend/playwright.config.ts` and `frontend/e2e/`.
- CI: `.github/workflows/ci.yml` gains an `e2e-smoke` job.
- Docs: `README.md`, `docs/SETUP_GUIDE.md`, `docs/inverter-profiles/CREATING_INVERTER_PROFILES.md`, `docs/BACKLOG.md` (user approved; `docs/RELEASE_NOTES.md` is untouched).
- Deletions: the tracked files listed above. The API change is additive (new `status` field), not breaking.
