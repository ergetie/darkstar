## Context

`PlannerService` and `SchedulerService` disagree about what a bare `datetime` means.

- `planner_service.py` is naive throughout: every one of its thirteen `datetime.now()` calls returns container-local time, which is `Europe/Stockholm` (`TZ` is set in the container environment; verified in production).
- `scheduler_service.py` is aware throughout: every timestamp it creates uses `datetime.now(UTC)`.

The two meet at `scheduler_service.py:151` and `:205`, which bridge the gap with:

```python
planner_service.next_retry_at.replace(tzinfo=UTC) if planner_service.next_retry_at.tzinfo is None else ...
```

`.replace(tzinfo=UTC)` relabels rather than converts. A naive `11:44` meaning 11:44 CEST (= 09:44 UTC) becomes `11:44 UTC` — an instant two hours later than intended. Every retry time is therefore pushed forward by the host's UTC offset. The `.tzinfo is None` test reads like a defensive guard, which is why this survived review: it looks like it handles both cases, but the naive branch is the only one ever taken and it is the wrong conversion.

Two paths set `next_retry_at`, so both are affected:

1. `clear_retry_suspension()` (line 110) sets `datetime.now()` to mean "retry immediately". Called from `config.py:354` on every config save. Result: saving settings stalls planning for 2 hours.
2. `_apply_retry_policy()` (lines 102, 105) sets the backoff. Result: a 60-second retry becomes a 2-hour outage.

The stall is invisible. The scheduler's skip branches (`scheduler_service.py:144-161`) fall through silently, so the only symptom is downstream: the executor logs `Schedule is stale — holding` and freezes its inverter mode.

A third factor compounded the production incident. The 2026-09-17 failure arrived as a bare `RuntimeError` ("Failed to read battery SoC"), not a `PlannerError`, so it fell to the `UNKNOWN` branch at `planner_service.py:248`. Had it instead raised `INITIAL_SOC_OUT_OF_RANGE` — which `planner/errors.py:96` lists as config-blocking — the planner would have suspended indefinitely rather than for two hours. A SoC reading comes from live hardware, not from `config.yaml`, so no amount of configuration editing is the right remedy.

**Evidence.** 2026-09-17 had 37 planner runs against a baseline of 46/day across the six other retained log days. Four gaps: 124, 58, 124, 134 minutes. Every gap begins at a config save; the six clean days contain no config saves. The gap ending at `19:27:24` follows the `17:27:18` save by 7,206 seconds — the UTC offset to the second. Cadence is `every_minutes: 30, jitter_minutes: 0`, so a 124-minute gap is four skipped cycles.

## Goals / Non-Goals

**Goals:**

- Retry scheduling behaves identically on any host UTC offset.
- A config save never delays planning.
- A transient failure retries on its stated backoff, not offset-shifted.
- A Home Assistant outage recovers with no user action.
- Automatic planning can never stall silently or indefinitely.
- CI catches a reintroduction of the naive/aware mix.

**Non-Goals:**

- Reworking the planner's error taxonomy beyond the two classification changes named in the specs.
- Changing the `/api/health` contract, the `retry_in_s` field, or any frontend component. The UI is already correct and stays as is.
- Changing cadence, jitter, or the executor's stale-schedule holding behavior. Holding on a stale schedule is correct; this change removes the reason it was triggering.
- The two unrelated defects found in the same logs (non-atomic `schedule.json` write; `database is locked` under overlapping planner runs). Tracked separately.

## Decisions

### D1: Make `PlannerService` UTC-aware throughout, rather than fixing the bridge

Convert `PlannerService` to `datetime.now(UTC)` and delete both `.replace(tzinfo=UTC)` coercions in the scheduler.

*Alternative considered:* patch only the scheduler, converting local→UTC properly with `.astimezone(UTC)` after localizing. Smaller diff, and it would fix the observed bug. Rejected because it preserves the actual defect — two modules disagreeing about what a bare datetime means — and leaves a correct-looking conversion at the boundary that the next person must reason about. The current bug exists precisely because a boundary conversion looked plausible. One representation end to end removes the boundary instead of documenting it.

*Consequence:* `retry_in_s` (line 88) currently compares naive-to-naive and so returns the right answer today. It must be converted in the same pass; converting `_next_retry_at` alone would break the one thing that currently works. This is the trap in this change and the reason the conversion must be complete rather than incremental.

### D2: Distinguish scheduling timestamps from elapsed-duration timestamps

Not all thirteen `datetime.now()` calls are equal:

- **Cross-module scheduling state** — `_next_retry_at` (102, 105, 110), `_last_error_at` (221, 246), `retry_in_s` (88), `_apply_retry_policy`'s `now` (92). These cross into the scheduler or the health API and MUST become aware UTC.
- **Local elapsed duration** — `_planner_start_time` and `start` (118, 140, 173, 202, 229, 254). Both ends of each subtraction share a representation, so these are correct as written.
- **Serialized output** — `planned_at` (168) and the progress `timestamp` (126) are emitted to API consumers. Convert for consistency, but verify the frontend renders them unchanged.

Converting only the first group would be enough to fix the bug. Convert the first and third; leave the second alone and let the regression guard exempt it explicitly (D4). Blanket-converting the duration timestamps adds churn to code that is not wrong.

