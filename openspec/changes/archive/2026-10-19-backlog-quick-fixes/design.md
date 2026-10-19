# Design

## Context

Verified against code on 2026-10-18, rebased onto robust-sensor-reading, ev-delivered-energy-guard, pv-forecast-partial-fallback and ev-single-phase-grid-limit (all archived and committed). Existing main specs `binary-water-heater-control` and `planner` already cover water heater control type and the inverter AC limit, so the deltas are MODIFIED.

## Decisions

**1. created_at.** `store.py` `SlotForecast` upsert `set_` (~466-484) omits `created_at`; add `"created_at": func.current_timestamp()` exactly as `store_plan` does. Same naive-UTC format. Test: store twice with a pause, assert timestamp advanced and values updated (including the openmeteo coalesce behavior unchanged). Day-ahead history stays out of scope (Planner Run Archive item).

**2. Water heater control type.**
- Supported domains (verified in `executor/config.py` ~762-780 and the validator): switch: `switch.`, `input_boolean.`; temperature: `number.`, `input_number.`. `water_heater.*` and `climate.*` are NOT supported by the executor (it skips such heaters), so they are not auto-detected; they give an explicit unsupported-domain error naming the supported ones.
- Add one shared helper `infer_control_type(entity) -> "switch"|"temperature"|None` used by `_validate_config_for_save`, and by the executor config loader so both agree (executor currently defaults missing to `temperature` and silently skips mismatches, which is a plausible cause of the report).
- Backend: when `control_type` is missing/empty, infer from domain; validate only if explicit. Explicit mismatch remains severity error. In the save-time path, also write the inferred value back into the saved data so the file is explicit.
- Frontend (`EntityArrayEditor.tsx`): on `target_entity` change, set `control_type` from the domain via a pure helper in `logic.ts`; entity filter keeps following control type, so the picker for the other type still shows the matching entities. Changing control type manually clears an entity of the wrong domain. Do not change the toggle on/off behavior beyond this.
- Inline error: `useSettingsForm.ts` (~390) currently only shows `errors[0].message` as a status message. Map backend errors for `water_heaters[i]` to the Heating tab (add an index/field path to the issue payload) and render beneath that heater's control type field, plus mark the Heating tab. This keeps the mismatch fixable without hunting.
- "Water tab unreachable" half: fixed by 5ca78c7d (all tabs always rendered, `showIf` removed in `index.tsx`); covered by `SettingsNavigation.test.tsx`. Only add a regression test that the Heating tab stays reachable after a failed save.

**3. Inverter AC limit** (`kepler.py` ~642-653). Grid charge = `charge[t] - pv_to_battery[t]` (no new variables).
- `dc_coupled`: `pv_to_ac + discharge + (charge - pv_to_battery) <= max_inverter_ac_kw*h`. The inverter AC stage carries PV output, battery discharge, and rectified grid charge. Sum (not net) is chosen as conservative and matching the backlog; simultaneous discharge and grid charge is never economic.
- `ac_coupled`: all battery charge crosses the AC inverter and `pv_to_battery <= charge`, so replace `pv_to_battery` with `charge`: `pv_to_ac + pv_to_battery + discharge` becomes `pv_to_ac + charge + discharge`, with `pv_to_battery` kept for the PV balance. (Equivalent in the dc case to adding grid charge; in ac_coupled the old row already counted PV-charge, now it also counts grid charge.)
- Feasibility: charge, discharge and pv_to_ac can all be zero with PV curtailed, so the row is always satisfiable; EV/load never appear in it (grid serves load directly).
- Solve time: no new variables, one modified row per slot with `charge` added. Measure with a 192-slot scenario (5 runs) before/after; accept if change is within noise (<10%).
- Interaction with `ev-single-phase-grid-limit`: the phase rows constrain grid import/EV per phase; the AC row is independent of them and uses only charge/discharge/PV flows, so both stack without affecting feasibility. Verified by test.
- User decisions: control type auto-detected in UI on selection and in backend when missing; explicit mismatches shown inline per heater; AC limit flows summed.

## Risks / Trade-offs

- Slightly lower grid charge power on installs whose `max_inverter_ac_kw` was set too low (e.g. below battery charge rating) → documented in release notes; user can raise the setting.
- Auto-detect could override a user's intent for unusual entities (e.g. a `number.` entity controlling a switch-like device) → only on entity change; user can still set control type, and explicit values are respected by the backend.

## Open Questions

None blocking.
