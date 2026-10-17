## Why

After a data gap, the learning backfill creates slot rows with null prices, and `backfill_missing_prices` is meant to fill them from Nordpool. It raises `KeyError: 'export_price_sek_kwh'` instead, and the broad `except` swallows it. Nothing is stored, so the gap slots stay unpriced. That breaks savings (DS vs grid-only), the daily battery benchmark and learning cost figures for those slots. It was seen in a local dev run after a 2-day gap. Production logs show 0 occurrences in 7 days and 0 null prices in 30 days, so the bug is latent.

## What Changes

- The history range read used by the price backfill returns each slot's export price alongside its import price.
- The price backfill sends only the slots it actually patched to storage. It no longer re-sends every priced row.
- Existing import/export prices are never overwritten by the backfill.
- Backfilled export price keeps its current meaning: raw Nordpool spot, with no fees or VAT.
- Tests cover mixed gap and normal rows, export price storage, and idempotence.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `energy-recording`: adds a requirement for price backfill of unpriced slots (completeness, no overwrite, only patched rows written, failure visibility).

## Impact

- `backend/recorder.py` (`backfill_missing_prices`)
- `backend/learning/store.py` (`get_history_range` column selection)
- New or extended tests under `tests/recorder/`
- No schema change, no new dependency, no config change.
