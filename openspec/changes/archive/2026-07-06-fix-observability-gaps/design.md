## Context

This change lands five fixes from the `stabilization-review-2` findings ledger, all in the "the system failed but nobody could see it" class:

- **#24** (S2, top priority): failed executor `ActionResult`s reach only `self.recent_errors` (a `maxlen=10` deque) and a WebSocket `executor_error` event (`executor/engine.py:1444-1460`). The phone-push path `dispatcher.notify_error` (`executor/actions.py:1229-1235`, gated on `notifications.on_error`) is wired only to stale-schedule (`engine.py:1108`), EV failure (`engine.py:1343-1352`), and tick exceptions (`engine.py:1531-1532`). Persistent command rejection is silent unless the dashboard is open.
- **#3** (S4): `execution_log.error_message` is NULL for all 2,536 historical failures. The DB layer already writes it (`executor/history.py:133` sets `error_message=record.error_message`), but `_create_execution_record` (`executor/engine.py:1819-1885`) never sets it, so it defaults to `None`.
- **#18** (S3): the dashboard socket (`frontend/src/lib/socket.ts`, socket.io-client v4 Manager API) gives up after `reconnectionAttempts: 10`, never refetches state on reconnect, and exposes no connection state — a frozen tab looks live.
- **#9** (S2): `data_quality_daily` has been dead since 2025-11-28 (backfill era); no live writer/reader. The `stabilization-review-2` runtime invariant monitors are its replacement, but have no UI.
- **#8** (S2, historical): `slot_observations.quality_flags` is written by the recorder but never used to filter training data, so flagged-bad periods still train the models.

Constraints: feature freeze (fixes only), operator is not a coder, prod is single-writer SQLite (WAL) with Alembic migrations, existing notification/dedup pattern is one-shot flags on the engine (no shared dedup util).

## Goals / Non-Goals

**Goals:**
- Repeated command failures reach the operator's phone, deduped so one streak = one notification.
- Every failed tick row carries a readable `error_message`.
- The dashboard survives backend restarts / network blips and visibly signals staleness.
- The dead data-quality table is removed; the live monitors are viewable in the UI.
- Flagged-bad slots are excluded from ML training without touching stored data.

