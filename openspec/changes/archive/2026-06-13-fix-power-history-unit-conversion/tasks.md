## 1. Fix unit propagation in power-history integration

- [x] 1.1 In `backend/core/ha_client.py`, add a `cached_unit` variable in `get_energy_from_power_history` that tracks the last non-empty `unit_of_measurement` while iterating the sorted states (mirror the pattern in `get_load_profile_from_ha`, ~lines 493/511–516).
- [x] 1.2 Update `normalize_kw` (or its call sites) to use the resolved/cached unit instead of reading `unit_of_measurement` only from the current state, so states lacking attributes inherit the first state's unit.
- [x] 1.3 Ensure the cached-unit resolution runs in chronological (sorted) order so the first state's unit seeds the cache before any energy is integrated.
- [x] 1.4 Preserve the existing conversions: `"W"` → ÷1000, `"MW"` → ×1000, `"kW"`/other/None-everywhere → value used as-is (assume kW). Adopt a new unit mid-series if one appears.

## 2. Tests

- [x] 2.1 Add a unit test for `get_energy_from_power_history` where only the first state carries `unit_of_measurement: "W"` and later states have `{}`; assert all values are divided by 1000 and the integrated energy is ~0.78 kWh (not ~780 kWh). Reproduce the real `sensor.vvb_power` series (3164/3124/3147/0).
- [x] 2.2 Add a test for "no unit anywhere in the series" asserting values are treated as kW (no division).
- [x] 2.3 Add a test for a mid-series unit change (`"W"` → `"kW"`) asserting the new unit is adopted from that entry onward.
- [x] 2.4 Add/extend a recorder-level test (or assertion) confirming a ~3 kW heater over a full slot records ~0.75 kWh and is no longer zeroed by the spike guard.

## 3. Verify

- [x] 3.1 Run the backend test suite / `scripts/ci_local.sh` and confirm green.
- [x] 3.2 Sanity-check against live HA history for `sensor.vvb_power` (e.g. run the function for a recent heater-on slot) and confirm the result is in the ~0.1–0.8 kWh range, not a thousands-scale spike.
- [x] 3.3 Update `docs/BACKLOG.md` — remove the `[Recorder] Water-Heater Energy 1000× Unit Inflation` inbox item now that it is tracked by this change.
