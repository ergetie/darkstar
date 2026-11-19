# Design

## Context

See proposal.md for motivation. Every claim below was read in the repo on 2026-11-19; `file:line` references are to the current tree.

Facts the wording depends on:

- Region: onboarding offers only SE1-SE4 (`frontend/src/components/onboarding/steps.tsx:479-482`); `ml/regions.json` has exactly the keys SE1-SE4; the Settings field is free text with helper "e.g. SE4, NO1, DK2" (`frontend/src/pages/settings/types.ts:253-256`); `config.default.yaml:268` lists "SE1-SE4, NO1-NO5, DK1-DK2, FI, etc."; `docs/SETUP_GUIDE.md:77` lists `SE4`, `NO1`, `FI`; README says only "Nordpool" (`README.md:46`). The backlog records the decision (2026-11-19): no NO/FI/DK support for beta exit.
- Telemetry: `installation_stats.enabled: true`, endpoint `https://telemetry.wxl.se/api/ping` (`config.default.yaml:14-16`). The wizard Review step already discloses and has a toggle (`steps.tsx:1104-1117`); Settings -> System has the same section, not advanced-only (`types.ts:586-598`, `systemSections` is `SystemTab`'s source, `SystemTab.tsx:7,56`; `isAdvanced` first appears at `types.ts:621`). Payload fields: `telemetry_receiver/README.md:5` (random UUIDv4 ID, version, channel, installation type, architecture, inverter profile, executor mode; no IP addresses retained; no energy data, location, entity names, secrets or detailed configuration).
- Beta wording: `README.md:9` (badge `label=beta`), `README.md:25-26` (warning box), `docs/SETUP_GUIDE.md:7`. Other "beta" hits are version strings (`darkstar/config.yaml:6`, `darkstar/CHANGELOG.md`, `docs/ARCHITECTURE.md:189`) and belong to the release process, not this change.
- Setup guide: `SETUP_GUIDE.md:5` links `https://github.com/ergetie/darkstar/README.md#installation` (README heading is "## Install", no such file URL without `blob/main`); `:19` links `CREATING_INVERTER_PROFILES.md` but the file is `docs/inverter-profiles/CREATING_INVERTER_PROFILES.md`; units warning at `:53-58` (malformed bold: `(Watts vs kW)"`) and `:106-111`; Logs at `:161` and Shadow Mode at `:170` point to Settings -> Advanced. In the UI, `Advanced` and `Debug` tabs are `advancedOnly` (`frontend/src/pages/settings/index.tsx:45-46,139`) and appear only after the header toggle (`index.tsx:213-228`); logs live in the Debug tab (`index.tsx:159-160`, `Debug.tsx` `LogsView`); the Shadow Mode toggle is on the Executor page (`frontend/src/pages/Executor.tsx:754-762`), not in Settings -> Advanced (`advancedSections` has no shadow_mode field). `USER_MANUAL.md:94` repeats the Advanced claim.
- Wizard: 10 steps, some conditional (`steps.tsx:1227-1384`: Connect, My system, Location & pricing, Inverter, Core sensors, Solar, Battery, Water heater, EV, Review & readiness; `applicableSteps` filters by `appliesWhen`). It opens automatically when the inverter profile is missing and onboarding is not completed or dismissed, or with `?setup_wizard=true` (`frontend/src/App.tsx:61-66`). It can be relaunched from Settings -> Advanced (`AdvancedTab.tsx:92-103`, button "Relaunch Setup Wizard"). Standalone Docker: the Connect step saves URL and token via `PUT /api/ha/config` (`steps.tsx:226-262`, `OnboardingWizard.tsx:319-326`, `backend/api/routers/ha.py:348-361`).
- Add-on: `darkstar/run.sh:35-49` regenerates `/config/darkstar/secrets.yaml` on every start when `SUPERVISOR_TOKEN` is set (and the embedded Python also refreshes the token, `run.sh:198-206`), including resetting `notifications.discord_webhook_url` to `""`; manual edits are lost. Add-on schema declares only `timezone` and `log_level` (`darkstar/config.yaml:45-52`). `run.sh:15` reads `price_area` (and `run.sh:246-247,256-267` read `price_area`, `battery_soc_sensor`, `has_*` options) that the schema never provides, so those branches never run; the price area comes from the wizard. `timezone` is written to `config.yaml` on every start when it differs (`run.sh:250-253`). Both add-ons map host port 5000 (`darkstar/config.yaml:37-38`, same in `darkstar-dev/config.yaml`), use `/config/darkstar` for config and secrets and `/share/darkstar` for data (`run.sh:310-315` in both). The README claims the dev add-on "can run next to the stable version" (`README.md:61`).
- Docker: `docker-compose.yml:5-12` has `build:` only (no `image:`); the entrypoint exits if `/app/config.yaml` or `/app/secrets.yaml` is missing (`scripts/docker-entrypoint.sh:50-67`); README step 1-2 (`README.md:62-66`) never says to clone the repo and uses `docker-compose`, while `docs/OPERATIONS.md:9,47,56-57` and `docs/DEVELOPER.md:66-67,475` use `docker compose`. `darkstar/DOCS.md:28-31` has the only token-creation instructions, add-on only.

## Goals / Non-Goals

**Goals:**
- Every statement in the touched docs matches the code cited above.
- One consistent Sweden-only statement and one consistent telemetry description, reused verbatim across files.

**Non-Goals:**
- No new region support, no price-area dropdown in Settings (the text field stays; only its hint changes).
- No change to the telemetry default, consent model or onboarding text.
- No change to add-on code: dead `price_area` / `has_*` branches in both `run.sh` files stay (code cleanup, not documentation).
- No inverter "tested" markers or removal of the unverified Solis/Huawei/GoodWe cheat-sheet rows (separate backlog item "Inverter Profiles Have No Tested Marker").
- No version renames: `-beta` tags and version strings stay; no `docs/RELEASE_NOTES.md` edit.
- No rewrite of `docs/OPERATIONS.md` / `DEVELOPER.md` (already use `docker compose`).

## Decisions

### D1. Reusable wording blocks

Sweden block (sentence, used in README, SETUP_GUIDE, DOCS.md):
> Darkstar supports Sweden only (Nord Pool price areas SE1, SE2, SE3 and SE4). Other countries and price areas are not supported.

Telemetry block (paragraph, used in README, USER_MANUAL, SETUP_GUIDE with a pointer instead of repeating it in SETUP_GUIDE):
> Darkstar sends one small anonymous heartbeat per day to `telemetry.wxl.se`. It contains a random installation ID, the Darkstar version, release channel, installation type, CPU architecture, inverter profile and executor mode (shadow, live or unknown). Energy data, location, entity names, credentials and detailed configuration are never sent, and the receiver does not keep IP addresses. Reporting is on by default. Turn it off at any time in **Settings -> System -> Installation statistics** (switch **Report installation statistics** off), or set `installation_stats.enabled: false` in `config.yaml`. In the setup wizard it can also be switched off on the last step.

Alternative considered: changing telemetry to opt-in. Rejected: the backlog says the opt-out model stays as is.

### D2. README.md

- Badge (`:9`): change `label=beta` to `label=release`. Alternative (remove the badge) rejected: it still shows the current version.
- Warning box (`:24-26`) becomes:
  `> [!WARNING]` / `> **Use at your own risk.** Darkstar controls high-power electrical equipment. Keep your Home Assistant safety cut-offs configured, check on it regularly and use it at your own risk. Savings depend on your prices, hardware and usage, and Darkstar does not guarantee any financial outcome. Not sure yet? Start in **shadow mode**, where Darkstar plans but doesn't control anything.`
  The original risk sentences survive word for word; only "Public beta." is replaced and the financial sentence is added.
- "Works with": replace "**Electricity prices**: Nordpool." with "**Electricity prices**: Nord Pool, Swedish price areas SE1-SE4 only." and add a bullet "**Region**: " + the Sweden block.
- Dev add-on paragraph (`:56`): replace "and can run next to the stable version" with "Run only one of the two add-ons at a time: both publish host port 5000 and share `/config/darkstar` and `/share/darkstar`." (The unverified runtime question "can they coexist" is answered by what the configs prove: they collide on config, data and port.)
- Docker section replaced by five steps: (1) `git clone https://github.com/ergetie/darkstar.git` and `cd darkstar`; (2) `cp config.default.yaml config.yaml` and `cp secrets.example.yaml secrets.yaml`; (3) create a long-lived access token in Home Assistant (profile -> Security -> Long-lived access tokens -> Create token, copy it when shown) and enter the Home Assistant URL and token in `secrets.yaml`, or leave them and enter both in the wizard's Connect step; (4) `docker compose up -d --build` with a one-line note that the image is built locally from the repository, which takes a few minutes the first time; (5) open `http://localhost:5000`. Keep the Raspberry Pi sentence. Alternative (add `image:` to compose) rejected: it is a code and release-process change.
- New `## Installation statistics` section before "## Learn more" containing the telemetry block and a link to `telemetry_receiver/README.md`.

### D3. docs/SETUP_GUIDE.md

- `:5` link becomes `[README Install section](../README.md#install)`.
- `:7` becomes "This guide walks you through tuning ..." (drop "Welcome to the Darkstar Public Beta!"), followed by a new paragraph on the wizard: first start opens a setup wizard (up to 10 steps, names as listed in Context) that fills in most of this guide and ends with a readiness check; this guide is for reviewing and tuning the result; it can be relaunched from **Settings -> Advanced -> Relaunch Setup Wizard** (Advanced Mode) or by opening the UI with `?setup_wizard=true`. Then a `> [!NOTE]` with the Sweden block.
- `:19` link becomes `inverter-profiles/CREATING_INVERTER_PROFILES.md`.
- Delete the first units warning (`:53-58` plus one blank line); keep the one in section 2.1 (`:106-111`), where sensors are mapped and whose bold markup is correct.
- `:77` becomes "**Nordpool Price Area**: Your Swedish price area, `SE1`, `SE2`, `SE3` or `SE4` (printed on your electricity bill)."; `:78` timezone example becomes only `Europe/Stockholm` (keep "IANA format").
- New subsection "### 1.6 Installation Statistics" after 1.5: two sentences (what it is, where to switch off: Settings -> System) and a link to `../README.md#installation-statistics` instead of repeating the full block.
- `:161` becomes "go to **Settings -> Debug** (first switch on Advanced Mode with the button at the top right of the Settings page)". `:170` becomes "Keep **Shadow Mode** on (toggle on the **Executor** page)". `:171` becomes "Switch **Shadow Mode** off on the **Executor** page and ensure `darkstar_enable` ...", rest of the sentence unchanged.

### D4. docs/USER_MANUAL.md

- `:93-95` Shadow Mode: "On the **Executor** page, use the **Shadow Mode** toggle." (ON/OFF bullets unchanged).
- New `### Installation Statistics` after Shadow Mode, before the `---` that precedes section 4, with the telemetry block.

### D5. darkstar/DOCS.md (add-on)

Rewrite the Configuration and token sections; keep Features and Support.
- Add Sweden block under the intro.
- "First start": install, start, **Open Web UI**; the wizard connects to Home Assistant automatically through the Supervisor, no token needed (`run.sh:35-49`).
- "Settings": everything is configured in the web UI. Add-on **Configuration** tab has two options: `timezone` (default `Europe/Stockholm`; applied to `config.yaml` at every start, so change it here, not in Settings) and `log_level` (`debug|info|warning|error`). Price area is chosen in the wizard.
- "Files": `/config/darkstar/config.yaml` (your settings; edit in the UI; hand edits need an add-on restart); `/config/darkstar/secrets.yaml` is regenerated at every start from the Supervisor token, do not edit it (changes, including a Discord webhook, are lost); data (learning database) in `/share/darkstar`.
- "Dev add-on": do not run both (same port, config and data).
- Remove "Getting a Long-Lived Access Token" (not needed in the add-on; the README Docker section covers it).

### D6. Copy-only code edits

- `frontend/src/pages/settings/types.ts:255` helper: `'Swedish price area: SE1, SE2, SE3 or SE4'`. Field stays `type: 'text'`. No test references the old string (grep for `NO1`/`DK2` in `frontend/src` hits only this line).
- `config.default.yaml:268` comment: `# Nordpool bidding zone (Sweden only: SE1-SE4)`. Comment only; config migration and defaults unaffected.

### D7. Docker command spelling

All docs use `docker compose` (plugin form), matching `docs/OPERATIONS.md` and `docs/DEVELOPER.md`. Only `README.md:66` changes.

## Risks / Trade-offs

- [The HA UI path for tokens (profile -> Security -> Long-lived access tokens) is not in this repo and could not be verified here] -> wording follows the current Home Assistant layout; the old `DOCS.md` text ("scroll to Long-Lived Access Tokens on your profile") is the only in-repo reference. Flagged in the final report.
- [Sweden-only wording while Settings price area stays free text] -> users can still type another zone; the docs state it is unsupported, which is the decision recorded in the backlog. A select field is a separate improvement.
- [Stating the add-ons cannot run together is inferred from configs, not a runtime test] -> the statement says only what the configs prove (same host port, config dir and data dir).
- [Docs mention "Relaunch Setup Wizard" and `?setup_wizard=true`] -> both read from `AdvancedTab.tsx` and `App.tsx`; if those change the guide goes stale, accepted.
