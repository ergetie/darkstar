## 1. EV cost attribution (API)

- [x] 1.1 Extend the aggregation query in `backend/api/routers/energy.py` with per-slot `ev_grid_kwh`, `ev_solar_kwh` and `ev_cost_sek` sums (grid-first; cost = grid import cost only).
- [x] 1.2 Return `ev_grid_kwh`, `ev_solar_kwh`, `ev_cost_sek` and `ev_solar_share` (null when there is no EV energy) from `/api/energy/today` and `/api/energy/range`, including the zero-fallback response.
- [x] 1.3 Tests:
  - night (all grid), midday (partial solar), no EV, null prices
  - grid + solar = `ev_charging_kwh`

## 2. Grid & Financial EV row (frontend)

- [x] 2.1 Add the EV fields to the energy response type and the fetch mapping in `frontend/src/components/CommandDomains.tsx`.
- [x] 2.2 Render the EV breakdown row (later refined to the "↳ of which EV" sub-row under Grid Import) (cost, kWh, "X% solar") with design-system tokens, labelled as part of the existing totals. Hide it when there is no EV energy.
- [x] 2.3 Verify the headline Net and the existing rows are unchanged. Check the row in the `/design-system` style at phone width.

## 3. Per-charger recorded energy (DB change approved 2026-09-25)

- [x] 3.1 Add the `EvChargerObservation` model (`slot_start`, `charger_id`, `energy_kwh`, `created_at`; PK `slot_start` + `charger_id`) and an idempotent Alembic migration.
- [x] 3.2 Persist the recorder's `ev_charger_energy` in the same transaction as the `slot_observations` upsert, replacing rows on re-record.
- [x] 3.3 Rewrite `_ev_delivered_today_kwh` to take a charger ID and the effective "now" (honour `now_override`). Return unknown when there are no rows.
- [x] 3.4 Use the per-charger delivered value in `_calculate_required_kwh` (only when no SoC sensor is configured) and in `_persist_ev_multi_day_state` (`delivered_kwh` null when unknown).
- [x] 3.5 Tests:
  - migration up/down
  - two-charger recording
  - idempotent re-record
  - per-charger delivered, and unknown when there is no data

## 4. Stale SoC handling

- [x] 4.1 Add last-known SoC plus reading time to `backend/core/ev_live_state.py`, updated only on valid reads.
- [x] 4.2 Add a resolved-SoC helper returning (value, status `live` | `carried` | `stale`, age), driven by `ev_chargers[].soc_stale_after_minutes` (default 15). Add the key to `config.default.yaml` and a settings field in the EV tab.
- [x] 4.3 Use the resolved SoC in the planner: suspend the goal requirement when a plugged charger's SoC is stale, and remove the capacity-minus-delivered fallback for chargers with a configured SoC sensor. Keep assumed-plugged planning (unplugged) on the persisted SoC regardless of age, and stop persisting a missing SoC as 0% (design D4a).
- [x] 4.4 Replace the "defaulting to 0%" log in `backend/core/ha_client.py` with truthful carry/suspend wording.
- [x] 4.5 EV API: report `status="soc_unavailable"` (plugged chargers only) plus `soc_status` and `soc_age_minutes`. The EV card shows the warning with design-system tokens.
- [x] 4.6 Send one notification per stale episode, and reset it on the next valid reading. Gate it on a new dedicated toggle `executor.notifications.on_ev_soc_stale` (default `true`): add it to `config.default.yaml` next to the other `on_*` toggles, to the executor notification config, and as a field in the existing notifications section of `frontend/src/pages/settings/types.ts`.
- [x] 4.7 Tests:
  - carried within the window, stale after it, custom window
  - recovery
  - one notification per episode
  - no notification when `on_ev_soc_stale` is false (planning is still suspended)
  - no SoC sensor configured keeps the SoC-less path
  - unplugged charger with a stale SoC is still planned from the persisted SoC, with no warning

## 5. Keep-on at any target

- [x] 5.1 Change `_apply_keep_on_after_target` to trigger when the resolved SoC (live or carried) is at or above target for any target, and never when stale.
- [x] 5.2 Tests: target 80 with SoC 81 flags slots; stale SoC flags none; the target-100 behaviour is unchanged.

## 6. Cleanup

- [x] 6.1 Remove the binary and current-charger 30-minute safety-timeout blocks in `executor/engine.py`, plus any state used only by them (`EVChargerState.charging_started_at`). Adjust the tests that asserted the log.
- [x] 6.2 Verify replan dispatch is unified: `ha_socket`, the EV API and the executor's `_request_balancer_replan` all go through `scheduler_service.request_replan` (delivered by `ev-goal-lifecycle-feedback`). No code change expected.
- [x] 6.3 Carry the per-charger `ev_shortfall_kwh` once on the solver result instead of on every slot. Update `compute_ev_goal_diagnostics` and the tests; the published `ev_goal_diagnostics` is unchanged.
- [x] 6.4 Log the "ready-by without target SoC" warning once per (charger, goal fingerprint) per process.
- [x] 6.5 Use `ev_slot_hours` for the slot-0 surplus EV terms in `planner/solver/kepler.py` (surplus reward, energy balance, excess-PV sink cap, surplus counted toward the goal). Add a partial-first-slot surplus test.

## 7. Follow-ups (user-approved 2026-09-26)

- [x] 7.1 Always show the "↳ of which EV" sub-row under Grid Import when an EV charger is configured (`hasEvCharger` passed from the Dashboard's `system.has_ev_charger`): "0 kr · 0 kWh" and no solar share when there is no EV energy; hidden when no charger is configured (unless the range has EV energy).
- [x] 7.2 Explain the row and the solar share with the card's native `title` tooltips (EV figure = grid import cost only, part of Grid Import; solar share = share of EV energy from solar, informational).
- [x] 7.3 Record a pending recovery in `ev_live_state` when a valid reading ends a stale episode; the executor's `_check_ev_soc_stale` consumes it and calls `request_replan(ReplanReason.SOC_RECOVERED, charger_ids=[id])` once per episode. A planner run that reads the recovered SoC discards the pending recovery.
- [x] 7.4 Tests:
  - frontend: configured-but-idle row shows 0 kr / 0 kWh without solar share; solar-share tooltip; hidden without a charger
  - backend: recovery triggers exactly one replan; no replan while stale, while fresh without a prior episode, on unplug, or for unconfigured chargers; planner discard

## 8. Verification

- [x] 8.1 Run `./scripts/lint.sh` and the full test suite.
- [x] 8.2 Run `openspec validate ev-cost-accuracy-cleanup` (spec sync happens on archive).
