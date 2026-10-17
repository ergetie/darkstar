# Design

## Context

`backfill_missing_prices` reads 30 days of observations via `LearningStore.get_history_range`. That query selects `import_price_sek_kwh` but not `export_price_sek_kwh`, although the column exists. The loop sets `obs["export_price_sek_kwh"]` only on patched rows. The `rows_to_update` comprehension covers every row with a non-null import price and indexes `obs["export_price_sek_kwh"]`, so any unpatched priced row raises `KeyError`. The outer `except` logs and swallows it, so nothing is stored. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**
- Gap slots get import and export prices in mixed windows.
- Only patched slots are written.

**Non-Goals:**
- No change to price fetching, fee or VAT semantics, or the schema.
- No change to how the learning backfill creates gap rows.

## Decisions

1. **Select the export price in `get_history_range`.** Rows then carry both price keys, so the read is consistent with the table. Alternative: use `obs.get(...)` in the recorder. That only hides the missing column and would make a patched row's existing export price look absent.
2. **Build `rows_to_update` from patched rows only.** Collect each patched slot in the loop, so the write set is exactly what changed. Alternative: keep the filter and guard the key. That rewrites unchanged rows and would send export prices that overwrite stored ones.
3. **Never overwrite.** Patching applies only when the import price is null. `store_slot_prices` is an upsert where new non-null values win over stored ones (it does not preserve existing values), so it is not a safeguard. The recorder therefore sends `export_price_sek_kwh=None` for a patched slot that already has an export price, which leaves that price unchanged. A slot with a missing import price but an existing export price keeps its export price; Nordpool's export price is used only when the slot has none. Covered by a test.
4. **Send `slot_end` with each patched row.** `slot_end` is NOT NULL, and SQLite checks it on the insert half of the upsert even when the row exists, so patched rows carry the observation's `slot_end`.
5. **Keep failure handling.** The broad `except` stays, so the recorder loop is not killed by a backfill error.

## Risks / Trade-offs

- [Extra column in `get_history_range` affects other callers] -> Additive key in the dict; grep callers and run the existing tests.
- [Swallowed exceptions hide future regressions] -> The new tests assert stored rows, not just the absence of a raise.
