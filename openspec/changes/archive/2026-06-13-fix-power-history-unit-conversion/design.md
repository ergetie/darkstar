## Context

`get_energy_from_power_history(entity_id, start, end)` in `backend/core/ha_client.py` fetches a power sensor's HA history for a 15-minute slot and step-integrates power over time to produce energy in kWh. Its inner helper `normalize_kw(value, state)` reads `state["attributes"]["unit_of_measurement"]` per state and divides by 1000 for `"W"`, multiplies by 1000 for `"MW"`, else returns the value unchanged (assumed kW).

The HA `/api/history/period` endpoint only includes the `attributes` object (and therefore `unit_of_measurement`) on the **first** state of each entity's series; subsequent states omit it. So `normalize_kw` sees `unit=None` for every state after the first and treats raw watts as kilowatts — a ~1000× inflation. Verified live: for `sensor.vvb_power` the first state was `3164 W (unit='W')` and the next three were `3124 / 3147 / 0 (unit=None)`, reproducing the logged 17.42 kWh spike exactly.

The same HA quirk was already solved in the sibling function `get_load_profile_from_ha` (same file, ~lines 493–516) using a `cached_unit` variable: it remembers the last non-empty unit and applies it to states that lack one. The existing `energy-recording` spec encodes this as the "Unit Propagation in History Processing" requirement. This change brings `get_energy_from_power_history` to parity.

## Goals / Non-Goals

**Goals:**
- `get_energy_from_power_history` propagates the first state's `unit_of_measurement` to all later states that lack it, so the W→kW conversion is applied consistently across the whole series.
- Correctly handle: unit on first state only (the common case), no unit anywhere in the series, and a unit that changes mid-series.
- Fix both water-heater (`water_kwh`) and EV-charger (`ev_charging_kwh`) energy, which share this function.

**Non-Goals:**
- No backfill/rewrite of historical `slot_observations` rows.
- No change to the recorder's spike guard (it stays as a safety net).
- No change to `get_load_profile_from_ha` or `_normalize_energy_to_kwh` (already correct).
- No config or DB schema changes.

## Decisions

**Decision: Mirror the `cached_unit` pattern from `get_load_profile_from_ha`.**
Track the last seen non-empty `unit_of_measurement` while iterating states; when a state has no unit, reuse the cached one. Pass the resolved unit into the kW conversion rather than reading it per-state inside `normalize_kw`.
- *Why:* Proven, already-shipped pattern in the same file; minimal surface area; consistent with the documented spec requirement.
- *Alternative considered:* Fetch the sensor's current unit via `/api/states` and use it for the whole series. Rejected — extra network call per slot, and the first history state already carries the unit reliably.
- *Alternative considered:* Magnitude heuristic (assume W if value > some threshold). Rejected for power — a 3000 W heater and a 3 kW reading are both plausible; magnitude can't disambiguate safely.

**Decision: Resolve unit ordering before integrating.**
States are already sorted by timestamp before the integration loop. The cached-unit resolution must happen in that same sorted order so the first chronological state's unit seeds the cache.

**Decision: No-unit-anywhere default stays "assume kW".**
If no state in the series carries a unit, keep current behavior (treat values as kW). This preserves backward compatibility for sensors genuinely reporting kW without a unit attribute. Document it explicitly in the spec.

## Risks / Trade-offs

- [A sensor that legitimately reports in W but never sends a unit attribute would still be misread as kW] → Acceptable: matches today's documented default; the spike guard still catches gross errors. Out of scope to auto-detect.
- [Mid-series unit change handled by adopting the new unit onward] → Matches the existing load-profile requirement; low real-world likelihood but specified for consistency.
- [Historical zeroed water data remains wrong] → By design; this fix is forward-looking only. A separate backfill could be proposed later if needed.
