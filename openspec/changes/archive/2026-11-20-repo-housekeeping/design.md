# Design

## Context

See proposal.md for motivation. Relevant current state:

- `profiles/*.yaml` use schema v2; `ProfileMetadata` and `parse_profile` in `executor/profiles.py` read metadata, `validate()` checks it, and `list_profiles()` feeds `GET /api/profiles` in `backend/api/routers/executor.py`. The frontend `InverterProfile` type is in `frontend/src/pages/settings/types.ts`. Profile pickers: onboarding (`components/onboarding/steps.tsx`, which already shows `supported_brands` under the select) and Settings (`pages/settings/SystemTab.tsx` builds select options from `profiles`).
- The design system defines `badge badge-good|warn|bad|muted` (`docs/design-system/AI_GUIDELINES.md`, tokens in `frontend/src/index.css`).
- Backend reads `config.yaml`, `secrets.yaml`, `profiles/` and `data/` relative to the working directory; `DB_PATH` overrides the planner database. `vite build` writes to `backend/static`, which the backend serves with SPA fallback. With no Home Assistant token in `secrets.yaml` the HA socket client starts and fails to connect without crashing the app (to be confirmed by the first E2E run).
- CI has no browser test. Local cache `~/.cache/ms-playwright` holds `chromium_headless_shell-1248`.
- `.agent/` is listed in `.git/info/exclude`, so `.agent/skills/conductor` is untracked and only exists on disk.
- Dockerfile copies selectively, so removing files needs no `.dockerignore` change.

## Goals / Non-Goals

**Goals:**
- Backend is the single source of truth for profile status; the UI never derives it.
- The smoke test is fully automated, hermetic and cheap enough for CI.

**Non-Goals:**
- No per-profile test evidence, version or date; only a two-value flag.
- No full user-flow E2E (onboarding completion, planning, executor control) and no real or mock Home Assistant server.
- No change to profile selection or detection behavior.

## Decisions

1. **Status as a plain metadata string, default `community`.** `ProfileMetadata.status: str = "community"`, parsed with `metadata_data.get("status", "community")`. `validate()` appends an error when the value is not in a module constant `PROFILE_STATUSES = ("tested", "community")`. Absent default means existing third-party profiles stay valid and honestly unverified. Alternative (boolean `tested`) rejected as less extensible and unclear in YAML. `list_profiles()` adds `"status"`; the router passes it through unchanged, so no router code change is needed beyond the existing passthrough (verify in test).
2. **Frontend follows backend.** `status?: 'tested' | 'community'` is optional on the type so older cached responses degrade. A small shared presentational component `ProfileStatusBadge` renders `badge badge-good` ("Tested") or `badge badge-muted` ("Community"), treating undefined as community. It is placed next to the brand line in the onboarding step and beside the select in Settings (`SystemTab`), where native `<option>` elements cannot hold a styled badge; the option label stays plain text. Using existing badge classes means no new tokens.
3. **Shipped profiles all `tested`.** User confirmed all four are hardware-tested. Guide states new contributions begin as `community`; maintainers promote.
4. **Playwright 1.64.0 pinned exactly.** `playwright-core` 1.64.0 uses chromium-headless-shell revision 1248, matching the local cache (1.62.1 needs 1234, 1.63.0 needs 1243, latest 1.65.x needs 1254), so local runs need no download. Pin exact (`"@playwright/test": "1.64.0"`) so the browser revision and the cache stay aligned; CI installs the matching browser with `pnpm exec playwright install --with-deps chromium`. Config must use the headless shell channel (default for headless chromium). Alternative of latest rejected because it forces a ~150 MB local download.
5. **E2E harness.** `frontend/playwright.config.ts` with `testDir: ./e2e`, one chromium project and a `webServer` that runs a Node launcher `frontend/e2e/start-backend.mjs` and waits on `GET /api/health` (confirm the exact health route during implementation). The launcher:
   - creates `frontend/e2e/.runtime/` (gitignored), wiping and recreating it each run;
   - writes `config.yaml` as a copy of the repo `config.default.yaml`, an empty `secrets.yaml` (no HA url or token, so Home Assistant is unavailable), and symlinks `profiles/` to the repo profiles so onboarding and Settings have profiles;
   - spawns `uvicorn backend.main:app --port <e2e port, 5055>` with cwd = runtime dir, `PYTHONPATH` = repo root, `DB_PATH` = runtime `data/planner_learning.db`, using the repo `.venv/bin/python` when present and otherwise `python`/`uv run` with `UV_NO_SYNC=1`;
   - forwards signals and kills the child on exit.
   The frontend is the real production build in `backend/static`; the script `test:e2e` runs `vite build` first (`pnpm build && playwright test`), so no Vite dev server or proxy is involved. Alternative (Vite dev server plus proxy) rejected: tests a different artifact than users get.
