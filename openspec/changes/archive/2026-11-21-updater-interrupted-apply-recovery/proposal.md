# Proposal

## Why

On 2026-11-21 an in-app update (dev, to `dev-261121.1826`) was killed halfway: the UI told the user to run a host command while the update was still running, the user ran it, the updater container was recreated, and the interrupted apply was recorded as `failed` ("Updater restarted during the update") although Darkstar had already restarted on the target version. The updater never checks what actually happened when it restarts mid-apply. Depending on the stage, it can also leave the checkout at the target while the old build still runs, and then refuses to retry ("Already up to date").

## What Changes

- On start-up, an apply left `building` or `restarting` is reconciled against the version the Darkstar container really reports, instead of being blindly marked `failed`:
  - running version equals the target: the apply is recorded as `done`;
  - running version equals the previous version: the checkout is restored to the previous commit/branch and the apply is `failed` with "Update was interrupted; nothing changed, safe to retry";
  - the container is unreachable or reports another version for 5 minutes: the apply is `failed` with a diagnostic message and the checkout is left untouched.
- The apply record persists the previous commit, branch, version and channel as soon as an apply starts, so recovery survives the updater restart.
- A stale `failed` record whose target equals the running version is cleared to `idle` (already implemented in the working tree: `_settle_completed_failure`, called from `check()`; kept and refined).
- The update card never tells the user to run a host command (the "Updater unavailable" hint and the "updater itself is outdated" hint) while an update is in progress or Darkstar is restarting as part of it. The in-progress knowledge lives in `useUpdater` (app level) so it survives closing the card, and is not erased by a `reachable: false` response.

## Capabilities

### New Capabilities

### Modified Capabilities
- `docker-self-update`: Apply gains start-up recovery of an interrupted apply; UI feedback gains the no-host-command-during-update rule; feature availability's "updater unavailable" hint is suppressed during an update.

## Impact

- `updater/service.py` (apply record, `recover_interrupted`, `_settle_completed_failure`), `updater/server.py` (start-up order).
- `frontend/src/lib/useUpdater.ts`, `frontend/src/components/UpdateCard.tsx` and their vitest tests.
- `tests/updater/test_updater.py`.
- No new dependencies, no database change, no new endpoints; `docs/` untouched.
