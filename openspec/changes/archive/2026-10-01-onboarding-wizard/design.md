## Context

`StartupWizard.tsx` (503 lines) is a single component with `step` 0–3 in `useState`. Nothing is persisted, and it saves once at the end with `Api.configSave`, then `Api.executor.run()`. `App.tsx` forces the wizard when `system.inverter_profile === null`. Reusable pieces are `EntitySelect` (searchable combobox), `Card`, `ProfileSetupHelper` and the `Api` client. The backend foundation (discovery, matching, readiness, onboarding state) comes from `onboarding-backend`. Config save is a partial deep merge with backups.

## Goals / Non-Goals

**Goals:**
- After onboarding, a working configuration for the add-on and standalone Docker.
- Minimal typing: auto-detect, then confirm.
- Re-runnable without silent overwrites, resumable, skippable, with back navigation.

**Non-Goals:**
- Exposing every advanced parameter (those stay in Settings).
- Non-Swedish pricing.
- PV tilt/azimuth detection (asked, with defaults).
- Mobile-specific redesign beyond the design system's responsive rules.

## Decisions

1. **Step registry.** `onboarding/steps.ts` declares each step as `{id, title, appliesWhen(systemDef), component, buildPatch(state), isComplete(state)}`. Skipped steps (for example EV when `has_ev_charger` is false) are filtered from navigation and progress. The alternative was a hardcoded switch like today, rejected because it doesn't scale to conditional steps.
2. **State model.** Each step's draft lives in a wizard store seeded from `GET /api/config`, which pre-fills current values on re-run. Step ids and completion are mirrored to `PUT /api/setup/onboarding`. On open, the wizard resumes at `current_step`.
3. **Per-step save.** "Next" saves that step's `buildPatch()` via `Api.configSave` (deep merge). Validation errors (HTTP 400) block progress and show inline. Warnings are shown but don't block. This replaces the single final save, so a closed wizard loses nothing.
4. **Explicit overwrite UX.** For every field where `current` is non-empty and a suggestion differs, the field shows the current value selected, plus a "Suggested: X (why)" chip that applies the suggestion on click. Suggestions never auto-apply over existing values. Empty fields are pre-filled only by high-confidence suggestions, visibly marked "auto-detected". The Review step lists all values changed in this session (current → new) for a final look. Saving happened per step, but the review links back to each step for correction.
5. **Entity field component.** `EntityField` wraps `EntitySelect` and adds a live state with unit, a confidence badge, a reasons tooltip, and a role-specific plausibility hint (for example "SoC should be 0–100 %"). It uses the discovery data and is shared with Settings later (out of scope here).
6. **Trigger and skip semantics.**
   - The wizard auto-opens when the onboarding status is `not_started` or `in_progress` *and* `inverter_profile` is null. This keeps existing installs that are configured without state from being nagged.
   - "Skip setup" and the X close action both ask for confirmation, set the status to `dismissed`, and close the wizard without clearing the saved config, `current_step`, or `completed_steps`. The dashboard is then accessible, and the wizard does not auto-open on the next load.
   - Settings gets a "Run setup again" button, which opens the wizard with the current config pre-filled and resumes at the saved `current_step`. Opening it this way changes the status back to `in_progress`.
   - This replaces the current requirement that forces the wizard and blocks the dashboard.
7. **Finish.**
   - On "Finish", the wizard saves `executor.shadow_mode: true` (unless it is already explicitly false on a re-run, in which case that value is shown and kept). It marks the status `completed` and shows a summary: "Darkstar is planning in shadow mode. It won't control your hardware until you turn shadow mode off in Settings → Executor."
   - "Go live now" sets `shadow_mode: false` through the config save after a confirm dialog. It is disabled while readiness has `fail` checks.
   - The wizard never calls `Api.executor.run()`.
8. **Steps content (minimum to work):**
   - **Connect.** Add-on: an automatic check is shown. Standalone: URL and token, tested with typed credentials, saved only on success.
   - **My system.**
     - Toggles for solar, battery, water heater and EV.
     - Grid meter type (net/dual).
     - `system.grid.max_power_kw`, with a helper that converts fuse amps × phases to kW.
   - **Location & pricing.**
     - Lat/long and timezone, pre-filled from HA.
     - Nordpool area: a required SE1–SE4 choice with region descriptions and a "check your electricity bill" hint. It keeps the existing value on re-run and has no preselection on fresh installs. Currency is also set here.
     - VAT, energy tax and transfer fee (flat), with Swedish defaults and labels. Time-of-use rules stay in Settings.
   - **Inverter.** Brand dropdown with a suggested brand, then the required profile entities as `EntityField`s.
   - **Core sensors.**
     - `load_power`, plus `grid_power` or import/export depending on the meter type.
     - `battery_soc`/`battery_power` if battery; `pv_power` if solar.
     - The cumulative `total_*` sensors if learning is on.
     - Load baseline: a sensor, or a synthetic estimate saved to `synthetic_daily_load_kwh`.
   - **Solar.** Arrays with name, kWp, tilt and azimuth (compass picker). The default is one array.
   - **Battery.**
     - Capacity, min/max SoC, and max charge/discharge W. Defaults come from the profile or entity attributes where available, and the W limits are required.
     - Nominal voltage, pre-filled for A-controlled profiles.
   - **Water heater.**
     - Name, control entity (auto-suggested) and power sensor.
     - power_kw, with a suggestion from the sensor peak if available.
     - Type (binary/modulating).
   - **EV.**
     - Charger name and type (binary/current), switch/current entities, car SoC and plug sensors.
     - Battery capacity, rated power or min/max current, and phases.
     - Phase switching stays in Settings.
   - **Review & readiness.** Show a checking state while the single batch request runs, then status totals and the readiness checklist with "Fix" links that jump to the owning step. Show remediation only for warnings and failures, with units that match each sensor role, then Finish / Go live now.
9. **No `localStorage`** for progress. The server-side state is used, because add-on ingress users may switch devices.

## Risks / Trade-offs

- [Per-step save writes partial configs that are briefly inconsistent (e.g. `has_battery` on before the battery step)] → Planner/readiness tolerate this already (warnings). The wizard is the active foreground flow, and readiness at the end is the gate.
- [A large step count feels long] → Steps not applicable to the system are hidden. Auto-filled steps need only "Next". The progress bar shows the remaining applicable steps.
- [A user dismisses onboarding and never configures] → The existing missing-profile banner and the config-incomplete banner remain, and both offer "Open setup".
- [The design-system drift] → Only tokens and components from the design system are used. The `/design-system` route is checked during review.

## Migration Plan

- Existing installs with a profile set and no onboarding state: no auto-open. "Run setup again" is available.
- Existing installs stuck mid-old-wizard (profile null): the new wizard opens and pre-fills whatever exists.
- Rollback: revert the frontend. The backend endpoints from `onboarding-backend` are harmless if unused.

## Open Questions

- None blocking. Exact copy text is to be reviewed with the user during implementation.
