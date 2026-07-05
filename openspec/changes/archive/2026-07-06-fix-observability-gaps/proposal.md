## Why

The `stabilization-review-2` evidence phase found a cluster of observability gaps: when Darkstar's executor fails to command hardware, the operator is never told (failures reach only an in-memory deque and a WebSocket event, never the phone push the operator enabled), the `execution_log.error_message` column that should record *why* a tick failed is NULL for all 2,536 historical failures, the dashboard silently freezes on a lost WebSocket with no staleness cue, the daily data-quality table has been dead since the backfill era (which is exactly why a 129-slot data-corruption episode went unnoticed), and the new runtime invariant monitors have no UI. These are all "the system failed but nobody could see it" defects — the highest-impact class under the current feature freeze.

## What Changes

- **Push notification on command-failure streaks (#24):** when an executor action (water temp, inverter, EV, etc.) fails repeatedly, send a phone notification via the existing `notify_error` path, honoring `notifications.on_error`, deduped to the first failure of each streak per action type — mirroring the existing EV-charge-failure notification.
- **Populate `execution_log.error_message` (#3):** write a short human-readable failure summary (derived from the per-action `action_results` detail) into the column at log time, so failures carry a top-level reason.
- **Dashboard connection resilience (#18):** reconnect indefinitely instead of giving up after 10 attempts, refetch the full state bundle on reconnect, and show a visible live/stale connection indicator.
- **Drop the dead `data_quality_daily` table (#9)** via migration; the runtime invariant monitors (shipped in `stabilization-review-2`) are its live-era replacement.
- **Monitor status UI panel (#9):** surface `GET /api/system/monitors` (invariant results + active violations + monitor health) in a read-only panel in the UI.
- **Flag-aware ML training (#8):** make the training data loader honor the existing `quality_flags` column so flagged-bad slots (e.g. the January corruption cluster) are excluded from the training set.

## Capabilities

### New Capabilities
- `command-failure-notification`: executor surfaces repeated action-command failures to the operator's notification channel (deduped per action type) and records a top-level failure reason on each `execution_log` row.
- `dashboard-connection-resilience`: the dashboard reconnects indefinitely, refetches state on reconnect, and shows connection liveness so a frozen tab is never mistaken for live data.
- `monitor-status-ui`: the runtime invariant monitors are viewable in the UI; the obsolete `data_quality_daily` table is removed.
- `training-quality-filter`: ML training excludes slots marked bad by `quality_flags`.

### Modified Capabilities
<!-- None: these are additive behaviors; existing specs' requirements are unchanged. -->

## Impact

- **Backend:** `executor/engine.py` (failure-streak tracking + notify + error_message summary), `executor/history.py` (write `error_message`), a new Alembic migration (drop `data_quality_daily`), ML training data loader (`quality_flags` filter). `GET /api/system/monitors` already exists (shipped in `stabilization-review-2`).
- **Frontend:** `frontend/src/lib/socket.ts` (reconnect config + connection-state signal), `Dashboard.tsx` (refetch-on-reconnect + indicator), a new monitor-status panel component.
- **Database:** removal of the `data_quality_daily` table and its `DataQualityDaily` model. No change to `slot_observations` schema (the `quality_flags` column already exists).
- **Config:** honors existing `notifications.on_error`; no new required keys.
- **No breaking changes** to external APIs or user config.
