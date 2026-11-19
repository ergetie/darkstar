# Proposal

## Why

The Cost card shows what was paid for grid import but not at what price per kWh. Users cannot tell how well their consumption tracked the market (raw spot) or what a kWh really cost them all-in. Two consumption-weighted averages answer both.

## What Changes

- `GET /api/energy/range` returns two new fields: `avg_import_spot_sek_kwh` (consumption-weighted raw Nordpool spot price of imported energy) and `avg_import_price_sek_kwh` (consumption-weighted all-in import price: grid fees, energy tax, VAT, markups).
- Both are weighted by imported kWh, ignore slots with a NULL price (never as 0), count only slots with `import_kwh > 0`, and are `null` when no kWh qualifies. Fixed fees and subscriptions are never part of either average.
- The Cost card shows both averages per kWh for the selected period, with a dash when `null`.
- No schema, config, dependency or docs changes. Existing response fields are unchanged.

## Capabilities

### New Capabilities
- `cost-card-import-price-averages`: Cost card presentation of the two weighted import-price averages, including the empty state.

### Modified Capabilities
- `energy-totals-api`: `/api/energy/range` gains the two average-price fields with defined weighting, NULL handling and fallback.

## Impact

- `backend/api/routers/energy.py` (`get_energy_range`: aggregate select, response dict, fallback dict).
- `frontend/src/components/CommandDomains.tsx` (range data type, mapping, Cost card render) and `frontend/src/lib/api.ts` if the range response type is declared there.
- Tests: new backend pytest module under `tests/api/`, extended `frontend/src/components/CommandDomains.test.tsx`.
- Independent of the archived `2026-11-08-bill-accurate-costs` change (see design.md).