### D3: Reclassify, and bound suspension with a ceiling

Two changes to `planner/errors.py`:

- Move `INITIAL_SOC_OUT_OF_RANGE` out of `is_config_blocking` into the invariant/normal-cadence group. A hardware reading is not a configuration error.
- Add `HA_UNAVAILABLE` as a transient code, and map the SoC-read safety abort to it rather than letting it reach `UNKNOWN`.

`HA_UNAVAILABLE` reuses the existing banner. Because it is transient, `check_planner()` already assigns it `severity="warning"`, which `SystemAlert` already renders — so it needs a `_USER_MESSAGES` and `_FIX_HINTS` entry (both dicts are looked up unconditionally and would `KeyError` without one) and **no frontend change whatsoever**. The executor emits its own connectivity errors during the same outage; a second planner-specific banner for one root cause would be noise.

Reclassification alone is not sufficient. It fixes the codes known to be misclassified today but leaves the structural hazard: any config-blocking failure parks the planner until the user happens to save settings, with no upper bound. Add a ceiling — after a bounded period a suspended planner attempts a run regardless, re-suspending if it fails again — plus a health issue while suspension is active.

*Ceiling value:* **30 minutes** (`_SUSPENSION_CEILING_S = 1800`), matching `every_minutes: 30`. Long enough that a genuine config error cannot produce a retry storm — the worst case is one planner run per 30 minutes, which is exactly the normal steady-state load — and short enough that an overnight stall self-corrects. The requirement stays unitless so the constant can be tuned without a spec change.

*Alternative considered:* remove config-blocking suspension entirely and let everything back off. Rejected — a genuinely invalid config will fail identically every time, and hammering it wastes a ~75-second planner run per cycle and floods the log. Suspension is right; unbounded suspension is not.

### D4: Regression guard extends the existing `dst-safe-time` guard

`dst-safe-time` already owns a CI test that scans production files for DST-unsafe patterns. Extend it rather than adding a parallel mechanism: same idea (a representation mistake that fails silently rather than raising), same enforcement point, one place to look.

The guard must exempt local elapsed-duration use (D2), or it will flag correct code and be disabled. Scope it to `planner_service.py` and `scheduler_service.py` initially; widening it across the backend is a larger cleanup and is out of scope here.

### D5: Tests must pin a non-UTC offset explicitly

Every bug in this class is invisible when the host runs UTC, where `.replace(tzinfo=UTC)` is the identity. CI and most dev machines run UTC; production runs UTC+2. That gap is why this shipped.

Retry-path tests MUST therefore force a non-UTC timezone rather than inheriting the host's. Freeze time and set the zone explicitly. A test that passes under both UTC and UTC+2 is the actual regression barrier — the existing tests in `test_planner_retry_policy.py` and `test_retry_policy_e2e.py` pass today against the broken code because they never leave UTC.

Include a direct regression test for the reported symptom: config save → next automatic run occurs within one cadence interval, asserted on a UTC+2 host.

## Risks / Trade-offs

- **An incomplete conversion silently breaks `retry_in_s`, which is correct today** → The naive-to-naive comparison at line 88 is load-bearing. Convert every member of the D2 scheduling group in one commit; the guard in D4 backstops a missed call site. Highest-likelihood failure mode of this change.

- **Mixing aware and naive datetimes raises `TypeError` at runtime, in the failure-recovery path** → A missed call site turns a recoverable planner failure into a crashing retry loop — worse than the bug being fixed, and reached only when something else has already gone wrong. Tests must exercise the retry path itself, not just assert on timestamps. Partly mitigated by `TypeError` being loud, unlike the current silent shift.

- **`_last_error_at` may be persisted or serialized somewhere unexamined** → A repo search found no consumers beyond `retry_in_s` and the health API, but "no consumers found" is weaker than "no consumers exist". Grep for persistence and `isoformat()` on these fields before converting.

- **Reclassifying `INITIAL_SOC_OUT_OF_RANGE` means a genuinely misconfigured SoC sensor now retries every 60s instead of suspending** → Accepted: the ceiling in D3 means even config-blocking errors retry eventually, so this narrows rather than removes rate limiting. Watch log volume after deploy.

- **A suspension ceiling set too short turns a real config error into a retry storm** → Start at 30 minutes, matching cadence. One run per 30 minutes is the normal load, so the worst case is no worse than steady state.

- **Skip logging in a 30-second loop floods the log** → Rate-limit to one record per 5 minutes per unchanged reason (`_SKIP_LOG_INTERVAL_S = 300`), and always log immediately on reason change. That caps the addition at ~288 records/day against a ~24 MB/day baseline, versus ~2,880 unthrottled.

## Migration Plan

No data, config, or API migration. Single deployable unit; backend only.

1. Land the conversion (D1, D2) with tests pinned to a non-UTC offset (D5).
2. Land the reclassification and ceiling (D3).
3. Land the skip logging and the regression guard (D4).

**Post-deploy verification** (outside this change, once deployed): save config and confirm the next automatic planner run lands within one cadence interval rather than one UTC offset later; the day after, confirm the planner run count returns to ~46/day on a day that includes config saves.

**Rollback:** revert the deploy. State is in-memory and rebuilt on restart, so there is nothing to undo. The pre-change failure mode is a delay, not corruption.
