# Design

## Context

`resolve_battery_power_limits(planner_config)` (planner/solver/adapter.py:498) returns `(charge_kw, discharge_kw)`: control unit `W` gives `battery.max_*_w / 1000`; otherwise (default `A`) `battery.max_*_a x nominal_voltage_v / 1000` (default 48 V, falling back to `system_voltage_v`). It reads the battery block from `system.battery`, else top-level `battery`, and the unit from `executor.inverter.control_unit` (default `A`). It is used by the adapter (adapter.py:593) and pipeline (pipeline.py:954). The executor clamps in the active unit (executor/controller.py:184-187, 469) and already agrees with the planner in both modes. The settings UI already shows only the active unit's fields (`showIf` in frontend/src/pages/settings/types.ts) and SystemTab.tsx:101-108 syncs `control_unit` to the selected profile.

Divergent consumers: planner/strategy/manual_plan.py:39-43 (stray kW key), planner/preflight.py:33-34 and 52-60 (always W), onboarding steps.tsx battery step and completeness (always W).

## Goals / Non-Goals

**Goals:**
- One definition of "max battery charge/discharge kW" used by every consumer in the planner and backend readiness.
- Onboarding and preflight follow the same active-unit rule as the solver.
- Remove the dead stray keys from user configs.

**Non-Goals:**
- Removing or renaming `max_*_a` / `max_*_w`.
- Changing executor clamping or its unit resolution (profile vs config at controller.py:208-216). It already agrees; importing planner code into the executor would add coupling for no behaviour gain.
- Changing the unit-sync logic in SystemTab.

## Decisions

1. **Neutral module `planner/battery_limits.py`.** Move `resolve_battery_power_limits` there unchanged in behaviour. `planner/solver/adapter.py` imports it (so `from planner.solver.adapter import resolve_battery_power_limits` keeps working for existing tests) and `planner/pipeline.py` imports from the new module. Alternative: leave it in the adapter and import from there in manual_plan/preflight. Rejected: preflight and manual plan would depend on the solver module (heavy imports, possible cycles), and the function is not solver-specific.
2. **Add `resolve_control_unit(config) -> "A" | "W"`** in the same module (default `A`, any value other than `W` is `A`), used by the resolver and by preflight to pick the field name. Executor stays as is.
3. **Manual plan** computes `charge_cap_kw = resolve_battery_power_limits(config)[0]` once. If the result is 0, it logs a warning (limit not configured) and plans 0 kW as before. No fallback to invented values.
4. **Preflight** calls the resolver for the limits; the field in the error details is the active field (`battery.max_charge_a` or `battery.max_charge_w`, likewise discharge). `details` keeps `value` in kW and gains `control_unit`. SoC and capacity checks are unchanged. The battery block for non-limit checks is still read as today.
5. **Onboarding** gets a helper `activeControlUnit(config, profiles)` in helpers.ts: profile `behavior.control_unit` if set, else `executor.inverter.control_unit`, else `A`. The battery step renders `battery.max_charge_a` / `max_discharge_a` (unit A, with the existing voltage field) for A, and `max_*_w` for W. `buildPatch` includes only the active pair (plus voltage for A); `isComplete` requires the active pair > 0. The footer sentence names the active unit. The inactive pair is neither shown, required nor patched.
6. **Migration**: append `max_charge_power_kw` and `max_discharge_power_kw` to `DEPRECATED_NESTED_KEYS["battery"]` with a comment (removed from defaults in a26b42c9, read by no code after this change). The existing `remove_deprecated_keys` handles it, idempotently.
7. **Settings UI**: reword helpers: charge "Maximum charge current of the battery (per the inverter/battery spec)", discharge likewise, W variants "Maximum charge/discharge power of the battery". Add optional `BaseField.effectiveKwVoltageKey?: string`; when set, SettingsField renders a `text-[10px] mt-1 text-muted` line (same pattern as the existing field feedback line) `~X.XX kW at NN V` under the number input, computed by a pure helper `effectiveBatteryKw(amps, voltage)` in `frontend/src/pages/settings/batteryPower.ts`. Voltage comes from `battery.nominal_voltage_v` in the form, falling back to 48 (`DEFAULT_BATTERY_VOLTAGE_V`, mirroring the backend). Hidden when the amps value is empty or not positive. Styling uses existing tokens per docs/design-system/AI_GUIDELINES.md (muted helper text); no new tokens.

## Implementation deviations (accepted)

- **Readiness message**: `backend/core/readiness.py` appends the active field name from the `PlannerError` details (for example `(battery.max_charge_a)`) to the `battery_limits` message, and the fix hint is unit-neutral ("active control unit (Amps or Watts)") instead of naming Watts.
- **`buildPatch` signature**: onboarding `StepDefinition.buildPatch` is now `(config, profiles)` (was `(config)`) so the battery step can patch only the active pair; `OnboardingWizard.tsx` passes `profiles`.
- **Existing readiness test**: the existing battery readiness test in `tests/backend/test_onboarding_backend.py` sets `executor.inverter.control_unit: "W"` explicitly, since the default unit is now A for preflight.
- **Manual plan warning**: the zero-limit warning is logged only when a Charge entry is actually applied, not on every manual plan call. The limit is still resolved once up front.
- **Onboarding unit rule**: profile control unit, else config `executor.inverter.control_unit`, else A; a profile with a null/absent control unit falls back to the config value.

## Risks / Trade-offs

- [Existing preflight tests build configs with only `max_*_w` and no `control_unit`; the resolver defaults to A, so they would now fail] -> the test helper sets `executor.inverter.control_unit: "W"` explicitly, and new A-mode tests are added.
- [A user in A mode with no `max_*_a` now fails preflight where before they passed on W] -> intended: the planner already plans 0 kW for them. The error names the field to fill in.
- [Mismatched profile vs config unit on the onboarding page] -> profile wins (matches SystemTab sync, which overwrites the config unit on save).
- [Frontend voltage fallback duplicates backend 48 V] -> constant commented with a pointer to the backend resolver.

## Migration Plan

Startup migration strips the two stray keys; nothing else to deploy. Rollback is a plain revert; the stripped keys were unused.
