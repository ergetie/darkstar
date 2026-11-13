## Context

Plug-state paths today:
- `executor/engine.py:4719` `_read_ev_plug_states` -> `read_ev_live_state` -> `interpret_ev_live_state` (`backend/core/ev_live_state.py:172`): unreachable -> `"unknown"`, so `_gate_ev_plan_on_plug_state` (`engine.py:4741`) drops planned kW, keep-on and surplus every tick.
- Planner initial state `backend/core/ha_client.py:863` and `backend/ha_socket.py:537` use `resolve_plug_state` (`backend/core/ev_plug.py:226`), which keeps the last known state forever.
- `ha_socket.py:~580`: `was_unreachable and is_plugged == previous_plugged` triggers `_trigger_ev_replan`. Added by 5440027b (ev-goal-shortfall-recovery) so that goals missed during a long outage are re-planned when the charger returns.
- `soc_stale_after_minutes(ev)` (`ev_live_state.py:63`, default 15) is the SoC carry window; config key lives in `config.default.yaml:151`, UI in `EntityArrayEditor.tsx:1112`.

## Goals / Non-Goals

**Goals:** a short plug outage neither interrupts charging nor causes a re-plan; a long outage still ends in the old safe behaviour (executor treats plug as unknown) and a recovery re-plan.
**Scope note:** the grace limit applies only to the executor gate. The planner and dashboard already keep the last known state for the whole outage, and that is deliberately kept so missed-goal recovery (`planner/pipeline.py` ~320/~513) is unchanged.
**Non-goals:** load balancer phase fail-safes (fuse safety); other sensors (EV SoC, battery SoC, water heater temp, shed-load states, dashboard power metrics) already degrade acceptably.

## Decisions

1. **New per-charger key `plug_unreachable_grace_minutes`, default 10, not a reuse of `soc_stale_after_minutes`.** SoC staleness (15 min) tolerates a slow-updating cloud SoC; a plug sensor is local and a 3.5 min blip was the observed case, so the two have different failure profiles and users may want to tune them separately. 10 min is well above typical Wi-Fi/HA reconnects (seconds to a few minutes), and equals `EV_UNPLUG_DEBOUNCE_MINUTES` (`ev_plug.py:25`) so "short flicker" means one thing across the plug code. Validation mirrors `soc_stale_after_minutes`: non-numeric or negative falls back to default; 0 disables the grace (old behaviour). UI: a number input next to "SoC Stale After", min 0, max 240.
2. **Outage tracking in `ev_plug.py`.** Add `_unreachable_since: dict[str, datetime]` (set on first unreachable reading, cleared on a valid one) and `_last_outage_minutes: dict[str, float]` (set when an outage ends, kept until the next one; reset by `reset_plug_memory`). New helper `resolve_plug_with_grace(charger_id, raw_state, configured_states, grace_minutes, now=None)` returns a small frozen dataclass: `plugged_in` (effective: last known inside the window, else False), `plug_known` (False when never seen or window expired), `unreachable`, `outage_minutes`. `resolve_plug_state` is left as is; the helper is built on the same last-known memory.
3. **Executor.** `interpret_ev_live_state` gains `plug_grace_minutes` (passed from `charger.plug_unreachable_grace_minutes` in `_read_ev_plug_states` and the manual-charge caller at `engine.py:1381`). The dashboard (`routers/ev.py:791`) stays as is (no grace argument, so it keeps showing the last known state); this is simpler and unchanged. Unreachable inside the window returns `"plugged"`/`"unplugged"` from the last known state; otherwise `"unknown"`. `_gate_ev_plan_on_plug_state` is unchanged. Manual-charge plug check (engine.py ~1363) benefits automatically.
4. **Planner: unchanged.** `ha_client.py:863` keeps `resolve_plug_state` (last known for the whole outage, `unreachable` flag), so goal continuity in `planner/pipeline.py` and the ev-missed-goal-recovery spec are untouched. No `last_known_plugged` key, no planner wiring.
5. **ha_socket.** Keeps `resolve_plug_state` for the resolved state; reads the helper's recorded outage duration. Reconnect branch becomes: `was_unreachable and is_plugged == previous_plugged and last_outage_minutes >= grace` -> re-plan; within grace -> log "reachable again within grace window, no re-plan". The recovery purpose (re-plan after a long outage, during which the executor treated the plug as unknown) is preserved; a short outage never changed the executor's view, so there is nothing to re-plan. The `unreachable` branch and `is_plugged != previous_plugged` branches are unchanged. Note `ha_socket` currently holds `previous_plugged` from `latest_values` indefinitely for dashboard display; that is unchanged.
6. **Load balancer consequence.** The pause after return (0.4 A below the 6 A floor with battery grid-charging) came from the executor resuming EV before the re-plan landed. With the plan kept and no re-plan, there is no resume step. No load-balancer change.

## Risks / Trade-offs

- Car genuinely unplugged during an outage: charging control still drives the switch for up to the window; the measured-EV-draw fail-safe and the first valid reading (unplugged -> existing unplug re-plan) bound this. Acceptable; window is configurable down to 0.
- Process restart during an outage loses `_unreachable_since`; the outage then counts from the first post-restart unreachable reading, i.e. the grace clock restarts. Accepted (user-approved), bounded by one extra window.
- Multiple callers poll the helper; `_unreachable_since` is set only once and cleared only by a valid reading, so call order does not matter. `_last_outage_minutes` is non-consuming so ha_socket still sees it after the executor's poll ended the outage.

## Migration Plan

No schema change. `config.default.yaml` gets the key with a comment; runtime falls back to 10 when absent. Per-charger array items are not merged by `backend/config_migration.py` (no precedent for `soc_stale_after_minutes` either), so no migration step is needed; verify with the config-migration tests that an existing config without the key loads. Tests must not call real webhooks (dispatchers mocked).
