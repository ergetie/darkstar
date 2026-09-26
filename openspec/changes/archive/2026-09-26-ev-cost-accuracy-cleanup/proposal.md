## Why

The Grid & Financial card hides EV charging inside "Grid Import". The user can't see what charging the car costs, or how much of it came from solar. Several EV data paths are also inaccurate or misleading:

- A failed SoC read makes the planner treat the car as needing its full target capacity, while the log claims it is "defaulting to 0%".
- "Delivered" is one total for all chargers.
- Keep-on-after-target only works at exactly 100%.

A round of point fixes has also left dead or duplicated EV code. This change makes EV cost visible, makes EV accuracy trustworthy, and removes that cruft. It is the third of four EV changes, after `ev-planning-model` (archived 2026-09-25) and `ev-goal-lifecycle-feedback` (archived 2026-09-26), and is written against the code as they left it.

## What Changes

- **EV cost row in Grid & Financial.** The energy endpoints return an EV cost for the period, attributed per slot:
  - EV energy covered by grid import is priced at the slot's import price.
  - The EV cost is its grid import cost only; solar energy is not priced and is shown as an informational solar share.
  - The solar share of EV energy is shown.

  The card shows a "↳ of which EV" sub-row under Grid Import with kWh, grid import cost and solar share. It does not change the headline Net.
- **Stale SoC handling.**
  - When a plugged charger's SoC reading is unavailable, the planner keeps using the last known valid SoC for a configurable window (`ev_chargers[].soc_stale_after_minutes`, default 15).
  - After that window, the planner stops planning goal charging for that charger, and a warning is surfaced (log + EV API status + notification, with its own toggle `executor.notifications.on_ev_soc_stale`).
  - Unplugged chargers keep `ev-goal-lifecycle-feedback`'s assumed-plugged planning from the last persisted SoC; the stale window does not apply to them (see design D4a).
  - The misleading "defaulting to 0%" log is replaced.
  - **BREAKING (behavioural):** the "SoC unknown → full target capacity minus aggregate delivered-today" fallback is removed.
- **Per-charger delivered energy.**
  - The recorder already computes per-charger slot energy (`ev_charger_energy`) but throws it away. It will be persisted.
  - `delivered_kwh` and the delivered-today inputs become per charger instead of the unattributable aggregate.
  - This requires a new storage location. DB schema change, approved by the user on 2026-09-25.
- **Keep-on after target for any target.** `keep_on_after_target` applies whenever the live SoC is at or above the configured target, not only when target == 100.
- **Cleanup (no user-facing behaviour change):**
  - Remove the no-op binary-charger 30-minute "safety timeout" in the executor, and the log-only current-charger counterpart.
  - ~~Route every planner replan request through one shared dispatch helper.~~ Already delivered by `ev-goal-lifecycle-feedback` (`scheduler_service.request_replan`, used by `ha_socket`, the EV API and the executor's balancer replan). Verified; nothing left to do here.
  - Stop copying the solver's per-charger `ev_shortfall_kwh` onto every slot result. Carry it once per solve. This is internal only; the published diagnostics are unchanged.
  - Log the "ready-by set without target SoC" warning once per goal state, not on every planner run.
  - Use `ev_slot_hours` (the remaining in-progress slot time) for surplus EV energy terms in slot 0 (reward, energy balance, excess-PV sink cap, and the surplus counted toward the goal), matching scheduled EV energy.

## Capabilities

### New Capabilities
- `ev-cost-attribution`: Source-aware EV charging cost and solar share for a period, computed from slot observations. Exposed by the energy endpoints.
- `ev-soc-staleness`: Last-known SoC carry-over window, the stop-and-warn behaviour when SoC is stale, and truthful logging.
- `ev-per-charger-energy`: Persisting per-charger recorded EV energy, and using it for delivered-today and `delivered_kwh`.

### Modified Capabilities
- `grid-financial-wear-display`: The card's breakdown gains a "↳ of which EV" sub-row under Grid Import (grid import cost, kWh, solar share).
- `energy-totals-api`: The endpoints return the EV cost fields next to `ev_charging_kwh`.
- `ev-target-charging`:
  - Keep-on applies at any target.
  - Required energy no longer falls back to full capacity when SoC is unknown; it defers to `ev-soc-staleness`.
  - In-progress slot timing covers surplus energy too.
- `ev-live-state`: Adds a last-known-valid SoC (with age) next to the live reading. The live reading itself still reports unknown as none.
- `per-device-ev-scheduling`: Removes the 30-minute "safety timeout" from per-device executor state. It never changed behaviour, because the stop already follows from the plan.
- `ev-current-control`: Removes the safety-timeout references from the pause-semantics and binary-charger requirements.

## Impact

- **Backend:**
  - `backend/api/routers/energy.py`: the energy aggregation query.
  - `backend/recorder.py`, `backend/learning/store.py`, `backend/learning/models.py`: new per-charger energy storage plus an Alembic migration.
  - `backend/core/ev_live_state.py`, `backend/core/ha_client.py`: SoC reads.
  - `backend/api/routers/ev.py`: status and warning fields.
- **Planner:**
  - `planner/pipeline.py`: `_resolve_ev_charger_plan_state`, `_calculate_required_kwh`, `_ev_delivered_today_kwh`, `_persist_ev_multi_day_state`, `_apply_keep_on_after_target`, `merge_ev_goals_from_state`, `compute_ev_goal_diagnostics`.
  - `planner/solver/kepler.py`: surplus slot hours, shortfall output.
- **Executor:** `executor/engine.py` (safety timeout removal, stale-SoC notification), `executor/config.py`, `executor/actions.py`.
- **Frontend:**
  - `frontend/src/components/CommandDomains.tsx`: the Grid & Financial card.
  - The EV card, for the stale-SoC warning.
- **Config:** a new optional `ev_chargers[].soc_stale_after_minutes` and `executor.notifications.on_ev_soc_stale` in `config.default.yaml`, plus settings fields.
- **DB:** one migration, adding per-charger EV energy. Ask-First.
- **Dependencies:** both sibling changes have landed. The per-charger delivered value feeds the SoC-less required-energy estimate; the stale-SoC rule composes with assumed-plugged planning as described in design D4a.
