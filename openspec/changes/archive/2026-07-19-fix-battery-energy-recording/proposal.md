## Why

Battery charge/discharge energy has been computed from a single instantaneous power snapshot (`battery_power * 0.25`) since this was added to the recorder in January 2026 — it has never used the cumulative meters (`total_battery_charge` / `total_battery_discharge`) that are already configured in `input_sensors` and already referenced by the `energy-recording` spec's cumulative-sensor requirement. Every other flow (PV, load, grid import/export) uses a cumulative-meter delta with snapshot only as a fallback; battery is the one exception.

When the instantaneous sample happens to land on a near-zero power reading during an actual sustained charge or discharge, the whole slot's battery energy silently drops to zero even though SoC is visibly moving. Production data confirms this is not rare: ~2-5% of slots per month show a real SoC swing with `batt_charge_kwh`/`batt_discharge_kwh` recorded as 0, and the rate spiked to 75% of slots on 2026-07-18, which is what tripped the `energy_balance` runtime invariant monitor. Fixing this closes a known gap between the spec (which already names Battery as a supported cumulative source) and the implementation (which never built it).

## What Changes

- Recorder computes `batt_charge_kwh` and `batt_discharge_kwh` from the configured `total_battery_charge` / `total_battery_discharge` cumulative sensors, using the same delta-based calculation already used for PV/load/grid, falling back to the power snapshot only when a cumulative sensor is missing or its meter resets.
- No schema changes — `batt_charge_kwh`/`batt_discharge_kwh` columns already exist and are already populated (just via the wrong method today).
- No new capability. This closes an existing gap in `energy-recording`: the spec has named Battery as a supported cumulative source since its first version, but no requirement scenario or code ever implemented it.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `energy-recording`: add requirement scenarios for battery cumulative-sensor delta calculation (mirroring the existing PV/load pattern), and update the snapshot-fallback requirement so battery is covered the same way PV/load/grid already are.

## Impact

- `backend/recorder.py` — battery energy calculation switches from snapshot-only to cumulative-delta-with-fallback (same `calculate_energy_from_cumulative` helper already used for PV/load/grid).
- `data/recorder_state.json` — two new tracked keys (`battery_charge_total`, `battery_discharge_total`) for delta calculation across recorder restarts, following the existing state-file pattern.
- No change to `backend/learning/backfill.py` — it does not independently compute battery energy today (only maps SoC), so it isn't part of this defect.
- Expected outcome: `energy_balance` invariant violations drop back toward the historical baseline (~2-5%/month → near the PV/load/grid baseline of near-zero), since the dominant source of residual error is removed.
