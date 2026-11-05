# Proposal

## Why

The battery power limit is configured in one of two units (`executor.inverter.control_unit`: Amps, the default, or Watts), and `resolve_battery_power_limits` already turns the active pair into kW for the solver. Three other consumers ignore it and read their own fields, so users get wrong or contradictory behaviour depending on their unit:

- Manual "Charge" plans read a stray `battery.max_charge_power_kw` key that was removed from the defaults (commit a26b42c9) and never migrated away. Configs without it plan 0 kW; configs with it ignore the real limit.
- Setup readiness / planner preflight always validates `max_charge_w` / `max_discharge_w`, so an Amp-mode user with a hidden W value of 0 gets CONFIG_INVALID, and the real limit is never validated.
- The onboarding battery step always asks for Watts and requires them, and never asks Amp-mode users for `max_*_a`.

The settings UI helper texts also describe the limits inaccurately.

## What Changes

- Move the limit resolver to a neutral module `planner/battery_limits.py` and make manual plans, preflight and the solver/pipeline all use it.
- Manual plan "Charge" uses the resolved max charge kW instead of the stray key.
- Preflight validates the active unit's fields (via the resolver) and names the active field in the error.
- Onboarding battery step shows and requires the active pair (A or W) by the profile's control unit; completeness follows.
- Add `battery.max_charge_power_kw` and `battery.max_discharge_power_kw` to the deprecated-key migration so they are removed from user configs.
- Settings UI: correct the helper texts for the four limit fields and show a read-only effective kW hint (A x nominal voltage) under the Amp fields.
- `max_*_a` and `max_*_w` are both kept; each is live for one unit. Executor clamping is unchanged.

## Capabilities

### New Capabilities
- `battery-power-limits`: a single unit-aware definition of the battery max charge/discharge power and its use by solver, manual plans, preflight, onboarding and settings.

### Modified Capabilities
- `planner-diagnostics`: battery preflight validates the active control unit's fields instead of always Watts.
- `config-migration`: stray battery kW keys are stripped by the deprecated-key migration.

## Impact

- `planner/battery_limits.py` (new), `planner/solver/adapter.py`, `planner/pipeline.py`, `planner/strategy/manual_plan.py`, `planner/preflight.py`, `backend/config_migration.py`
- `frontend/src/components/onboarding/steps.tsx`, `helpers.ts`, `frontend/src/pages/settings/types.ts`, `SettingsField.tsx`, new `frontend/src/pages/settings/batteryPower.ts`
- Tests: `tests/planner/test_preflight.py`, `tests/planner/test_adapter.py`, new `tests/planner/test_battery_limits.py` and `tests/planner/test_manual_plan.py`, `tests/backend/test_onboarding_backend.py`, `tests/config/test_config_migration.py`, onboarding `helpers.test.ts` and `OnboardingWizard.test.tsx`, new `batteryPower.test.ts`
- No config schema change, no new dependencies, no DB change. Executor untouched.
