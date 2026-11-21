# Tasks

## 1. Already implemented (keep, refine)

- [x] 1.1 `_settle_completed_failure` in `updater/service.py`, called from `check()` and recovery; compares the running container version, not the checkout
- [x] 1.2 Tests: cleared at target, cleared on check, different version kept, checkout-at-target with old version running kept, unreachable kept
- [x] 1.3 Fixture type `running: str | None` stays; run `./scripts/lint.sh` on these edits

## 2. Persist previous state

- [x] 2.1 `_set_apply`: carry `previous` from the prior record, accept it via `extra`, drop it for `done`/`failed`
- [x] 2.2 `_apply_steps`: write `previous` (commit, branch, version, channel) with the `building` record before the first checkout command
- [x] 2.3 Tests: record holds `previous` during build and `restarting`, and none after `done`/`failed`

## 3. Startup recovery

- [x] 3.1 Add `recover_interrupted(threaded=True)` replacing `mark_interrupted`: take the apply lock, set `restarting`, run the decision in a daemon thread (synchronous when `threaded=False` for tests)
- [x] 3.2 Decision loop: poll `_running_version()` every `HEALTH_POLL_S` up to `HEALTH_TIMEOUT_S`; target -> `done` (+ `_maybe_recreate`); previous twice in a row -> `_restore` then `failed` "Update was interrupted; nothing changed, safe to retry" (restore failure -> failed with manual command); timeout -> `failed`, checkout untouched; no `previous` -> never restore
- [x] 3.3 `server.py`: `reconcile_self_update()` then `recover_interrupted()`; keep the lock-release in a `finally`
- [x] 3.4 Tests (fixture `running`, no-op sleep and fast clock `_fast_clock`): killed in `building` with old running and checkout moved to target (restored, failed, retry then works); killed mid-`restarting` with target running (`done`); target appears after unreachable polls; old running once then target (not restored); unreachable until timeout (failed, HEAD unchanged); third version (untouched); restore failure; no `previous`; checks and apply refused while recovering; `_maybe_recreate` invoked after `done`; replace `test_interrupted_apply_marked_failed`

## 4. UI guard

- [x] 4.1 `useUpdater`: `applyInFlight` (+ 10 min expiry), unchanged by `reachable: false` replies; set after accepted `apply()`
- [x] 4.2 `UpdateCard`: `inProgress` from the hook; gate the "unavailable" and "updater outdated" hints on `!inProgress`; render "Updater not responding, the update continues" when unreachable mid-update
- [x] 4.3 Vitest in `UpdateCard.test.tsx`: no command hints with `apply: building` + `updater_outdated`; no hint when `reachable: false` after a `restarting` status (card closed and reopened); hints return when idle; expiry after 10 min (fake timers)

## 5. Verify

- [x] 5.1 `UV_NO_SYNC=1 uv run python -m pytest tests/updater -q`, frontend `pnpm test` for the update card, `./scripts/lint.sh`
