## Why

`PlannerService` stores its retry timestamps as naive local datetimes (CEST), while `SchedulerService` works in UTC and bridges the two with `.replace(tzinfo=UTC)`. That coercion reinterprets a local wall time as a UTC instant, pushing every retry exactly one UTC-offset into the future — 2 hours in summer, 1 hour in winter. Because a config save calls `clear_retry_suspension()` ("retry immediately"), **saving settings freezes automatic planning for 2 hours**, and a failed planner run's 60-second backoff becomes a 2-hour outage. The scheduler skips silently, so nothing in the logs says planning has stopped; the only visible symptom is the executor emitting `Schedule is stale — holding` and freezing its inverter mode.

Observed in production on 2026-09-17: 37 planner runs instead of the usual 46, with four gaps of 124/58/124/134 minutes. Each gap begins at a config save, and the gap ending at `19:27:24` follows the `17:27:18` save by exactly 2 hours to the second. The six other retained log days contain no config saves and no gaps.

## What Changes

- Convert all `PlannerService` retry/error timestamps (`_next_retry_at`, `_last_error_at`, and the run-duration and progress timestamps) to timezone-aware UTC, and delete the `.replace(tzinfo=UTC)` coercions in `SchedulerService`. One representation end to end, so the mismatch cannot recur.
- Keep `retry_in_s` correct. It currently compares naive-to-naive and so reads right while the scheduler is 2 hours off — after the change both agree, rather than only the UI being believable.
- Reclassify Home Assistant connectivity failures as transient. A SoC read that fails because HA is unreachable must back off and recover on its own instead of being treated as a configuration problem the user has to fix.
- Add a suspension safety net: the planner SHALL NOT remain suspended indefinitely. After a bounded period it retries anyway and raises a health issue, so a suspension can never become a silent permanent stall.
- Log every scheduler skip with its reason. The skip branches are currently silent, which is why hours of no planning looked like a healthy system.
- Add a regression guard test that fails CI on naive `datetime.now()` in the planner/scheduler retry path, mirroring the existing `dst-safe-time` guard.

No breaking changes. All of this is internal scheduling behavior; the `/api/health` contract and the `retry_in_s` field are unchanged.

## Capabilities

### New Capabilities

None. This corrects behavior already specified by `planner-diagnostics` and extends an existing guard.

### Modified Capabilities

- `planner-diagnostics`: The retry policy requirements gain an explicit timezone contract — retry timestamps are timezone-aware UTC, and "schedule an immediate retry" must mean the next scheduler tick regardless of the host's UTC offset. HA-connectivity failures move from config-blocking to transient, suspension gains a bounded ceiling with a health issue, and skipped scheduler cycles must be logged with a reason.
- `dst-safe-time`: The regression guard requirement extends to cover naive `datetime.now()` in scheduling and retry code, not just `pd.date_range`/`tz_localize`.

## Impact

**Code**
- `backend/services/planner_service.py` — lines 88, 92, 102, 105, 110 set or compare naive datetimes; also 118, 126, 140, 168, 173, 202, 221, 229, 246, 254.
- `backend/services/scheduler_service.py` — the naive→UTC bridges at lines 151 and 205, and the silent skip branches at lines 144–161.
- `planner/errors.py` — `is_config_blocking` / `is_transient` membership, and a code for HA connectivity failures.
- `backend/api/routers/config.py:354` — the `clear_retry_suspension()` call site; behavior is unchanged, but it is the main trigger of the bug.
- Tests: `tests/services/test_planner_retry_policy.py`, `tests/services/test_retry_policy_e2e.py`, plus a new regression guard.

**Systems**
- Planner scheduling cadence and the executor's stale-schedule holding behavior. No database, config, or API migration.

**Risk**
- The retry path is the planner's failure-recovery mechanism; a mistake here degrades recovery rather than normal operation. Tests must cover a non-UTC host offset explicitly, since every bug in this class is invisible when the host runs UTC.

**Out of scope** — found during the same investigation, tracked separately:
- `Failed to load schedule: Expecting ':' delimiter` (2026-09-14) — non-atomic `schedule.json` write.
- `sqlite3.OperationalError: database is locked` during overlapping planner runs (2026-09-17 22:15).
