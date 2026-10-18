## Why

A Tesla `energy_added_sensor` drifts down ~0.11 kWh every 45-60 min while the car is idle (22.47, 22.36, 22.25 ...). The recorder treats every drop as a session reset and books the whole post-drop value (~22 kWh) as car energy, so the EV card showed "Delivered Today" 90.7 kWh at 08:55 and 176.5 kWh at 14:30 with the wallbox at ~7.5e-05 kWh per slot (user torleif, diagnostics 2.7.1-beta). The car value wins over wallbox energy in the delivered-today query, and the card's progress bar divides it by a SoC-delta requirement, giving "100% of goal" with 13.9 kWh remaining.

## What Changes

- Sensor drops count as a session reset only when the new value is near zero (configurable threshold); other drops contribute 0. No plug-in signal is used (the recorder has none).
- Per-slot car energy is capped by wallbox energy (plus tolerance) and is 0 when the wallbox is ~0.
- Car energy is zeroed whenever the aggregate EV energy is rejected, like the per-charger wallbox energy.
- Progress bar and percent derive from SoC relative to the target SoC (`soc / target_soc` with SoC; delivered / required kWh without a SoC sensor; no persisted goal-start SoC, no schema change); "Delivered Today" becomes informational only.
- Tests use torleif's real sequence.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `ev-charging-losses`: car-side energy recording rules (reset detection, wallbox cap, rejected aggregates).
- `ev-dashboard-card`: progress is SoC-based; delivered today informational.

## Impact

- `backend/recorder.py` (`car_energy_from_added_sensor` ~79-88, `_ev_car_energy` ~137-166, rejected-aggregate handling ~583-584)
- `planner/pipeline.py` (`_ev_delivered_today_kwh` ~71-110)
- `frontend/src/components/EVChargingCard.tsx` (~57-63, ~301, ~529-560), `frontend/src/lib/api.ts` (~1317-1330)
- `config.default.yaml`: one new optional per-charger key. Existing bad rows in `ev_charger_observations` are not migrated; the delivered-today query also caps defensively. No DB schema change.
