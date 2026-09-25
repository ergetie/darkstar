## 1. Charger power model

- [x] 1.1 Add `backend/core/ev_power.py` with `charger_power_limits(cfg, voltage) -> (min_kw, max_kw)` for current and binary chargers, plus unit tests (10 A 3-phase = 6.9 kW, binary `rated_power_kw`, missing fields → invalid)
- [x] 1.2 Add a config migration: drop `max_power_kw`/`nominal_power_kw` on current chargers (log the derived kW), and rename to `rated_power_kw` on binary chargers. Make it idempotent and back up the config first. Add tests.
- [x] 1.3 Update `config.default.yaml` and config validation in `backend/api/routers/config.py`: require amps and phases (current) or `rated_power_kw > 0` (binary), and validate `ev_planning.deferral_risk_margin_percent` in 0–100, `deferral_risk_margin_max_percent` in base–200 and `deferral_risk_ramp_hours` in 1–168
- [x] 1.4 Switch consumers to the helper:
  - `planner/solver/adapter.py` (`derive_min_power_kw`, `build_ev_charger_inputs`);
  - `planner/preflight.py`, `planner/errors.py` guidance, `backend/loads/service.py` disablement;
  - the pipeline status and diagnostics helpers (`pipeline.py` ~368-596, 694).
- [x] 1.5 Make executor `planned_kw_to_amps` and callers use the configured nominal voltage, and update the executor tests
- [x] 1.6 Verify with `rg "max_power_kw"` that no EV code path still reads it (grid/inverter usages stay)

## 2. Deferral pricing inputs

- [x] 2.1 Add a pipeline helper that, for a charger's goal, returns the post-horizon slots (after the last Kepler slot and at or before the deadline) with per-slot spot from the known-price resolver, falling back to the forecast `spot_p50`
- [x] 2.2 Convert spot to import price via `calculate_import_export_prices`. Add a test that forecast spot is never compared raw against import prices.
- [x] 2.3 Implement the missing-price fallback (trailing 14-day average import price × (1 + effective_margin), then the horizon maximum) with a warning log and a `deferral_price_source` result
- [x] 2.4 Build the tiers: sort by price, group into ≤ 24 blocks, energy-weighted price × (1 + effective_margin), capacity = Σ `max_kw × slot_h`. Add unit tests for the tier shape and the margin.
- [x] 2.5 Implement the deadline-proximity ramp (design D5): `effective_margin = base + (max − base) × clamp(1 − h / ramp_hours, 0, 1)`, applied to the tiers and the trailing-average fallback. Persist and log `effective_margin_percent` per charger. Unit tests: 72 h → base, 24 h → 31%, 6 h → 45.25%, at the deadline → max, max = base disables the ramp.

## 3. Kepler

- [x] 3.1 Extend `EVChargerInput` (`planner/solver/types.py`) with `deferral_tiers: list[(price, cap_kwh)]` and remove `quota_by_day`
- [x] 3.2 In `kepler.py`:
  - replace the quota caps and `effective_required` with `delivered_in_horizon (scheduled + surplus) + Σ deferred_k + shortfall ≥ required`;
  - add `deferred_k` variables with caps and objective terms;
  - return the solved `deferred_k`.
- [x] 3.3 Remove `_ev_day_energy_terms` quota usage and the task-4.4 quota comments. Keep the surplus energy terms for the requirement.
- [x] 3.4 Add solver tests:
  - the prod scenario (two published days, cheaper tomorrow → zero grid charging today);
  - forecast cheaper than every known slot;
  - known slot cheaper;
  - a large requirement spilling into dearer tiers;
  - a tail too short (forced in-horizon minimum);
  - an unreachable target stays feasible.

## 4. Pipeline integration and removals

- [x] 4.1 Replace the EV goal block (`pipeline.py` ~1476-1530): compute the tiers for every plugged charger with a goal and remove the >24 h gates (three sites)
- [x] 4.2 Delete `_compute_daily_ev_quota`, `_max_daily_kwh_for_deadline`, `planner/strategy/multi_day_planner.py`, and `tests/planner/test_multi_day_planner.py`. Drop the EV use of `fetch_price_floor_inputs`; the safety floor keeps its own call.
- [x] 4.3 Build `planned_by_day` after the solve:
  - in-horizon: scheduled + surplus per date;
  - post-horizon: deferred tier energy attributed cheapest-first per date;
  - `basis` of `known` or `estimated` per day.
