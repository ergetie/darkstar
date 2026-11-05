# Tasks

## 1. Shared resolver module

- [x] 1.1 Create `planner/battery_limits.py` containing `resolve_control_unit(config)` (returns `"W"` only when `executor.inverter.control_unit == "W"`, else `"A"`) and `resolve_battery_power_limits(config)` moved verbatim from `planner/solver/adapter.py` (~498-523), using `resolve_control_unit`.
- [x] 1.2 In `planner/solver/adapter.py` remove the function body and import it from `planner.battery_limits` (name stays importable from the adapter); in `planner/pipeline.py` (~48) import it from `planner.battery_limits`.
- [x] 1.3 Add `tests/planner/test_battery_limits.py`: A mode, W mode, default unit is A, missing keys give 0.0, voltage default 48 and `system_voltage_v` fallback, `system.battery` vs top-level `battery`, `resolve_control_unit` defaults. Existing resolver tests in `tests/planner/test_adapter.py` (~703-733) must still pass unchanged.

## 2. Manual plan fix

- [x] 2.1 In `planner/strategy/manual_plan.py` (~39-43) replace the `max_charge_power_kw` lookup with `resolve_battery_power_limits(config)[0]`; log a warning when it is 0.
- [x] 2.2 Add `tests/planner/test_manual_plan.py`: Amps config without stray key plans 4.8 kW for a Charge entry; W config plans 5.0 kW; stray `battery.max_charge_power_kw: 8` is ignored; unconfigured limit plans 0 kW and logs a warning.

## 3. Preflight fix

- [x] 3.1 In `planner/preflight.py` `check_battery_config` (~33-34, ~52-60) take the limits from `resolve_battery_power_limits(config)` and raise CONFIG_INVALID with `details` `field` = `battery.max_charge_a|w` / `battery.max_discharge_a|w` per `resolve_control_unit`, `value` (kW) and `control_unit`.
- [x] 3.2 Update `tests/planner/test_preflight.py`: the `_valid_config` helper (~50-59) sets `executor.inverter.control_unit: "W"`; add tests for A-mode valid with `max_charge_w = 0`, A-mode missing `max_discharge_a` naming `battery.max_discharge_a`, W-mode zero naming `battery.max_charge_w`.
- [x] 3.3 In `tests/backend/test_onboarding_backend.py` add a readiness test: an Amps-mode config with valid `max_*_a` and `max_*_w = 0` yields `battery_limits` status pass; with `max_charge_a` missing it yields fail and the message names `battery.max_charge_a`. Use the existing readiness fixtures in that file.

## 4. Config migration

- [x] 4.1 In `backend/config_migration.py` add `"max_charge_power_kw"` and `"max_discharge_power_kw"` to `DEPRECATED_NESTED_KEYS["battery"]` (~137-141) with a comment (removed from defaults in a26b42c9, read by no code).
- [x] 4.2 Add a test in `tests/config/test_config_migration.py` next to `test_remove_deprecated_keys_nested`: both keys removed, `max_charge_a`, `max_charge_w`, `max_discharge_a`, `max_discharge_w` preserved, `changed` true; second run returns `changed` false.

## 5. Onboarding

- [x] 5.1 Add `activeControlUnit(config, profiles)` to `frontend/src/components/onboarding/helpers.ts` (profile `behavior.control_unit`, else `executor.inverter.control_unit`, else `'A'`).
- [x] 5.2 In `frontend/src/components/onboarding/steps.tsx` `BatteryStep` (~763-835) render `battery.max_charge_a` / `battery.max_discharge_a` (unit A, step 1, min 1) for A and `battery.max_charge_w` / `battery.max_discharge_w` for W; keep the voltage field for A; update the footer sentence to name the active unit.
- [x] 5.3 In the battery step definition (~1280-1300) make `buildPatch` return the active pair (plus `nominal_voltage_v` for A) and `isComplete` require the active pair > 0 (voltage rule for A unchanged).
- [x] 5.4 Update `helpers.test.ts` (~49-58, ~69): the W case keeps passing; add an A profile case that is complete with `max_*_a` and `nominal_voltage_v` and no W values, and incomplete without `max_*_a`; add `activeControlUnit` cases (profile wins, config fallback, default A).
- [x] 5.5 Update `OnboardingWizard.test.tsx`: A profile shows current fields and no Watts fields; W profile (existing fixture at ~62) shows Watts fields.

## 6. Settings UI

- [x] 6.1 In `frontend/src/pages/settings/types.ts` (~951-1010) reword the four helpers to describe the battery's maximum charge/discharge current or power (remove "allowed from grid" and "for load following").
- [x] 6.2 Create `frontend/src/pages/settings/batteryPower.ts` exporting `DEFAULT_BATTERY_VOLTAGE_V = 48` (comment: mirrors the backend resolver default) and `effectiveBatteryKw(amps, voltage)` returning a formatted string or null when amps is not a positive number.
- [x] 6.3 Add optional `effectiveKwVoltageKey?: string` to `BaseField` in `types.ts`, set it to `battery.nominal_voltage_v` on `battery.max_charge_a` and `battery.max_discharge_a`, and render a `text-[10px] mt-1 text-muted` hint `~X.XX kW at NN V` in `SettingsField.tsx` below the input using `fullForm` values.
- [x] 6.4 Add `frontend/src/pages/settings/batteryPower.test.ts` (positive value, empty, zero, voltage fallback to 48).

## 7. Verification

- [x] 7.1 Run `UV_NO_SYNC=1 uv run python -m pytest tests/planner tests/config tests/backend/test_onboarding_backend.py -q`, the frontend vitest for onboarding and settings, then `./scripts/lint.sh`; fix any failures.
