# Proposal

## Why

A user with a 20 A main fuse and a 3-phase hybrid inverter had a plan that grid-charged the house battery at about 10 kW with the EV off. A washing machine and other loads on one phase pushed that phase to about 24 A, and Darkstar did nothing. The real-time load balancer (`executor/load_balancer.py`) can only throttle type="current" EV chargers (`EVBalancerInput`/`EVBalancerOutput`) and switch off shed loads (`ShedLoadInput`/`ShedLoadOutput`). `give_way_order` parsing (`executor/config.py`, `_parse_load_balancing_config`) accepts only kind `"charger"` or `"shed"`. The battery path (`executor/controller.py` `_calculate_charge_limit` → `ControllerDecision.charge_value` → profile `{{charge_value}}` in `executor/actions.py`) never looks at phase currents. The planner only caps total import (`system.grid.max_power_kw`). Grid charging the battery is often the biggest controllable load in the house, but the fuse guard cannot touch it.

## What Changes

- New give-way entry kind `battery` (single entry, id `battery`) in `load_balancing.give_way_order`. The user places it anywhere in the list.
- When a phase the inverter draws on is over the limit and the entries above the battery are exhausted, the balancer reduces the battery's **grid** charge power by the remaining deficit. The cut applies to all of the inverter's phases (3-phase inverters draw evenly), never goes below zero, and never goes above the planned value. At the profile's minimum charge value it stops grid charging for the tick (the `idle` mode intent, so PV can still charge and the battery does not discharge).
- Only the grid-sourced part of the charge can be reduced, and only while the controller's mode intent is `charge` (planned grid charging). PV self-consumption, solar charging and discharge are never touched.
- After relief, the battery ramps back up toward the plan through the existing gates: `ramp_up_window_s` hold-off, the averaged `target_margin_percent` check, reverse-order restore.
- The override uses the same path as today: the balancer caps `decision.charge_value` (in the profile's `control_unit`, A or W) before `dispatcher.execute(decision)`. No profile writes are added, so Deye's program-6 SoC (`soc_target`) and the other mode actions stay as they are.
- The inverter is assumed to be 3-phase: the reduction is spread evenly over L1-L3. 1-phase inverters are out of scope.
- Battery interventions do not send `notify_interventions` notifications.
- Sustained battery throttling triggers one early replan via `replan_after_throttled_s`, like the chargers do.
- The battery shows up in the load-balancer status API, the status card, and the settings give-way editor.
- `heal_give_way_order` (and its frontend mirror `healOrderForDisplay`) learns the new kind and auto-appends the battery entry at the end of the list for existing users when an inverter profile with a charge mode is configured.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `phase-load-balancing`: adds battery grid-charge give-way, its relief/restore behaviour, stale handling and sustained-throttle replan.
- `load-balancing-settings`: adds the `battery` give-way kind, its self-heal, and the settings and status UI for it.

## Impact

- Backend: `executor/config.py` (`GiveWayOrderEntry`, give-way parsing, `heal_give_way_order`), `executor/load_balancer.py` (new `BatteryBalancerInput`/`BatteryBalancerOutput`, tick passes), `executor/engine.py` (`_run_load_balancer`, applying the cap to the decision before dispatch, `_track_balancer_throttling`, `get_load_balancer_status`), `backend/api/routers/config.py` validation if give-way kinds are checked there.
- Frontend: `frontend/src/pages/settings/components/giveWayOrder.ts`, `GiveWayListEditor.tsx`, `LoadBalancingTab.tsx`, `frontend/src/components/LoadBalancerStatusCard.tsx` / `LoadBalancerCompactView.tsx`, `frontend/src/lib/api.ts` types.
- Config: `config.default.yaml` (commented example of the battery entry). No new settings.
- No planner, schema or dependency changes. Related BACKLOG items (not edited): "[Planner] Per-Phase Load Awareness" and "[Load Balancer] Proportional Overload Timing" (fuse time-current curve) in `docs/BACKLOG.md`.
