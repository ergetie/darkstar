## 1. Base-load average (backend)

- [x] 1.1 In `backend/api/routers/energy.py` `get_energy_today`, add `base_load_avg_daily_kwh`: the sum of `SlotObservation.load_kwh` over the 96 completed 15-minute slots before the current slot start, scaled by `96 / count`, rounded to 2 decimals; `null` when fewer than 87 slots have non-null `load_kwh`. Update the return type annotation to allow `None`.
- [x] 1.2 Add pytest coverage: full window, exactly 87 slots (scaled value), 86 slots (`null`), the in-progress slot excluded, slots older than 24 h excluded.

## 2. Power Flow House value (frontend)

- [x] 2.1 Add a pure `computeHouseKw(grossKw, evKw, waterKw, enabledNodeIds)` helper beside `PowerFlowRegistry.ts`: `max(0, gross - ev - water)`, subtracting EV only when the `ev` node is enabled and water only when the `water` node is enabled; missing values count as 0.
- [x] 2.2 Use the helper for `house.kw` in `Dashboard.tsx`; do not modify `livePower.load_kw`.
- [x] 2.3 Add vitest coverage for the helper: both loads subtracted, EV node disabled, water node disabled, negative residual clamped to 0, missing inputs.

## 3. Energy Resources comparison (frontend)

- [x] 3.1 Add `base_load_avg_daily_kwh: number | null` to the energy-today API type in `frontend/src/lib/api`.
- [x] 3.2 In `Dashboard.tsx`, set the House Load average from `base_load_avg_daily_kwh`; remove the `Api.haAverage()` call and the `avgLoad` state if nothing else uses them.
- [x] 3.3 Pass `null` through when the field is `null`, so the card shows its unavailable value; no `?? 0` fallback.

## 4. Verification

- [x] 4.1 Confirm `load_kw` / `load_power_kw` and `/api/ha/average` responses are unchanged.
- [x] 4.2 Confirm the Dashboard renders correctly with EV disabled, water disabled, and both disabled.
- [x] 4.3 Run the new pytest and vitest tests, then `./scripts/lint.sh`.
