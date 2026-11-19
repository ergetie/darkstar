# Tasks

All edits follow design.md (wording blocks D1, per-file decisions D2-D7). Do not edit `docs/RELEASE_NOTES.md`. Do not stage or commit.

## 1. Copy-only code edits (Sweden-only hint)

- [x] 1.1 In `frontend/src/pages/settings/types.ts:255` change the helper `'e.g. SE4, NO1, DK2'` to `'Swedish price area: SE1, SE2, SE3 or SE4'`; verify `grep -rn "NO1\|DK2" frontend/src` returns nothing and `pnpm --dir frontend exec tsc --noEmit` passes
- [x] 1.2 In `config.default.yaml:268` change the comment to `# Nordpool bidding zone (Sweden only: SE1-SE4)`; verify `UV_NO_SYNC=1 uv run python -c "import yaml; yaml.safe_load(open('config.default.yaml'))"` exits 0 and `grep -n "NO1\|DK1\|FI," config.default.yaml` returns nothing

## 2. README.md

- [x] 2.1 Change the badge `label=beta` to `label=release` (`README.md:9`); verify `grep -n "label=" README.md` shows `label=release`
- [x] 2.2 Replace the warning box (`README.md:24-26`) with the D2 text: "Use at your own risk." heading, the original three risk sentences and shadow-mode sentence unchanged, plus the sentence that savings depend on prices, hardware and usage and no financial outcome is guaranteed; verify `grep -n -i "beta" README.md` returns nothing and the warning still contains "safety cut-offs" and "at your own risk"
- [x] 2.3 In "Works with" change the electricity-prices bullet to "Nord Pool, Swedish price areas SE1-SE4 only." and add a "Region" bullet using the D1 Sweden block; verify `grep -n "Sweden only" README.md` matches
- [x] 2.4 Replace the dev add-on sentence "and can run next to the stable version" (`README.md:61`) with the D2 sentence (run only one at a time; same host port 5000, `/config/darkstar` and `/share/darkstar`); verify `grep -n "next to the stable" README.md` returns nothing
- [x] 2.5 Rewrite the Docker section (`README.md:62-68`) as the five D2 steps (clone and `cd`, copy the two files, create the HA long-lived token and fill `secrets.yaml` or use the wizard Connect step, `docker compose up -d --build`, open `http://localhost:5000`), keeping the Raspberry Pi sentence; verify `grep -n "docker-compose" README.md` returns nothing and `grep -n "git clone" README.md` matches
- [x] 2.6 Add a `## Installation statistics` section before `## Learn more` with the D1 telemetry block and a link to `telemetry_receiver/README.md`; verify `grep -n "Installation statistics" README.md` matches and the link target file exists

## 3. docs/SETUP_GUIDE.md

- [x] 3.1 Fix the intro: change the link at line 5 to `[README Install section](../README.md#install)`; replace "Welcome to the Darkstar Public Beta! This guide will walk you through" at line 7 with "This guide walks you through"; verify `grep -n -i "beta\|README.md#installation" docs/SETUP_GUIDE.md` returns nothing
- [x] 3.2 Insert after line 7 the D3 wizard paragraph (up to 10 steps with the exact step names, readiness check at the end, relaunch via Settings -> Advanced -> Relaunch Setup Wizard or `?setup_wizard=true`) and a `> [!NOTE]` with the D1 Sweden block; verify `grep -n "Relaunch Setup Wizard\|Sweden only" docs/SETUP_GUIDE.md` matches both
- [x] 3.3 Change the profile-guide link (line 19) to `inverter-profiles/CREATING_INVERTER_PROFILES.md`; verify `test -f docs/inverter-profiles/CREATING_INVERTER_PROFILES.md` succeeds and `grep -n "(CREATING_INVERTER" docs/SETUP_GUIDE.md` returns nothing
- [x] 3.4 Delete the duplicated malformed units warning in section 1.1 (lines 53-58 and one adjoining blank line), keeping the one in section 2.1; verify `grep -c "Check Your Units" docs/SETUP_GUIDE.md` prints 1
- [x] 3.5 In section 1.4 replace the price-area bullet with "Your Swedish price area, `SE1`, `SE2`, `SE3` or `SE4` (printed on your electricity bill)" and make the timezone example only `Europe/Stockholm`; verify `grep -n "NO1\|FI\b\|America/New_York" docs/SETUP_GUIDE.md` returns nothing
- [x] 3.6 Add "### 1.6 Installation Statistics" after section 1.5: two sentences (daily anonymous heartbeat, on by default, switch off in Settings -> System) and a link to `../README.md#installation-statistics`; verify `grep -n "installation-statistics" docs/SETUP_GUIDE.md` matches
- [x] 3.7 Fix the Logs step (line 161) to "**Settings -> Debug** (first switch on Advanced Mode with the button at the top right of the Settings page)" and the Shadow Mode lines (170-171) to refer to the **Shadow Mode** toggle on the **Executor** page, leaving the `darkstar_enable` clause unchanged; verify `grep -n "Settings -> Advanced" docs/SETUP_GUIDE.md` shows only the "Relaunch Setup Wizard" line

## 4. docs/USER_MANUAL.md

- [x] 4.1 Change the Shadow Mode location (`docs/USER_MANUAL.md:94`) to "On the **Executor** page, use the **Shadow Mode** toggle."; verify `grep -n "Settings -> Advanced" docs/USER_MANUAL.md` returns nothing
- [x] 4.2 Add `### Installation Statistics` after the Shadow Mode subsection (before the following `---`) with the D1 telemetry block; verify `grep -n "Installation Statistics" docs/USER_MANUAL.md` matches and the next `---` and `## 🔋 4.` heading are intact

## 5. darkstar/DOCS.md (add-on)

- [x] 5.1 Rewrite `darkstar/DOCS.md` per D5: keep Features and Support; add the D1 Sweden block; replace "Configuration" and "Getting a Long-Lived Access Token" with First start (wizard, automatic Supervisor connection), Settings (UI; the two add-on options `timezone` and `log_level`; price area in the wizard), Files (`/config/darkstar/config.yaml`, `secrets.yaml` regenerated every start and not to be edited, data in `/share/darkstar`) and Dev add-on (do not run both); verify `grep -n "long-lived\|Long-Lived\|your-long-lived" darkstar/DOCS.md` returns nothing and `grep -n "regenerated" darkstar/DOCS.md` matches

## 6. Final checks

- [x] 6.1 Verify all relative links in `README.md`, `docs/SETUP_GUIDE.md` and `docs/USER_MANUAL.md` resolve: run `grep -on "](\(\.\./\)\?[A-Za-z0-9_./-]*\(#[a-z-]*\)\?)" <file>` per file and confirm every path exists with `test -f`, and that `#install` and `#installation-statistics` match headings in `README.md`
- [x] 6.2 Verify scope: `git diff --stat` lists only `README.md`, `docs/SETUP_GUIDE.md`, `docs/USER_MANUAL.md`, `darkstar/DOCS.md`, `config.default.yaml`, `frontend/src/pages/settings/types.ts` and `docs/BACKLOG.md`; `docs/RELEASE_NOTES.md` is unchanged and nothing is staged
- [x] 6.3 Run `pnpm --dir frontend exec vitest run src/pages/settings` and verify it passes
