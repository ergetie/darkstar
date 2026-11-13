## Why

On 2026-11-13 11:04-11:08 CET the go-e charger's plug sensor went `unavailable` in HA for about 3.5 minutes while the car was plugged in and charging (the car kept charging at 7 kW). Three code paths disagreed on what that means: the executor treated the plug as "unknown = not plugged" and dropped planned EV kW every tick, while the planner and the WebSocket handler kept the last known state. On reconnect, `ha_socket` then triggered an immediate re-plan that reshuffled slots and stopped charging for the current slot. A Wi-Fi blip should not interrupt a charge session.

## What Changes

- A shared helper in `backend/core/ev_plug.py` resolves a plug reading with a bounded grace window: while the sensor is unreachable and the outage is shorter than the window, the last known plug state (plugged or unplugged) is used; past the window, or if no state was ever seen, the plug is "unknown" (= not plugged, today's behaviour).
- The grace limit applies only in the executor (`_read_ev_plug_states` / `interpret_ev_live_state`, used for switching, plus the manual-charge path). The planner (`ha_client.py`) and the dashboard keep today's behaviour: last known state for the whole outage with the existing `unreachable` flag, so missed-goal recovery is unchanged.
- `ha_socket.py` no longer re-plans on "reachable again and connected" when the outage was within the grace window. It still re-plans after a longer outage, which preserves the missed-goal recovery purpose of commit 5440027b.
- New per-charger config key `plug_unreachable_grace_minutes` (default 10) in `config.default.yaml`, `executor/config.py` and the EV charger settings UI.
- Consequence note: the load-balancer pause on return (0.4 A below the 6 A floor while the battery grid-charged) was caused by the executor starting EV before the re-plan; it disappears once the plan is no longer dropped and no re-plan fires.

Non-goals: load balancer stale grid phase-current fail-safes are NOT changed (fuse safety). A survey found EV SoC (already `soc_stale_after_minutes`), battery SoC, load-balancer phases, water heater temperature, shed-load states and dashboard power metrics already handle `unavailable` acceptably; they are untouched.

## Capabilities

### New Capabilities
- `ev-plug-unreachable-grace`: how the plug state is resolved while the plug sensor is unreachable, and when an unreachable-to-reachable transition triggers a re-plan.

### Modified Capabilities
None. `ev-missed-goal-recovery` is unchanged: the planner keeps the last known plug state for the whole outage.

## Impact

- `backend/core/ev_plug.py`, `backend/core/ev_live_state.py`, `backend/ha_socket.py`, `executor/engine.py`, `executor/config.py`, `config.default.yaml`, `frontend/src/pages/settings/components/EntityArrayEditor.tsx`.
- No database schema change; no new dependencies; no `docs/` change.
