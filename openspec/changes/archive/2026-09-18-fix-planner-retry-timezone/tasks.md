All values are decided. Nothing in this plan requires a judgement call — implement it literally.

Constants introduced by this change:

| Constant | Value | Where |
|---|---|---|
| `_SUSPENSION_CEILING_S` | `1800` (30 min) | `backend/services/planner_service.py` |
| `_SKIP_LOG_INTERVAL_S` | `300` (5 min) | `backend/services/scheduler_service.py` |

Line numbers below refer to the state of the files at the start of this change. They shift as you edit, so match on the quoted text, not the number.

## 1. Test harness for non-UTC hosts

Do this group first. Tasks 1.2 and 1.3 MUST fail against current `main`; if they pass, the harness is not forcing a non-UTC zone and the rest of the change is unverifiable.

- [x] 1.1 In `tests/conftest.py`, add a fixture `stockholm_tz` that sets `TZ=Europe/Stockholm`, calls `time.tzset()`, yields, then restores the original `TZ` and calls `time.tzset()` again.
- [x] 1.2 In `tests/services/test_planner_retry_policy.py`, add `test_clear_retry_suspension_is_due_immediately_on_utc_plus_2`: use `stockholm_tz`, call `svc.clear_retry_suspension()`, then assert `svc.next_retry_at <= datetime.now(UTC) + timedelta(seconds=1)`. Run it and confirm it FAILS with the retry time ~2 hours in the future.
- [x] 1.3 In the same file, add `test_transient_backoff_is_60s_on_utc_plus_2`: use `stockholm_tz`, drive one transient failure (`PlannerErrorCode.PRICES_UNAVAILABLE`), assert `55 <= (svc.next_retry_at - datetime.now(UTC)).total_seconds() <= 65`. Run it and confirm it FAILS.

## 2. Convert PlannerService to aware UTC

File: `backend/services/planner_service.py`. Ensure `from datetime import UTC` is imported.

- [x] 2.1 In `retry_in_s` (line 88), change `(self._next_retry_at - datetime.now())` to `(self._next_retry_at - datetime.now(UTC))`.
- [x] 2.2 In `_apply_retry_policy` (line 92), change `now = datetime.now()` to `now = datetime.now(UTC)`. Lines 102 and 105 derive from `now` and need no separate edit.
- [x] 2.3 In `clear_retry_suspension` (line 110), change `self._next_retry_at = datetime.now()` to `self._next_retry_at = datetime.now(UTC)`.
- [x] 2.4 In the `except PlannerError` handler (line 221), change `self._last_error_at = datetime.now()` to `datetime.now(UTC)`.
- [x] 2.5 In the `except Exception` handler (line 246), change `self._last_error_at = datetime.now()` to `datetime.now(UTC)`.
- [x] 2.6 Change `planned_at=datetime.now()` (line 168) to `planned_at=datetime.now(UTC)`.
- [x] 2.7 Change the progress payload `"timestamp": datetime.now().isoformat()` (line 126) to `datetime.now(UTC).isoformat()`.
- [x] 2.8 Leave lines 118, 140, 173, 202, 229 and 254 naive — they are `start`/`_planner_start_time` elapsed-duration pairs and are correct. Add the comment `# naive by design: elapsed-duration only, never crosses a module boundary` above the assignment at line 173 and at line 118.
- [x] 2.9 Run `rg -n "datetime\.now\(\)" backend/services/planner_service.py` and confirm exactly six hits remain, all from task 2.8.

## 3. Remove the scheduler bridge

File: `backend/services/scheduler_service.py`.

- [x] 3.1 In the planning branch (lines 148-160), delete the `retry_at_utc = ... .replace(tzinfo=UTC) if ... is None else ...` expression and compare `planner_service.next_retry_at` directly: `if now >= planner_service.next_retry_at and self._status.next_run_at and now >= self._status.next_run_at:`.
- [x] 3.2 In `_run_scheduled`'s `finally` block (lines 204-210), delete the same coercion and assign `self._status.next_run_at = planner_service.next_retry_at` directly.
- [x] 3.3 Run `rg -n "replace\(tzinfo" backend/services/scheduler_service.py` and confirm zero hits.
- [x] 3.4 Run tasks 1.2 and 1.3 and confirm both now PASS.

## 4. Error classification

File: `planner/errors.py`.

