## 1. Implement overwrite-on-save in `_persist_forecasts`

- [x] 1.1 In `ml/price_forecast.py`, update `_persist_forecasts()` to collect the distinct `(slot_start, days_ahead)` pairs present in the incoming `forecasts` batch.
- [x] 1.2 Before inserting, bulk-delete existing `price_forecasts` rows matching those pairs (SQLAlchemy `tuple_(PriceForecast.slot_start, PriceForecast.days_ahead).in_(pairs)`), then add the new rows — all within a single transaction.
- [x] 1.3 Add rollback-on-exception around the delete+insert (keep the existing `try/except`, call `session.rollback()` before logging, and ensure `session.close()` in a `finally`).
- [x] 1.4 Leave `cleanup_price_forecast_duplicates()` and its startup call (`backend/main.py`) untouched (retained as backstop).

## 2. Tests

- [x] 2.1 Add a test: persisting a batch twice for the same `(slot_start, days_ahead)` pairs (different `issue_timestamp`) leaves exactly one row per pair, holding the later run's `issue_timestamp` and values.
- [x] 2.2 Add a test: persisting forecasts for the same `slot_start` but different `days_ahead` (simulating successive days) keeps both rows (overwrite must not collapse distinct horizons).
- [x] 2.3 Add a test: a weather-only batch (null spot columns) overwrites a prior row for the same pair and stores null spot columns.
- [x] 2.4 Verify SQLite row-value tuple `IN` works in the test environment; if not, switch task 1.2 to per-pair deletes within the transaction and keep the tests green.

## 3. Verify

- [x] 3.1 Run the price-forecast test suite and full lint/type checks (`scripts/ci_local.sh` or project equivalent).
- [x] 3.2 Manually (or via test) confirm: two consecutive `generate_price_forecasts()` runs produce no growth in row count for the overlapping `(slot_start, days_ahead)` pairs.
