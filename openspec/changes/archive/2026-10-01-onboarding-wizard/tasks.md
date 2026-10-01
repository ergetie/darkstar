## 0. Preconditions

- [x] 0.1 Confirm `onboarding-backend` and `config-save-persistence` are merged
- [x] 0.2 Read `docs/design-system/AI_GUIDELINES.md` and `frontend/src/index.css` tokens

## 1. Foundations

- [x] 1.1 Add API clients/types in `frontend/src/lib/api.ts`: discovery, core-config, ha test with body, profiles list, profile + role suggestions (new shape), readiness, onboarding state
- [x] 1.2 Create `frontend/src/components/onboarding/` with step registry (`steps.ts`: id, title, appliesWhen, component, buildPatch, isComplete)
- [x] 1.3 Implement wizard store seeded from `GET /api/config`, tracking session changes (current → new)
- [x] 1.4 Implement shell: progress (applicable steps only), Back/Next, Skip and X close (confirm → dismissed while preserving saved config and progress), resume at `current_step` on manual Settings relaunch
- [x] 1.5 Implement per-step save via `Api.configSave` with inline 400 errors / warnings and onboarding state `PUT`

## 2. Shared components

- [x] 2.1 `EntityField`: wraps `EntitySelect`; live state + unit, confidence badge, reasons tooltip, plausibility hint
- [x] 2.2 Suggestion chip implementing never-overwrite semantics (current kept, explicit "use suggested")
- [x] 2.3 Adapt `ProfileSetupHelper` to nested `patch`/`candidates`/`current` response (fixes dotted-key bug)

## 3. Steps

- [x] 3.1 Connect (add-on auto-check; standalone typed-credential test, save on success)
- [x] 3.2 My system (has_* toggles, meter type, grid limit with fuse helper)
- [x] 3.3 Location & pricing (HA pre-fill, SE1–SE4 required choice with region descriptions, currency, VAT/energy tax/transfer fee)
- [x] 3.4 Inverter (dynamic dropdown from `/api/profiles`, brand suggestion, required entities)
- [x] 3.5 Core sensors (meter-type and flag dependent; load baseline sensor or synthetic → `synthetic_daily_load_kwh`)
- [x] 3.6 Solar (arrays: name, kWp, tilt, azimuth)
- [x] 3.7 Battery (capacity, min/max SoC, charge/discharge W required, voltage for A-profiles)
- [x] 3.8 Water heater (entry with suggested entities, power_kw, type)
- [x] 3.9 EV (charger, type-dependent fields, suggested entities)
- [x] 3.10 Review & readiness (current → new list, readiness checklist with Fix links, Finish → shadow mode, Go live now with confirm, disabled on fail)

## 4. App integration

- [x] 4.1 Replace `StartupWizard` usage in `App.tsx` with new trigger logic (profile null + status not_started/in_progress); keep missing-profile banner with "Open setup"
- [x] 4.2 Wire the existing Advanced Settings "Relaunch Setup Wizard" card to open the onboarding wizard
- [x] 4.3 Remove `StartupWizard.tsx` and the `Api.executor.run()` call; remove hardcoded profile lists in wizard and `pages/settings/types.ts` (use `/api/profiles`)

## 5. Tests & verification

- [x] 5.1 Frontend tests: conditional steps, resume, skip/X dismissal preserving saved progress, manual relaunch, back edit, never-overwrite, medium confidence not pre-filled, dynamic profile list, battery W gating, shadow finish, go-live disabled on fail, no executor run
- [x] 5.2 Update `startup-wizard`-related backend tests if any reference old behavior
- [x] 5.3 Run `./scripts/lint.sh` and full test suites; all green
- [x] 5.4 Add-on mode covered by automated tests only (mock `SUPERVISOR_TOKEN` / ingress URL): Connect step auto-check, no credential form
