## Why

Today's startup wizard asks four things (HA connection, inverter brand, battery kWh/solar kWp, load baseline). It leaves pricing, location, system flags, core sensors, battery limits, water heater, EV and executor mode untouched, so a "completed" install does not work. It also has bugs: a hardcoded brand list (the fake `victron` is listed, `sungrow` is hidden), profile suggestions saved under the wrong keys, the synthetic baseline never saved, and a live executor run at the end that actuates hardware. The goal is that a user who finishes onboarding has a fully working Darkstar, with entities found automatically wherever possible. Advanced tweaking stays in Settings.

## What Changes

- **New guided flow** (replaces the 4-step wizard): Connect → My system → Location & pricing → Inverter → Core sensors → Solar → Battery → Water heater → EV → Review & readiness. Steps for features the user doesn't have are skipped.
- **System definition first**: has solar / battery / water heater / EV, grid meter type, main fuse/grid limit. This drives which steps and checks apply.
- **Auto-fill everywhere**: location, timezone and currency from HA. The price area is an explicit SE1–SE4 choice with region descriptions, because the borders follow municipalities and can't be derived from coordinates. The inverter brand is suggested from discovery. Entities are pre-selected only when the match is high-confidence. Each picked entity shows its live value and unit.
- **Dynamic brand dropdown** from `GET /api/profiles`, so only shipped profiles appear and new profiles show up automatically.
- **Never overwrite silently**: on re-run, every step pre-fills current values. Wherever a suggestion differs from an existing value, the user explicitly picks "keep current" or "use suggested". The Review step shows a current → new diff before saving.
- **Resume, back, skip**: progress is persisted server-side, so the user can close and reopen onboarding to continue. Back navigation edits earlier steps. The whole onboarding can be skipped or closed at any time, and re-opened from Settings.
- **Per-step save**: each completed step saves its partial patch through the existing deep-merge save, so closing midway keeps the work done.
- **Readiness finish**: the final step shows the readiness checklist (pass/warn/fail with fix links). The user can finish while checks fail, but is told clearly that Darkstar won't work yet.
- **Shadow mode by default**: onboarding finishes with `executor.shadow_mode: true` and explains that Darkstar plans without controlling the hardware, and that shadow mode can be turned off in Settings when ready. A "Go live now" button sets `shadow_mode: false` after a confirm. The automatic live executor run at the end is removed. **BREAKING** for anyone relying on the wizard triggering an executor run.
- **Bug fixes absorbed**: the dotted-key suggestion spread, the synthetic baseline save, the standalone connection test, and the hardcoded brand list.
- **Swedish pricing only**: Nordpool area SE1–SE4 and the Swedish fee fields (VAT, energy tax, transfer fee), with clear labels.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `startup-wizard`: the triggering, steps and finalization requirements are replaced by a full guided onboarding with system definition, auto-discovery, explicit-overwrite semantics, resume/skip/back, readiness and a shadow-mode finish.

## Impact

- Frontend: `frontend/src/components/startup/StartupWizard.tsx` is replaced by a `frontend/src/components/onboarding/` module (a step registry plus one component per step). `App.tsx` changes its trigger logic and banner. `ProfileSetupHelper.tsx` adapts to the new suggestions shape. `EntitySelect.tsx` gains a live value and confidence display. `lib/api.ts` gets the new endpoint clients. Settings gets a "Run setup again" entry.
- Depends on `onboarding-backend` (discovery, matching, readiness, onboarding state, synthetic key) and `config-save-persistence`.
- Tests: new frontend tests for the wizard (there are none today).
- Follows `docs/design-system/AI_GUIDELINES.md` and the tokens in `frontend/src/index.css`.
- No new dependencies.