**Non-Goals:**
- No change to what the monitors compute (shipped in `stabilization-review-2`); this only surfaces them.
- No one-off re-flagging of the January 2026 rows (operator decision #8: leave data as-is; only add the filter).
- No new user-facing config keys; reuse `notifications.on_error`.
- No redesign of the notification transport or the socket architecture — minimal, pattern-matching edits.

## Decisions

### 1. Failure-streak notification mirrors the EV-failure one-shot pattern (#24)
Add per-action-type streak state on `ExecutorEngine`, mirroring `_ev_zero_power_ticks` / `_ev_failure_notified` (`engine.py:207-208`):
- `self._action_fail_counts: dict[str, int]` and `self._action_fail_notified: set[str]` (or a single dict of small state objects), initialized in `__init__`.
- In the existing failed-result loop (`engine.py:1444-1460`), increment the counter for each `not r.success and not r.skipped` result keyed by `r.action_type`; when a counter reaches the threshold and the type is not yet in the notified set, `await self.dispatcher.notify_error(...)` and add it to the set.
- Reset a type's counter and notified-flag whenever it produces a `success`/`skipped` result on a later tick (mirrors the EV reset at `engine.py:1368-1369`).
- **Threshold:** default 3 consecutive ticks (a small constant; EV uses 5 for its noisier zero-power signal). Command rejections are deterministic, so 3 balances "not a one-off blip" against "operator hears within ~3 min". Chosen over notifying on the very first failure (too noisy — 404s during HA restarts self-heal next tick per finding #7.6).
- **Dedup granularity:** per `action_type` string (free-form, `ActionResult.action_type`, `actions.py:178`). Alternative considered: dedup per (type, message) — rejected as over-granular; a flapping message would re-notify.

### 2. `error_message` summarized at write time from `action_results` (#3)
In `_create_execution_record` (`engine.py:1819-1885`), when aggregate `success == False`, build a short summary string from the failed entries (the same `not r.success` filter already used at `engine.py:1445`) — e.g. `"; ".join(f"{r.action_type}: {r.message}")` truncated to a sane length — and pass it as `error_message=` to `ExecutionRecord`. Successful ticks pass `None`. No schema change (column exists, `models.py:325`; writer exists, `history.py:133`).

### 3. Socket: Manager-level reconnect config + a subscribable connection signal (#18)
socket.io-client v4, Manager API (`socket.ts:58-66`):
- Set `reconnectionAttempts: Infinity` on the Manager; keep `reconnectionDelayMax: 5000` so backoff stays bounded.
- Add a module-level connection-state store in `socket.ts` and a companion `useSocketStatus()` hook in `lib/hooks.ts` (mirrors how `useSocket` already wraps `getSocket`). Update it from the `connect`/`disconnect`/`reconnect_attempt` handlers (currently console-only, `socket.ts:113-130`).
- On `connect` (and reconnect), invoke a refetch. Implementation: expose the connection signal and let `Dashboard.tsx` call its existing `fetchAllData` (`Dashboard.tsx:419`, already reused by manual refresh at :661/:692/:728) in a `useEffect` keyed on the connection signal transitioning to connected. Avoids threading a callback into `socket.ts`.
- Indicator: a small live/stale dot/badge mirroring `components/ui/Banner.tsx` `Badge`, placed near the dashboard header. `SystemAlert.tsx` is the precedent for an app-level status element.

### 4. Drop `data_quality_daily` via Alembic migration (#9)
New Alembic revision with `op.drop_table('data_quality_daily')` in `upgrade()` and a recreate in `downgrade()` (copy the columns from the current `DataQualityDaily` model before deleting it). Remove the `DataQualityDaily` model from `backend/learning/models.py`. Verify zero remaining references by grep (only the model + alembic baseline reference it today per #9). Downgrade recreates an empty table (historical rows are not restored — acceptable; they were backfill-era).

### 5. Monitor UI panel is a read-only fetch of the existing endpoint (#9)
`GET /api/system/monitors` already exists (shipped in `stabilization-review-2`, `backend/api/routers/system.py`). Add a read-only React panel that fetches it and renders per-invariant status + active episodes + monitor health, mirroring an existing status-card component. Placement: the Aurora tab or Settings→Debug (operator approved either). Graceful error/empty state on fetch failure.

### 6. Training filter is a query-level WHERE on `quality_flags` (#8)
Add the exclusion at the training data-loading query only. No data mutation, no migration. The exclusion set is the flag literal(s) meaning "exclude" (confirmed values from the recorder/model). Rows with NULL or benign flags are unaffected.

## Risks / Trade-offs

- **[Notification spam if the threshold is too low]** → default threshold 3 consecutive ticks + one-shot dedup per action type + reset-on-success; respects `notifications.on_error`.
- **[`error_message` summary too long for the column]** → truncate the summary to a bounded length; column is `Text` so no hard limit, but keep it phone/log-readable.
- **[`reconnectionAttempts: Infinity` causes a reconnect storm against a truly dead backend]** → `reconnectionDelayMax` caps backoff at 5 s; the socket only reconnects, it does not poll extra endpoints.
- **[Refetch-on-reconnect double-fetches on the initial connect]** → key the effect so the mount fetch and the first connect don't both fire (guard with a "was previously disconnected" flag).
- **[Migration downgrade loses historical data_quality_daily rows]** → acceptable per #9 (backfill-era only, superseded by monitors); documented in the migration.
- **[Training filter accidentally excludes too much]** → only the explicit exclusion-flag literal is filtered; unflagged/NULL rows (the vast majority) are untouched; add a test asserting an unflagged row is still included.

## Migration Plan

1. Backend fixes (#24, #3) — no schema change; ship with tests.
2. Alembic migration to drop `data_quality_daily` (#9) — reversible; runs on app start per existing migration flow.
3. Frontend (#18 socket resilience, #9 monitor panel) — no backend dependency beyond the already-shipped endpoint.
4. Training filter (#8) — query-only.
5. Rollback: revert the code; run the Alembic downgrade to recreate the (empty) table if needed.

## Open Questions

- Monitor panel placement: **Aurora tab vs Settings→Debug** — operator approved either; implementer picks whichever fits the existing tab structure with least friction (to be confirmed against the frontend map).
- Exact `quality_flags` exclusion literal(s) — to be confirmed from the recorder/model definition before writing the filter.