- [x] 4.4 Update `_persist_ev_multi_day_state` to write `planned_by_day` and `deferral_price_source`, stop writing `daily_quota_kwh`/`quota_schedule`, and make the reader ignore old keys
- [x] 4.5 Update `compute_ev_goal_diagnostics` and `_warn_on_zero_scheduled_active_goals` so a goal fully deferred by price is not reported as a zero-schedule warning or `cost_tradeoff` at-risk

## 5. API and frontend

- [x] 5.1 `backend/api/routers/ev.py`: return `planned_by_day` and `deferral_price_source`, remove `daily_quota_kwh`/`quota_schedule`, and update `tests/backend/test_ev_api.py`
- [x] 5.2 `frontend/src/lib/api.ts` types: replace the quota fields with `planned_by_day`
- [x] 5.3 `EVChargingCard.tsx`: render "Planned per day" chips (solid for known, de-emphasised "est." with a tooltip for estimated, today highlighted), hidden when empty. Follow `docs/design-system/AI_GUIDELINES.md` and update the card tests.
- [x] 5.4 Settings: add `ev_planning.deferral_risk_margin_percent` (default 12), `deferral_risk_margin_max_percent` (default 50), `deferral_risk_ramp_hours` (default 48) and advanced `kepler.ev_shortfall_penalty_sek_per_kwh` to the EV tab in `frontend/src/pages/settings/types.ts`
- [x] 5.5 Charger editor: remove the max-power input for current chargers and show the derived min/max kW read-only (live), with a `rated_power_kw` input for binary chargers

## 6. Verification

- [x] 6.1 Run `./scripts/lint.sh` and the full test suite; everything must pass
- [x] 6.2 Dry-run the planner locally against a prod DB copy for the 2026-09-25 scenario and confirm no grid EV charging is planned today (2026-09-25 15:15, SoC 43→80%, 60 kWh, 12 A × 3 at 230 V = 8.28 kW, deadline 2026-09-26 23:00 inside the published horizon: 0.00 kWh today, 22.20 kWh tomorrow, 0 tiers/deferred, 0 shortfall)
- [x] 6.3 Check `openspec validate ev-planning-model` and that the specs match the implemented behaviour

## 7. Follow-ups (user-approved 2026-09-25)

- [x] 7.1 Add `system.grid.nominal_voltage_v` (default 230) next to `main_fuse_a` in `config.default.yaml`; drop `load_balancing.nominal_voltage_v` (was 220)
- [x] 7.2 Add the idempotent `_migrate_nominal_voltage` config migration (legacy value moved, new key wins, backup-before-write reused) with tests
- [x] 7.3 Read the single voltage everywhere: `ev_power.nominal_voltage_v()`, `ExecutorConfig.ev_nominal_voltage_v`, `LoadBalancingConfig.nominal_voltage_v` (per-phase voltage sensors still win), `executor/ev_surplus.py`, and the engine's measured-draw / per-phase W→A conversions; no hard-coded 230/220 left
- [x] 7.4 Settings: nominal voltage field in the System profile (100–260 V) with matching backend validation; remove the load-balancing field; charger editor reads the new key
- [x] 7.5 Verify and test that binary chargers use `rated_power_kw` only (no voltage/amps/phases)
- [x] 7.6 Add `charger_disabled_reason()`; register `missing_phases` / `missing_max_current` / `missing_rated_power`; return a named `disabled_reason` from `GET /api/ev/chargers`; show it on the EV card
- [x] 7.7 Migration logs a warning for current chargers without phases; validation message "Configure phases for <name> to enable planning"
- [x] 7.8 Charger editor: phases required for current chargers (pre-filled L1/L2/L3 for new chargers), missing-phases warning, save blocked; frontend tests
