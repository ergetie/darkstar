## Why

The live Power Flow card uses the gross whole-home power sensor for House while also showing EV and water-heater power as separate loads, so the displayed demand is double-counted. The Energy Resources card also compares stored base-load consumption with an average derived from the gross sensor, making its comparison inconsistent.

## What Changes

- Derive the Power Flow House value from gross load after removing separately displayed EV and water-heater consumption.
- Add `base_load_avg_daily_kwh` to `GET /api/energy/today`: the base-load total of the last 96 completed 15-minute slots, or `null` when fewer than 87 of them are recorded.
- Use that field for the Energy Resources House Load average instead of the gross-sensor `/api/ha/average` value.
- Keep the gross whole-home meter reading available as total load; do not change its meaning globally.

## Capabilities

### New Capabilities
- `powerflow-house-load`: Defines the residual House load shown when controllable loads are displayed separately.

### Modified Capabilities
- `dashboard-ev-display`: Requires the House Load actual and comparison values to use a consistent base-load definition.

## Impact

- Backend: `backend/api/routers/energy.py` (`get_energy_today` gains one nullable field).
- Frontend: `frontend/src/pages/Dashboard.tsx`, a new pure helper beside `frontend/src/components/PowerFlowRegistry.ts`, and the energy-today API type.
- `/api/ha/average` is unchanged and remains available for other callers.
- No database schema, migration, or dependency changes.
