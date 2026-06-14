## Why

Every price-forecast generation run (daily at 06:00 **and** after each ML training cycle) appends a fresh full set of `price_forecasts` rows tagged with a new `issue_timestamp`, instead of replacing the prior forecast for the same slot. Duplicates accumulate unbounded between restarts (observed: 6382 rows pruned on one boot, 679 in a 22-minute window) and are only cleaned up at startup. While duplicates exist they also skew the daily price-outlook averages, which average across every duplicate of a slot. Fixing the write path so each forecast overwrites its predecessor removes the accumulation at the source.

## What Changes

- Change the price-forecast persistence path so that writing a forecast for a `(slot_start, days_ahead)` pair **replaces** any existing row for that pair instead of inserting an additional row. After any generation run, at most one row SHALL exist per `(slot_start, days_ahead)`.
- Keep the existing startup duplicate-cleanup (`cleanup_price_forecast_duplicates`) in place as a backstop / legacy-data sweep — it becomes a no-op once the write path stops creating duplicates, but is retained intentionally.
- No database schema change: no new UNIQUE constraint and no data migration. The fix is application-level (single-writer system; the startup cleanup is the safety net).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `price-forecasting`: The "Price forecast persistence" requirement changes from append-only writes to overwrite-on-save keyed on `(slot_start, days_ahead)`, so generation runs no longer accumulate duplicate rows.

## Impact

- **Code:** `ml/price_forecast.py` — the persistence helper (`_persist_forecasts`) and its callers in `generate_price_forecasts()`. The startup cleanup call (`backend/main.py`) and `cleanup_price_forecast_duplicates()` are unchanged.
- **Data:** No migration. Existing duplicates continue to be handled by the read-side dedup and the startup cleanup; the new write path simply stops creating more.
- **Behavior:** Daily price-outlook averages (`backend/core/price_outlook.py`) become accurate (no double-counting) once duplicates stop accruing. All existing readers already tolerate/dedup duplicates, so none break.
- **Constraints:** Single-writer assumption — only the scheduler/training pipeline writes `price_forecasts`. No DB-level uniqueness guarantee is added; correctness relies on the write path plus the retained startup cleanup.
