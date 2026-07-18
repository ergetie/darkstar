# Design: s-index-history-persistence

## Context

Every planner run computes an S-Index debug record (~1.1 KB JSON: safety floor inputs, price addon, risk parameters) and attaches it to the schedule output as `meta.s_index` in `schedule.json` — overwritten each run. The only history is `strategy_history.json` (capped at 100 entries, events ≥ 0.5 kWh addon only). Legacy DB sinks are dead: `strategy_log` has no writer left in the codebase; `planner_debug` writes are gated behind `enable_planner_debug`, off in production since Dec 2025 (and its payload is the full debug dump — far larger than needed).

Prod reality (measured 2026-07-17): 46 planner runs/day, 1,125 bytes per record → ~50 KB/day, ~19 MB/year.

An established pattern exists for non-fatal async DB writes from the planner: `planner/observability/logging.py::record_debug_payload` (async session via `get_learning_engine().store`, warn-and-continue on failure).

## Goals / Non-Goals

**Goals:**
- One durable row per planner run containing the S-Index debug record, on all installs, no config toggle.
- Bounded storage via 365-day retention.
- Zero impact on planner reliability — persistence failure must never fail a run.

**Non-Goals:**
- No UI/API surfacing of the history (possible follow-up).
- No change to how the S-Index is calculated or to `schedule.json` / `strategy_history.json` behavior.
- No backfill of historical data (replay reconstruction covers past analysis needs).
- No removal of the dead `strategy_log` table (avoid destructive migration in this change; can be dropped in a later cleanup).
- No remote/call-home data collection (tracked as a separate backlog idea).

## Decisions

1. **New dedicated table `s_index_history`** with columns `id` (PK autoincrement), `created_at` (ISO-8601 UTC string, indexed), `payload` (TEXT, JSON of the s_index debug dict).
   - *Why not reuse `planner_debug`?* Its payload is the full planner debug dump (windows, sample schedule — tens of KB) gated behind a debug flag; we want a small always-on record. Mixing "always-on compact" with "opt-in verbose" in one table couples retention and query patterns.
   - *Why JSON payload instead of typed columns?* The debug dict's shape varies by S-Index mode (`physical_deficit`, probabilistic, dynamic) and evolves with tuning work; a JSON column tolerates that without migrations. Calibration queries load rows into Python/pandas anyway. `created_at` is the only field that needs indexing.

2. **Write hook in `planner/output/schedule.py`** alongside the existing `generate_debug_payload` call site, implemented as `record_s_index_history(...)` in `planner/observability/logging.py` following the `record_debug_payload` pattern (async session, warn-and-continue). One row per successful schedule generation — the same cadence at which `meta.s_index` is produced.
   - *Why not in `s_index.py` itself?* The calculation functions are pure and also run in tests/replays; persistence belongs at the output boundary where "a real planner run happened" is known.

3. **Retention pruning inline in the write path**: after inserting, `DELETE FROM s_index_history WHERE created_at < now - 365 days`. At 46 rows/day the delete scans an indexed range and is trivially cheap; no separate scheduled job to build or monitor.

4. **Always on, no config key.** ~19 MB/year steady state does not justify a toggle; toggles multiply test surface and this record has diagnostic value on every install.

5. **Unlike `record_debug_payload`, the write is NOT gated on `learning_config["enable"]`** — the record must exist on installs that have learning disabled too. It still degrades to a no-op (with a debug log) if the learning engine/store is unavailable, since the table lives in `planner_learning.db`.

## Risks / Trade-offs

- [Clock skew / non-UTC timestamps break retention comparison] → store `created_at` as ISO-8601 UTC (same convention as `planner_debug`); compute the cutoff in UTC.
- [Write adds latency to every planner run] → async single-row insert + indexed delete, following an already-proven pattern; failure path is warn-and-continue.
- [Payload schema drift makes old rows heterogeneous] → accepted; consumers are ad-hoc calibration queries that must tolerate missing keys. The alternative (typed columns) trades this for recurring migrations.
- [`planner_learning.db` WAL contention with concurrent learning writes] → single small transaction per run; same exposure `record_debug_payload` already has, no new locking pattern.

## Migration Plan

1. Alembic migration adds `s_index_history` (table + index on `created_at`). Additive only — safe on existing installs; `scripts/dev-backend.sh` migrates dev automatically, prod migrates on next deploy's `alembic upgrade head`.
2. Rollback = downgrade drops the table; no other code depends on it.

## Open Questions

None — sizing, cadence, and write location were verified against production on 2026-07-17.
