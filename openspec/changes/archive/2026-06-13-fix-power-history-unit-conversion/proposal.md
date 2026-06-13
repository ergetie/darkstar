## Why

Water-heater (and, when enabled, EV-charger) energy per 15-minute slot is computed by integrating a power sensor's HA history via `get_energy_from_power_history()`. That function converts each state's power to kW using `normalize_kw()`, which only divides by 1000 when the state carries `unit_of_measurement == "W"`. But the HA `/api/history/period` API attaches `unit_of_measurement` **only to the first state** in the series — every later state has `unit=None`. So all states after the first are treated as kilowatts instead of watts, inflating the integrated energy by ~1000×. The values then trip the recorder's spike guard (4 kWh threshold) and are silently zeroed, so `water_kwh` has been under-recorded for months (verified: across 21,386 observations, 0 exceed 4 kWh and the max stored value is 0.808 kWh). The identical HA-history quirk was already fixed for `get_load_profile_from_ha` (see the existing "Unit Propagation in History Processing" requirement) — this change closes the same gap in the power-history path.

## What Changes

- Fix `get_energy_from_power_history()` in `backend/core/ha_client.py` so the `unit_of_measurement` from the first history state is propagated to all subsequent states that lack attributes, matching the behaviour already required for `get_load_profile_from_ha`.
- Apply the propagated unit consistently when normalizing every state's power to kW (W → ÷1000, MW → ×1000), instead of per-state unit lookup.
- Handle the "no unit anywhere in the series" case explicitly (treat values as already in kW, the documented current default) and the "unit changes mid-series" case (adopt the new unit onward).
- This fixes both water-heater and EV-charger slot energy, since both flow through the same function.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `energy-recording`: Extend the unit-handling requirements so that power-based history integration (`get_energy_from_power_history`), not just cumulative-energy history (`get_load_profile_from_ha`), propagates the first-state `unit_of_measurement` across the whole series. Add scenarios covering the water-heater/EV power-sensor case where HA returns the unit only on the first state.

## Impact

- **Code**: `backend/core/ha_client.py` — `get_energy_from_power_history()` and its inner `normalize_kw()` helper.
- **Consumers**: `backend/recorder.py` water-heater energy (`water_kwh`) and EV-charger energy (`ev_charging_kwh`) recording. No schema or API change.
- **Data**: Going forward, `water_kwh` (and EV energy when a charger is enabled) will be recorded at the correct magnitude instead of being zeroed by the spike guard. Existing historical rows are not rewritten by this change.
- **Behaviour**: No config changes required. The spike guard remains as a safety net.
