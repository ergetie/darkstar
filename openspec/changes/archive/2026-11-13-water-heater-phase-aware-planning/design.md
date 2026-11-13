# Design

## Context

- `ev-single-phase-grid-limit` (planner/solver/kepler.py ~337-344, ~787-820) adds a per-phase row per charger-covered line: `(import - export)/3 + sum((share_c - 1/3) * kW_c * h) <= max_phase_import_kw * h`, where share_c = 1/len(phases). Net import already includes each EV spread evenly (1/3 per line), so the term corrects it to the charger's real share.
- Water heater phases today exist only in `load_balancing.loads[].phases` (executor/config.py ~643, `BalancedLoadConfig.phases`). The planner never sees them.
- `config.default.yaml` documents `loads[].phases`; `backend/api/routers/config.py` ~1803 errors on empty `phases` for every load.

## Double counting finding (house load vs water heater)

The house-load forecast does NOT include water heater consumption, so the VVB is not double counted:
- Recorder and backfill store `load_kwh` via `isolate_base_load(total, ev_kwh, water_kwh)` (backend/core/slot_energy.py:180, used in backend/recorder.py ~451/466 and backend/learning/backfill.py ~108): EV and water energy are subtracted, so the ML training target is base load only.
- In the solver (kepler.py ~610-750) the balance is `load + water_load_kwh + ev == pv + discharge + import + shedding`; water is added as its own decision term on top of the forecast.
- Therefore the existing "net/3" term already contains water_kw/3 (via grid import) and the correction `(share - 1/3) * water_kw` is exactly right, same as for EV. Residual risk: a heater whose sensor is not mapped (water_kwh = 0) leaves its draw inside the base forecast; the correction then slightly over-counts that heater. Accepted, documented in the manual (map the heater power sensor).

## Goals / Non-Goals

**Goals:** one source of truth for heater phases; planner avoids single-phase clashes of VVB + EV; migration is lossless; universal (no per-user values).

**Non-Goals:** per-phase house-load forecast (stays in docs/BACKLOG.md "[Planner] Per-Phase Load Awareness"); changing EV phase handling; changing balancer algorithms.

## Decisions

1. **`water_heaters[].phases`, default `[1,2,3]`.** Adapter reads it into `WaterHeaterInput.phases: tuple[int, ...]` (new field, default `(1,2,3)`), sanitising invalid input to the default with a warning (like `_charger_phases`). Not a user-facing "required" field (unlike EV) because a 3-phase spread is a correct default.
2. **Balancer reads device phases.** In executor/config.py, after parsing loads and water heaters, water_heater `BalancedLoadConfig.phases` is filled from the matching `water_heaters[]` entry (fallback `[1,2,3]` if heater missing; validation already flags unknown ids). `loads[].phases` is ignored for water_heater entries even if still present. Config validation: `loads[].phases` is required only for `custom_entity`; `water_heaters[].phases` validated 1-3, distinct, non-empty.
3. **Migration** `_migrate_water_heater_load_phases` in backend/config_migration.py, run in the pre-merge section next to the other 2.1x steps (before template merge so defaults do not mask it). Copy only if the heater has no `phases`; always drop from the load entry when a matching heater exists; keep and warn when none matches. Idempotent. Template merge must not re-add `phases` to load entries (the default `loads` is an empty list with a commented example, so it does not).
4. **Generalise the solver rows.** Replace `phase_limited_chargers` with a list of phase-limited "devices" (EV chargers with control_type current and < 3 phases, plus enabled water heaters with < 3 phases). Per slot and per line build coefficient vectors over the active devices (`share = 1/len(phases) if line in phases else 0`), dedupe identical vectors as today, and add the row with each device's kW expression:
   - EV: unchanged expression.
   - Water heater: `(water_heat[d][t] + water_boost[d][t]) / h`-style kWh term; the term added is `(share - 1/3) * kWh`.
   Water heaters have no deadline; they are active in every slot. `phase_limit_kw` is None when benchmark mode or when neither kind exists.
   Binary EV chargers keep their present exclusion (not phase-limited) to keep this change scoped.
