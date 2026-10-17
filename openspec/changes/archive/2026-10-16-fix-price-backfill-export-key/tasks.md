## 1. Read path

- [x] 1.1 Select `SlotObservation.export_price_sek_kwh` in `LearningStore.get_history_range` (`backend/learning/store.py`). Add a store test that a stored export price is returned by `get_history_range`. Verify: `UV_NO_SYNC=1 uv run python -m pytest tests/<store test file> -v` passes, and callers of `get_history_range` are checked with grep and their tests still pass.

## 2. Backfill fix

- [x] 2.1 In `backfill_missing_prices` (`backend/recorder.py`), collect patched slots and build `rows_to_update` only from them (each row carries `slot_start`, `slot_end` (NOT NULL on the upsert insert path), the import price, and the export price, or None when the slot already has one). Drop the all-priced-rows comprehension. Verify: new tests in `tests/recorder/` for a window mixing priced and gap rows, which fails on the old code with KeyError and passes now, and asserts both import and raw-spot export prices are stored for the gap slots.
- [x] 2.2 Add tests for the no-overwrite rule (existing prices unchanged), a gap slot with no Nordpool price staying unpriced while others are filled, and idempotence (second run finds nothing missing and writes nothing). Verify: `UV_NO_SYNC=1 uv run python -m pytest tests/recorder -v` passes.

## 3. Final checks

- [x] 3.1 Run `./scripts/lint.sh` and fix all findings. Verify: it exits 0.
