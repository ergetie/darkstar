## 1. Backend

- [x] 1.1 In `get_energy_range` (`backend/api/routers/energy.py`) append four `case()`-based sums to the aggregate select (spot numerator/denominator on `export_price_sek_kwh`, all-in numerator/denominator on `import_price_sek_kwh`), each filtered by `import_kwh > 0` and price NOT NULL; add a comment that `export_price_sek_kwh` is the pure spot price
- [x] 1.2 Compute both averages in Python (`None` when denominator is missing or not > 0), round to 4 decimals, add `avg_import_spot_sek_kwh` and `avg_import_price_sek_kwh` to the response dict and as `None` to the fallback dict
- [x] 1.3 Confirm existing fields and row indices are unchanged and fixed fees are not used in the averages

## 2. Frontend

- [x] 2.1 Extend the `rangeData` state type and mapping in `CommandDomains.tsx` with the two nullable fields (`?? null`); update the API response type in `frontend/src/lib/api.ts` if declared there
- [x] 2.2 Reuse `formatPrice` from `ChartCard.logic.ts` (no new helper) and render the two rows with tooltips below the Grid Import block, following `docs/design-system/AI_GUIDELINES.md`

## 3. Tests

- [x] 3.1 Add `tests/api/test_energy_avg_import_prices.py`: kWh weighting vs simple mean, NULL-price exclusion per column, zero price included, zero/NULL import ignored, no import returns null, fixed fees configured do not change averages, fallback dict has nulls; no real webhooks
- [x] 3.2 Extend `frontend/src/components/CommandDomains.test.tsx`: both values rendered, null/absent shows dash with no `NaN`
- [x] 3.3 Run `UV_NO_SYNC=1 uv run python -m pytest tests/api -n auto`, the frontend tests, and `./scripts/lint.sh`
