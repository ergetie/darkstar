# Tasks

## 1. Repository cleanup

- [x] 1.1 Re-verify paths with `git ls-files`, then `git rm` `history_debug_dump.json`, `msg_bad`, `data/history.db`, `frontend/package.json.bak`, `frontend/lint.txt`, `frontend/lint_errors.txt`, `frontend/lint_final_push.txt`, `frontend/lint_output_fix.txt`, `frontend/lint_output_status.txt`, `frontend/lint_status.txt` and the whole `conductor/` directory (do not commit)
- [x] 1.2 Delete the untracked, git-excluded `.agent/skills/conductor` directory from disk
- [x] 1.3 Confirm nothing references `conductor/` (grep excluding node_modules and .git) and fix any stray reference
- [x] 1.4 Add `.gitignore` entries only where needed: `frontend/lint*.txt`, `frontend/e2e/.runtime/`, `frontend/test-results/`, `frontend/playwright-report/` (verify with `git check-ignore`; `*.bak` and `data/history.db` are already covered)

## 2. Contributor files

- [x] 2.1 Write `CONTRIBUTING.md` (uv/pnpm setup, `UV_NO_SYNC=1`, `./scripts/lint.sh`, conventional commits, tests required, inverter profile contribution linking `docs/inverter-profiles/CREATING_INVERTER_PROFILES.md`)
- [x] 2.2 Write `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1, enforcement via GitHub private reporting and repo maintainers, no email)
- [x] 2.3 Write `SECURITY.md` (GitHub private vulnerability reporting, latest release supported, no email)
- [x] 2.4 Add `.github/ISSUE_TEMPLATE/bug_report.yml` (version, install type HA add-on/Docker, inverter profile, diagnostics bundle), `inverter_profile_request.yml` and `config.yml`
- [x] 2.5 Add `.github/pull_request_template.md`

## 3. Inverter profile status (backend)

- [x] 3.1 Add `status` to `ProfileMetadata` (default `community`), parse it in `parse_profile`, and add `PROFILE_STATUSES` validation in `validate()`
- [x] 3.2 Add `status` to the dicts returned by `list_profiles()` and confirm `GET /api/profiles` passes it through
- [x] 3.3 Set `status: tested` in `profiles/deye.yaml`, `fronius.yaml`, `sungrow.yaml` and `generic.yaml`; document the field in `profiles/schema.yaml`
- [x] 3.4 Add backend tests in the `tests/executor/test_profiles_v2.py` style: default community, declared tested, invalid value rejected, `list_profiles()` includes status, all shipped profiles are tested and pass `scripts/validate_profiles.py`, and the API response contains `status`

## 4. Inverter profile status (frontend)

- [x] 4.1 Add optional `status?: 'tested' | 'community'` to `InverterProfile` in `frontend/src/pages/settings/types.ts`
- [x] 4.2 Create `ProfileStatusBadge` using `badge badge-good` / `badge badge-muted` per `docs/design-system/AI_GUIDELINES.md` (undefined renders as community)
- [x] 4.3 Show the badge in the onboarding picker (`components/onboarding/steps.tsx`) and the Settings picker (`pages/settings/SystemTab.tsx`)
- [x] 4.4 Add vitest tests for the badge (tested, community, undefined) and for presence in the onboarding and Settings pickers, extending `OnboardingWizard.test.tsx` and `SystemTab.test.tsx`
- [x] 4.5 Update `docs/inverter-profiles/CREATING_INVERTER_PROFILES.md`: document `status`, new profiles start as `community`, maintainers promote after hardware verification

## 5. Docs

- [x] 5.1 Update the README "Works with" table: Status column, Tested for Deye/SunSynk/Sol-Ark/Turbo Energy, Fronius GEN24 and Sungrow, keep the Generic row
- [x] 5.2 Edit `docs/SETUP_GUIDE.md` cheat sheet: replace "verified strings" with community-reported wording, state that Solis, Huawei and GoodWe have no profile and are not verified, remove the Deye/SunSynk and Fronius rows (case differs from `deye.yaml` and `fronius.yaml`) and point those users to the dedicated profiles
- [x] 5.3 Delete the three entries from `docs/BACKLOG.md` ("[Testing] Test Gaps (Updater, E2E)", "[Docs] Inverter Profiles Have No Tested Marker", "[Repo] Repo Not Ready For Outside Contributors") and leave all others untouched; do not touch `docs/RELEASE_NOTES.md`

## 6. Browser smoke test

- [x] 6.1 Add `@playwright/test` pinned to exactly `1.64.0` as a frontend devDependency with `pnpm add -D -E`, update `pnpm-lock.yaml`, and confirm chromium-headless-shell revision 1248 in `~/.cache/ms-playwright` is used without a download
- [x] 6.2 Spike: start the backend manually with an empty `secrets.yaml`, copied `config.default.yaml` and a runtime `DB_PATH` under `frontend/e2e/.runtime/`, and confirm it boots and serves the built UI and the health route without Home Assistant (if not, add the minimal local 401 HA stub fallback from design.md)
- [x] 6.3 Write `frontend/e2e/start-backend.mjs` (recreate the runtime dir, config/secrets/profiles symlink, spawn uvicorn on the E2E port with cwd, `PYTHONPATH` and `DB_PATH`, forward signals)
- [x] 6.4 Write `frontend/playwright.config.ts` (testDir `e2e`, chromium project, `webServer` using the launcher and health URL, retries only in CI)
- [x] 6.5 Write `frontend/e2e/smoke.spec.ts`: dashboard and settings load, handle the onboarding wizard state deterministically, assert no `pageerror` or console errors, with a minimal commented allowlist for HA-caused noise
- [x] 6.6 Add `test:e2e` script (`pnpm build && playwright test`), keep vitest `include` unchanged so `pnpm test` skips it, and keep `pnpm lint` and `pnpm typecheck` green with the new files
- [x] 6.7 Add the `e2e-smoke` job to `.github/workflows/ci.yml` (Python 3.12 + uv deps, pnpm 10, Node 22, `pnpm exec playwright install --with-deps chromium`, `pnpm test:e2e`, upload `playwright-report/` on failure)
- [x] 6.8 Run `pnpm test:e2e` locally and confirm it passes; extend `tests/test_ci_workflow_and_compose.py` style checks if CI workflow tests exist for job lists

## 7. Verification

- [x] 7.1 Run `UV_NO_SYNC=1 uv run python -m pytest tests/executor tests/api -q`, then `./scripts/lint.sh`, and fix any failure
- [x] 7.2 Run `pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm build` in `frontend/` and confirm `pnpm test` runs no Playwright test
- [x] 7.3 Run `git status` to confirm only intended changes, that `openspec/changes/learning-data-path-fixes/` and `scratch/` are untouched, and that nothing is staged or committed without the user asking