6. **Home Assistant stub = unavailable.** Rather than a fake HA server, the runtime has no HA credentials, which is a legitimate state (fresh install). This exercises the real degraded paths and avoids a mock that can drift. If the app proves unable to start without a token, a minimal local HTTP stub returning 401 is the fallback (documented as a task contingency, not an open question).
7. **Smoke assertions.** For `/` and `/settings`: collect `pageerror` and `console` events of type `error` from navigation until network idle and a visible landmark (app nav/heading); assert none, after filtering a short explicit allowlist of expected degraded-state noise that is HA-caused (failed resource loads from API calls that legitimately return 4xx/5xx without HA). The allowlist lives in one place with a comment per entry; the aim is to start with none and add only what the first real run shows. Because a fresh config may open the onboarding wizard, the test dismisses or accepts it deterministically (state asserted either as wizard or dashboard, not assumed).
8. **Kept out of vitest.** `vitest.config.ts` `include` is already `src/**/*.test.{ts,tsx}`; E2E files live in `frontend/e2e/*.spec.ts`, outside it. Add `e2e` and `playwright.config.ts` handling to ESLint/tsconfig only as needed so `pnpm lint` and `pnpm typecheck` stay green. Ignore `frontend/e2e/.runtime/`, `frontend/test-results/`, `frontend/playwright-report/`.
9. **CI job `e2e-smoke`.** Checks out, sets up Python 3.12 + uv, installs `requirements.txt` into `.venv`, sets up pnpm 10 and Node 22, `pnpm install --frozen-lockfile`, `pnpm exec playwright install --with-deps chromium`, runs `pnpm test:e2e`, uploads `playwright-report/` on failure. Matches existing job conventions (action versions, `UV_NO_SYNC`).
10. **Docs.**
   - README table gets a Status column: Deye/SunSynk/Sol-Ark/Turbo Energy Tested, Fronius GEN24 Tested, Sungrow Tested, Generic row kept with "Community-mapped / Generic profile" wording.
   - `SETUP_GUIDE.md`: "verified strings" becomes community-reported strings for the generic profile to be checked against the integration; Solis, Huawei and GoodWe have no profile and are not verified. Cheat sheet check found the Deye and Fronius rows differ only in letter case from the shipped profiles ("Zero Export to CT" vs `Zero Export To CT`, "Discharge to grid" vs `Discharge to Grid`) while the page itself says strings are case-sensitive. Decision: remove those two rows and point Deye/SunSynk and Fronius users to their dedicated profiles, since the generic cheat sheet is for brands without a profile.
   - Repo files are created fresh; `docs/RELEASE_NOTES.md` is not touched.
11. **Removal.** `git rm` for tracked files (paths confirmed by `git ls-files`). `.gitignore` already covers `*.bak` and `data/history.db`; add only `frontend/lint*.txt` (plus the `lint_errors`, `lint_final_push`, `lint_status` variants matched by one glob) and the new Playwright paths. Delete `.agent/skills/conductor` from disk with `rm -r` (untracked, so no git operation).
12. **BACKLOG.** Remove the three entries at their headings (including bodies) up to the next `####`; the updater tests already exist (`tests/updater/*`, `tests/core/test_redaction.py`, `tests/api/test_diagnostics_export.py`) so no extra updater test work is needed.

## Risks / Trade-offs

- **Console error noise without HA** could make the smoke flaky or force a wide allowlist. Mitigation: start strict, allowlist only observed HA-caused entries individually and commented; if the app itself emits errors, fix the app or record it rather than loosening blindly.
- **Pinned Playwright** ties the local cache to 1.64.0; bumps need a new browser download. Accepted, documented in the config comment.
- **CI time and browser download** adds roughly a minute or two; job is independent and parallel.
- **`status: tested` is a claim** with no machinery to enforce it; promotion relies on maintainer judgment and the guide.
- **Symlinked `profiles/`** in the runtime dir assumes POSIX; CI and dev are Linux. Windows contributors are out of scope for this smoke.
- **Docs removal of cheat-sheet rows** loses at-a-glance strings for Deye and Fronius; the dedicated profiles supersede them.
