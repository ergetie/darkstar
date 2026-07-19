## 1. Recorder: battery cumulative-delta calculation

- [x] 1.1 In `backend/recorder.py`, add a call to `calculate_energy_from_cumulative("total_battery_charge", ..., "battery_charge_total")` to compute `batt_charge_kwh`, mirroring the existing `total_grid_import` call in the `dual` meter branch.
- [x] 1.2 Add a call to `calculate_energy_from_cumulative("total_battery_discharge", ..., "battery_discharge_total")` to compute `batt_discharge_kwh`, mirroring the existing `total_grid_export` call.
- [x] 1.3 Replace the current unconditional snapshot lines (`batt_discharge_kwh = (battery_kw * 0.25) if battery_kw > 0 else 0.0` / `batt_charge_kwh = (abs(battery_kw) * 0.25) if battery_kw < 0 else 0.0`) so the snapshot formula is used only as the per-side fallback when its `calculate_energy_from_cumulative` call reports `used_cumulative=False`.
- [x] 1.4 Confirm `input_sensors.battery_power_inverted` is applied only to the `battery_kw` snapshot fallback path, not to the cumulative charge/discharge deltas.
- [x] 1.5 Confirm the two sides fall back independently (one side missing/reset does not force the other side to snapshot).

## 2. State persistence

- [x] 2.1 Confirm `RecorderStateStore` requires no changes — `battery_charge_total`/`battery_discharge_total` are just new keys handled by the existing generic `get_delta()` method.
- [x] 2.2 Manually verify (e.g. via a local run or the dev backend) that `data/recorder_state.json` gains `battery_charge_total` and `battery_discharge_total` entries after one recorder cycle.

## 3. Tests

- [x] 3.1 Add cumulative-delta test cases for battery charge/discharge in `tests/backend/test_recorder_deltas.py`, following the existing PV/grid test pattern (previous reading, current reading, expected `batt_charge_kwh`/`batt_discharge_kwh`).
- [x] 3.2 Add a test for independent per-side fallback: `total_battery_charge` configured and healthy, `total_battery_discharge` missing or reset — assert `batt_charge_kwh` uses the cumulative delta and `batt_discharge_kwh` uses the snapshot.
- [x] 3.3 Add a meter-reset test for `total_battery_discharge` (or charge): decreasing cumulative value falls back to snapshot for that side only, per the design's Decision 3.
- [x] 3.4 Update `tests/recorder/test_recorder_battery_sign.py` and `tests/recorder/test_recorder_inversion.py` if needed so they exercise the snapshot fallback path explicitly (no cumulative sensors configured) rather than assuming snapshot is always used.
- [x] 3.5 Run the full recorder test suite (`tests/recorder/`, `tests/backend/test_recorder_deltas.py`, `tests/backend/services/test_recorder_service.py`) and confirm all pass.

## 4. Verification

- [x] 4.1 Deploy to the darkstar production instance (or a dev instance pointed at its config) and confirm via logs that `battery_charge_total`/`battery_discharge_total` cumulative reads succeed each cycle (no persistent "Meter reset" or missing-sensor warnings). Verified via the local dev backend (`pnpm dev:backend`, auto-reload), which points at the real `config.yaml`/live HA instance: `data/recorder_state.json` gained `battery_charge_total`/`battery_discharge_total` on the first cycle after the code change, `data/darkstar.log` shows a clean "Recording observation" line with no meter-reset or missing-sensor warnings for either key, and the new `slot_observations` row (2026-07-19T15:15:00) has a non-round `batt_charge_kwh` (0.1477) confirming the cumulative-delta path (not the `power*0.25` snapshot) was used.
- [ ] 4.2 After at least a few hours of live data, re-run the SoC-delta-vs-recorded-energy check used during the original investigation and confirm the daily dropout rate has dropped back toward the pre-spike baseline (~2-5%/month, not the 07-18 75% spike).
- [ ] 4.3 Confirm the `energy_balance` runtime invariant monitor is no longer reporting violations once enough post-deploy slots have accumulated (24h window).