5. **Feasibility.** Findings: `min_kwh_per_day` is already soft (`water_reliability_penalty_sek` per day), water heating can be 0 in any slot, so the limit alone cannot make the model infeasible. The only hard water constraint is `force_on_slots` (`water_heat == 1`, mid-block lock, kepler.py ~764). A forced slot could, with a high house base load and import already at its floor, push a row above the limit. Approach: add a non-negative slack variable `phase_slack[t, row]` only to rows of slots in which a phase-limited heater is forced on; the row becomes `... <= limit*h + slack` and the objective adds `PHASE_OVERLOAD_PENALTY * slack` (value well above the water reliability penalty and below `LOAD_SHEDDING_PENALTY`; fixed at `PHASE_OVERLOAD_PENALTY = 1000.0` SEK per kWh of slack, a module constant next to `LOAD_SHEDDING_PENALTY` in kepler.py: above the highest water reliability penalty (300 SEK/day) and below `LOAD_SHEDDING_PENALTY` (10000), so the solver prefers phase slack over fake house-load shedding). All other rows stay hard, as for EV today (EV can drop to 0, heater can be off). Slack use is logged at warning level once per solve. Rejected alternative: slack on all rows (would let the solver trade EV overload against cost, changing the established EV behaviour); and "skip rows with forced slots" (silently removes protection exactly when it matters).
6. **UI.** Phase picker (chips L1/L2/L3, same pattern as the EV "Phases" selector at EntityArrayEditor.tsx ~1348) added to the water heater card in the VVB tab (`EntityArrayEditor` with `entityType='water_heater'`, shown in WaterTab). `WaterHeaterEntity` gains `phases?: number[]`; default `[1,2,3]` in `createDefaultWaterHeater`. In `GiveWayListEditor.tsx` (Load Balancing tab) water_heater shed loads render phases as read-only `PhaseBadges` with a link/button to the VVB settings (existing settings deep-link mechanism, see SettingsDeepLink tests); custom loads keep the editable picker. Follow docs/design-system/AI_GUIDELINES.md (tokens from index.css, existing chip and tooltip components, no new colours).
7. **Docs and defaults.** config.default.yaml: add `phases: [1, 2, 3]` with a comment to the `water_heaters` entry and example; change the `loads[]` comment so `phases` is documented for `custom_entity` only ("water heaters: set phases on the water_heaters[] device").

## Risks / Trade-offs

- Heater with unmapped power sensor is partially double counted (see finding); mild, conservative.
- Users whose balancer worked via `loads[].phases` depend on the migration; a failed match (renamed heater id) keeps the old key and warns, and the balancer then falls back to `[1,2,3]` for that heater. Mitigation: the validation endpoint surfaces an issue when a water_heater load still carries `phases` without a matching device.
- New rows enlarge the MILP slightly (rows only when a phase-limited heater exists, deduped by coefficient vector); solver time limit unchanged.
- Planner and balancer agree on limits only if `load_balancing` margin config is the same source; this already holds for EV (`max_phase_import_kw`).
- Water heater control by planner already has `force_on_slots`; slack makes overload visible in logs but the balancer remains the runtime safety net.

## Resolved decisions (no open points for apply)

- Slack penalty: `PHASE_OVERLOAD_PENALTY = 1000.0` SEK/kWh (see item 5).
- Settings link: the water heater phase picker lives on the water heater card rendered by `frontend/src/pages/settings/WaterTab.tsx` (settings tab id `water`, label "Heating"). The read-only phases in `GiveWayListEditor.tsx` link to `/settings?tab=water`.
- Docs: update `docs/USER_MANUAL.md` (water heater phase setting, load balancing note) and `docs/BACKLOG.md` (per-device part of "[Planner] Per-Phase Load Awareness" done; per-phase house-load forecast remains, only if real cases show up). `docs/ARCHITECTURE.md` has no per-phase constraint section, so it is not changed. `docs/RELEASE_NOTES.md` is not touched. User approved these docs edits on 2026-11-13.
- Migration match failure (no water heater with the load's device_id): keep the load's phases, log a warning, and the validation endpoint reports a warning naming the device_id.