- [x] 4.1 Add `HA_UNAVAILABLE = "HA_UNAVAILABLE"` to `PlannerErrorCode`.
- [x] 4.2 Add to `_USER_MESSAGES`: `PlannerErrorCode.HA_UNAVAILABLE: "Home Assistant is unreachable"`.
- [x] 4.3 Add to `_FIX_HINTS`: `PlannerErrorCode.HA_UNAVAILABLE: ["Home Assistant did not respond. Planning is paused until it returns and will resume automatically — no action needed unless the outage persists."]`.
- [x] 4.4 Add `PlannerErrorCode.HA_UNAVAILABLE` to the set returned by `is_transient`.
- [x] 4.5 Remove `PlannerErrorCode.INITIAL_SOC_OUT_OF_RANGE` from the set returned by `is_config_blocking`. Add no replacement — codes in no set already fall to the normal-cadence branch in `_apply_retry_policy`.
- [x] 4.6 In `backend/core/ha_client.py:486`, replace the `raise RuntimeError(f"Critical: Failed to read battery SoC from {soc_entity_id}. Planning aborted to prevent unsafe assumptions.")` with `raise PlannerError(PlannerErrorCode.HA_UNAVAILABLE, details={"entity_id": soc_entity_id})`. The surrounding comment already states this guard exists for "HA is down", which is exactly `HA_UNAVAILABLE`.
- [x] 4.7 Use a **function-local** import at that raise site — `from planner.errors import PlannerError, PlannerErrorCode` inside the function, matching the existing deferred-import pattern at `planner/pipeline.py:429` and `:1143`. Do NOT add a module-level import: `planner/__init__.py` eagerly loads the full pipeline including the solver, so a top-level import here would make every `ha_client` import drag in the planner. Run `python -c "import backend.core.ha_client"` afterwards and confirm it exits 0.
- [x] 4.8 Confirm the new `PlannerError` is caught by the existing `except PlannerError` handler in `planner_service.run_once` (the typed handler at line 216), not the generic one at line 241 — assert on `error_code` in the test below.
- [x] 4.9 Make no frontend change. `check_planner()` assigns `severity="warning"` to transient codes and `SystemAlert` already renders it.
- [x] 4.10 Test `test_ha_outage_is_transient_and_recovers`: a SoC read returning `None` produces `error_code == "HA_UNAVAILABLE"`, leaves `retry_suspended is False`, and the following run succeeds once the sensor returns a value.

## 5. Bounded suspension

File: `backend/services/planner_service.py`.

- [x] 5.1 Add module constant `_SUSPENSION_CEILING_S = 1800`.
- [x] 5.2 Add `self._suspended_since: datetime | None = None` to `__init__`.
- [x] 5.3 In `_apply_retry_policy`, in the `is_config_blocking` branch, set `self._suspended_since = now` alongside the existing `_retry_suspended = True`.
- [x] 5.4 In `_on_success` and in `clear_retry_suspension`, set `self._suspended_since = None`.
- [x] 5.5 Add property `suspension_expired` returning `True` when `self._retry_suspended` and `self._suspended_since is not None` and `(datetime.now(UTC) - self._suspended_since).total_seconds() >= _SUSPENSION_CEILING_S`.
- [x] 5.6 In `scheduler_service.py`, change the `if planner_service.retry_suspended:` branch so that it runs the planner when `planner_service.suspension_expired` is true, and otherwise skips as before. A repeat config-blocking failure re-enters 5.3, which restarts the ceiling.
- [x] 5.7 In `backend/health.py`, extend `check_planner()` so an active suspension yields a `HealthIssue` with `category="planner"` and `severity="critical"` for as long as `retry_suspended` is true, even when a prior run has since been attempted.
- [x] 5.8 Test `test_suspension_retries_after_ceiling`: with `stockholm_tz` and time advanced past 1800s, a suspended planner attempts a run and re-suspends when it fails again.
- [x] 5.9 Test `test_active_suspension_visible_in_health`: `/api/health` contains the planner suspension issue throughout.

## 6. Skip logging

File: `backend/services/scheduler_service.py`.

- [x] 6.1 Add module constant `_SKIP_LOG_INTERVAL_S = 300`.
- [x] 6.2 Add instance state `self._last_skip_reason: str | None = None` and `self._last_skip_logged_at: datetime | None = None`.
- [x] 6.3 Add a helper `_log_skip(self, reason: str, due_at: datetime | None) -> None` that logs at INFO when `reason != self._last_skip_reason`, or when `_SKIP_LOG_INTERVAL_S` has elapsed since `_last_skip_logged_at`; then updates both fields. The message must name the reason and the due time.
- [x] 6.4 Call `_log_skip("suspended", None)` in the suspension branch, `_log_skip("retry_pending", planner_service.next_retry_at)` when a retry time has not yet arrived, and `_log_skip("cadence_pending", self._status.next_run_at)` when only the cadence is pending.
- [x] 6.5 Reset `self._last_skip_reason = None` whenever the planner actually runs, so the next skip after a run always logs.
- [x] 6.6 Test `test_skip_reason_change_logs_immediately`: changing reason emits a record without waiting for the interval.
- [x] 6.7 Test `test_repeated_skip_reason_is_rate_limited`: 10 consecutive identical skips within 5 minutes emit exactly one record.

## 7. Regression guard

- [x] 7.1 Open `tests/utils/test_no_bare_tz_calls.py` — the existing `dst-safe-time` guard that scans production files for bare `pd.date_range` / `.tz_localize` calls.
- [x] 7.2 Add a scan to `tests/utils/test_no_bare_tz_calls.py` covering `backend/services/planner_service.py` and `backend/services/scheduler_service.py`, failing on `datetime.now()` or `datetime.utcnow()` with no timezone argument.
- [x] 7.3 Exempt lines carrying the comment added in task 2.8. Match on that exact comment string so the exemption cannot spread silently.
- [x] 7.4 Test the guard fails on a reintroduced naive scheduling assignment and passes on `datetime.now(UTC)` and on an exempted elapsed-duration line.

## 8. Existing tests

- [x] 8.1 Update `tests/services/test_planner_retry_policy.py` and `tests/services/test_retry_policy_e2e.py` for aware UTC, and re-run under `stockholm_tz`. Both pass today against broken code, so confirm they now bind.
- [x] 8.2 Run the full backend test suite and the CI quality gate; both green.
