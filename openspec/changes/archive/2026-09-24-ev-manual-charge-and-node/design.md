## Context

Verified current state (file refs at time of writing):

- **House Top Up**: `CommandBar.tsx` fixed list `TOP_UP_SOC_OPTIONS = [30,50,80,100]` (index stepper, no free input). Calls `quickAction.set('force_charge', 60, {target_soc})`. Executor quick action is in-memory only (`engine.py:266`), duration must be 15/30/60, and nothing compares SoC to `target_soc` — it just writes `soc_target` to the inverter and expires after 60 min.
- **EV on/off**: single source of truth `_charger_should_be_on(slot, id)` (`engine.py:3085`) = planned kW > 0.1 or `ev_keep_on`. Used by 3 sites: `_update_ev_surplus_and_phase_mode` (~2590), `_run_load_balancer` (~2703, `planner_target_a`), `_control_ev_charger` (~3097). Binary chargers are forced to match every tick, so any "on" outside the plan is reverted. Only EV override today is `force_stop`.
- **Executor does not read EV SoC or plug state**; those are read by `backend/core/ha_client.py` (planner) and `ha_socket.py` (live metrics). `EVChargerDeviceConfig` lacks `soc_sensor`/`plug_sensor` though they are in the YAML. `executor/actions.py:303 get_state_value` exists for HA reads.
- **Precedent**: per-device water boost (`_water_boost_until` dict, `set_/clear_/get_water_boost_status`, websocket emit) — in-memory, per device, dispatched via the normal per-device loop.
- **Goals** live in `data/ev_multi_day_state.json` via `backend/core/ev_state.py` (`update_ev_state`, atomic + file lock).
- **Frontend**: live `ev_chargers[]` = `{name, kw, soc, plugged_in, unreachable?}` with no id; Dashboard reads non-existent `ev_soc`. Goal target only in `GET /api/ev/chargers`. `PowerFlowCard` uses its own `getSubValue` (~341), ignoring registry accessors. lucide-react provides `Zap`, `Plug`, `Unplug`.

## Goals / Non-Goals

**Goals:** per-charger manual charge to target SoC that ends by itself; optional amps on current-type chargers; shared 15%-step stepper with exact entry for both top-ups; EV node showing SoC/target/state at a glance.

**Non-Goals:** persisting the house Top Up across restarts (stays in-memory like today); changing the planner's goal logic; phase-switching changes; EV card redesign beyond the manual-charge line.

## Decisions

1. **Per-charger manual charge in the executor, modelled on water boost** — `self._ev_manual_charge: dict[charger_id, ManualCharge(target_soc, current_a|None, started_at)]` with `set_/clear_/get_ev_manual_charge_status`. *Alternative*: a new global quick-action type — rejected: quick actions are single, global and capped at 60 min; EV charging takes hours and is per car.
2. **Hook at `_charger_should_be_on`** — return True when a manual charge is active for that id. This makes all 3 decision sites agree without special-casing each. The current-type target: in `_run_load_balancer` and `_control_ev_charger_current`, `planner_target_a` = manual `current_a` or `max_current_a`; surplus target is ignored for that charger while manual is active (it could only lower it). The balancer still clamps; shed, `force_stop`, and `skip_writes` still win because they are applied after/around these sites unchanged.
3. **Persistence** — store `manual_charge` per charger in `ev_multi_day_state.json` via `update_ev_state` (a separate key, goal fields untouched). Executor loads it at startup. *Alternative*: in-memory like water boost — rejected: a restart mid-charge would silently drop a multi-hour action. JSON file, not DB — no schema change.
4. **End detection in executor tick** — add `soc_sensor` and `plug_sensor` (+ existing `plugged_in_states`) to `EVChargerDeviceConfig`; read them each tick only for chargers with an active manual charge. End on SoC ≥ target, unplugged, user clear, or 24 h timeout. Unavailable SoC → keep charging until back or timeout. On end: clear persisted entry, emit event, request replan via the existing rate-limited path (`_executor_replan_allowed` / `_request_balancer_replan` pattern).
5. **Validation at start (API)** — reject unknown/disabled/`externally_controlled` charger, not plugged, SoC unknown, SoC ≥ target, target outside 1–100, current outside min–max, current on binary. Charger type taken from executor config (note `ev.py` defaults `type` to "current" in places while config default is "binary" — use the config value, not the API default).
6. **API** — `POST /api/ev/chargers/{id}/manual-charge {target_soc, current_a?}`, `DELETE /api/ev/chargers/{id}/manual-charge`; `GET /api/ev/chargers` gains `manual_charge: {target_soc, current_a, started_at} | null`. Websocket event `ev_manual_charge_updated`. Update route snapshot test.
7. **Live data id** — add `id` to each live `ev_chargers[]` entry (ha_socket + `/api` status) so the frontend can join live SoC/kW with `/api/ev/chargers` (target, manual charge, type) by id rather than by name/index.
8. **Shared `SocStepper` component** — − / + step 15, clamp 0–100 (EV: 1–100), value is a button that turns into a numeric `input` (Enter/blur commits, Esc cancels, invalid keeps old). Built with design tokens and added to the `/design-system` showcase. Used by Top Up and EV Charge.
9. **EV Charge control placement** — command bar (with the other manual controls), charger selector only when >1 controllable charger is plugged (copy Boost's heater selector). Amps behind a small collapsed "A" toggle, current-type only, default = `max_current_a`. EV card shows "Manual charge → 80% · Stop" line.
10. **EV node** — compute from `evChargers` + charger status: charging = `kw > 0.1` → `Zap` + "SoC → target"; plugged → `Plug` + "SoC"; else `Unplug` + "away" muted. Target = manual target ?? goal target ?? none. Multi-charger: aggregate icon + "N connected". Move the logic into one pure function (tested), used by `PowerFlowCard`; drop the dead `ev_soc` field.

## Risks / Trade-offs

- [SoC sensor lags or is car-cloud based (updates every few minutes)] → may overshoot target by a few %; acceptable, documented in UI help text.
- [Manual charge from grid at expensive price] → it is an explicit user action; source isolation already prevents the house battery discharging into the car.
- [Binary charger without a plug sensor is "assumed plugged"] → unplug end never fires; SoC-target and 24 h timeout still end it.
- [Surplus/phase-switch logic interacting with manual current] → manual chargers excluded from surplus targeting while active; covered by tests.
- [Replan right after end may immediately schedule more charging] → intended: returns to plan.

## Migration Plan

No migration: new optional state key and optional config fields (`soc_sensor`/`plug_sensor` already in YAML). Rollback = revert; a stale `manual_charge` key in the state file is ignored by old code.

11. **House Top Up ends at target** — in the tick (`engine.py` ~1303), after `_get_quick_action_status()`, if type is `force_charge` and `state.current_soc_percent >= target_soc`, clear the quick action and fall through to normal schedule. `set_quick_action` for `force_charge` ignores the 15/30/60 list and sets `expires_at = now + 24 h` as a safety timeout; validates `min_soc_percent ≤ target ≤ 100` and current SoC < target. Frontend no longer sends a meaningful duration. Existing tests for the duration list are kept for `force_stop`/`force_heat` and adjusted for `force_charge`.
12. **Stepper ranges** — house Top Up: `min_soc_percent`–100 (below minimum SoC is meaningless: the battery never goes there). EV: 1–100.
