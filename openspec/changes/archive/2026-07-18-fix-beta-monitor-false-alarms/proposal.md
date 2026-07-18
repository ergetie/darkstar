# Fix beta-tester monitor false alarms

## Why

Beta testers with systems that differ from the reference installation see permanent red/yellow warnings that are false alarms: the PV forecast "physical ceiling" is a hardcoded 7.11 kW constant (any array larger than that violates forever), the command-success threshold (99 %) trips on a single 15-minute HA restart, and Fronius lifetime-energy sensors that read 0 overnight blow up the load-history profile builder (19,609 "kWh/day"), silently forcing the demo load forecast with a misleading "configure your sensor" message. Fresh installs additionally log a scary `Profile file not found: profiles/None.yaml` ERROR, and none of the warning banners can be dismissed/snoozed.

## What Changes

- Derive the forecast-sanity PV ceiling from the user's configured solar arrays (Σ kWp × 0.25 kWh per 15-min slot) instead of the hardcoded `7.11 * 0.25` constant; skip the check when no arrays are configured.
- Lower `COMMAND_SUCCESS_MIN` from 0.99 to 0.95 so short outages/restarts (~up to 72 failed minutes per 24 h) don't trip the invariant.
- Add a per-delta sanity guard to the HA load-history profile builder: skip cumulative-meter jumps larger than `recorder.max_meter_delta_kwh` (reuse existing config, default 50 kWh) instead of discarding the whole profile; keep the 500 kWh/day bound as a final backstop.
- Make the degraded-load-forecast message accurate: distinguish "sensor not configured" from "sensor data discarded as implausible".
- Treat a `null`/empty `system.inverter_profile` (the shipped default) as "generic" directly, without attempting to load `profiles/None.yaml` and logging an ERROR on every fresh install.
- Make health warning banners snoozable: an ✕ button snoozes that specific issue (keyed by issue code/category) for a fixed window; it reappears when the snooze expires. No permanent dismissal.

## Capabilities

### New Capabilities
- `load-history-sanitization`: per-delta guard and honest degraded messaging when building the 7-day load profile from a cumulative HA energy sensor.
- `system-alert-snooze`: snooze (not dismiss) behavior for health warning banners in the UI.

### Modified Capabilities
- `runtime-invariant-monitors`: forecast-sanity ceiling becomes config-derived (per-system) instead of a hardcoded constant; command-success threshold changes from 99 % to 95 %.
- `executor`: inverter profile loading falls back to `generic` gracefully when the configured profile is null/empty (no ERROR-level log for the shipped default).

## Impact

- `backend/monitors.py` — threshold constant, config-derived ceiling.
- `backend/core/ha_client.py` — delta guard in `get_load_profile_from_ha`, degraded-status messaging.
- `executor/profiles.py` — null-profile fallback.
- `frontend/src/components/SystemAlert.tsx` (+ `App.tsx`) — snooze button and localStorage-based snooze state.
- Tests for monitors, ha_client profile builder, profiles loader, SystemAlert.
- No DB schema changes, no API changes (frontend snooze is client-side).
