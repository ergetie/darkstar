# Proposal: s-index-history-persistence

## Why

The S-Index safety-floor calculation (including the Module 3 price addon) produces a rich per-run debug record, but nothing durably persists it: `schedule.json` is overwritten every run, `strategy_history.json` is capped at 100 entries (~4 days at 46 runs/day) and only records addon events ≥ 0.5 kWh, and the legacy `strategy_log` / `planner_debug` DB tables have been dead since December 2025. The pending `RISK_PRICE_KW_FRACTION` calibration session (backlog) had to fall back to reconstructing history by replay because the real record was never kept. At ~1.1 KB per record and 46 planner runs/day, durable persistence costs ~19 MB/year — negligible.

## What Changes

- Add a new `s_index_history` DB table (Alembic migration) storing one row per planner run: timestamp plus the full S-Index debug record (the same dict already written to `schedule.json` `meta.s_index`) as JSON.
- Write a row from the planner pipeline on every successful run, for all installs, with no config toggle. Persistence failures are logged as warnings and never fail the planner run.
- Prune rows older than 365 days as part of the write path, keeping the table bounded (~19 MB steady state).
- No UI in this change; the table is for calibration/diagnostics queries. Surfacing it in the analyst UI is a possible follow-up.

## Capabilities

### New Capabilities

- `s-index-run-history`: Durable per-run persistence of the S-Index debug record (safety floor, price addon, risk inputs) with bounded retention.

### Modified Capabilities

<!-- none — existing S-Index calculation behavior is unchanged; this only adds persistence of its existing debug output -->

## Impact

- **DB:** new `s_index_history` table + Alembic migration (`backend/learning/models.py`, `alembic/versions/`).
- **Planner:** write hook in the pipeline/output path where `s_index_debug` is available (`planner/pipeline.py` / `planner/output/schedule.py`).
- **Storage:** ~50 KB/day, capped at ~19 MB by 365-day retention.
- **Tests:** new tests for write, retention pruning, and non-fatal failure behavior.
- **Backlog:** unblocks future `RISK_PRICE_KW_FRACTION` calibration sessions with real history instead of replay reconstruction.
