# Design

## Context

Incident 2026-11-21 (UTC), evidence from prod:

- Apply started 18:40:20 (`state.json` `started_at`). Updater stages (`updater/service.py` `_apply_steps`): checkout -> `compose build` -> `compose up -d --no-deps darkstar` -> `restarting` + `_wait_for_version` (5 min) -> `done` -> `_maybe_recreate`.
- Darkstar was recreated 18:41:54 (container `Created`), started 18:42:09, and only listened on :5000 at 18:43:46 (pre-migration backup 30 s, retention cleanup 44 s). The apply log ends at "Container darkstar Started": the updater was in `restarting`, inside `_wait_for_version`.
- Docker events: the updater container was killed at 18:42:10 (SIGTERM ignored, SIGKILL at 18:42:21) and recreated; again at 18:42:44 after a fresh image build at 18:42:42, "Updater listening" 18:42:56. `~/.bash_history` on prod holds `docker compose up -d --build updater` twice, the text of the "updater itself is outdated" hint (`UpdateCard.tsx` ~188-190), not the "unavailable" hint.
- The hint is shown because the checkout moved to the target before the build, so the repo fingerprint of `updater/` and `docker-compose.yml` differs from the running updater (`service.py` `_updater_outdated`), and that banner is not guarded by `inProgress`. Had the user waited, `_maybe_recreate` would have recreated the updater itself ~18:43:50.
- The "Updater unavailable" banner (`UpdateCard.tsx:133`) is guarded by `!inProgress && !reconnecting`, but `inProgress` depends on the card-local `awaiting` flag (lost when the card closes, `App.tsx:122`) and on `status.apply`, which `useUpdater.run` replaces wholesale by a `reachable: false` payload (`useUpdater.ts` `setStatus(next)`). During Darkstar's own down time requests fail, `refresh()` returns null and `reconnecting` hides the banner, so the restart window itself is covered.
- Consequences of a kill, per stage: checkout (git op interrupted, possibly stale `index.lock`, repo may be at target or previous); build (repo at target, old container running, retry refused with "Already up to date", `updater_outdated` true); `compose up` (container possibly stopped/renamed by the half-run CLI; Darkstar may be down); `restarting`/wait (new container running, no one records `done`, `_maybe_recreate` skipped, DB already migrated); rollback (state is also `restarting`). Today `mark_interrupted` (`service.py` ~294) only flips to `failed`; nothing restores the checkout, and `_restore`/`_rollback` run only inside the dead thread.

## Goals / Non-Goals

**Goals:** a restart of the updater at any stage ends in a truthful, retry-safe state; no UI text sends the user to the host mid-update.

**Non-Goals:** making the updater survive SIGTERM mid-apply (a handler could not finish a build anyway); resuming a build; database restore on recovery (decided below); changing the API surface.

## Decisions

1. **Decide from facts, with the running version as the oracle.** Recovery polls `_running_version()` (same fetcher as `_wait_for_version`) every `HEALTH_POLL_S` up to `HEALTH_TIMEOUT_S`. Alternative: a persisted stage marker; rejected, a marker says where the thread was, not what Docker did (a kill during `compose up` is ambiguous), the version is authoritative.
2. **Outcomes.** target running -> `done`. Previous version running on two consecutive polls (guards against the old container still being stopped by an interrupted `up`) -> restore checkout, `failed` "Update was interrupted; nothing changed, safe to retry". Timeout, or only unreachable/third version -> `failed`, checkout untouched, message points at `docker compose logs darkstar`. Never destroy state on uncertainty.
3. **`done`, not `idle`, for a completed apply.** The UI reloads on `done` + matching version (`UpdateCard.tsx` tick), which an old frontend open in a browser needs; `idle` would leave stale JS running. `done` is also what a normal apply leaves. `idle` is correct for the already-implemented `_settle_completed_failure`, which clears a *stale failed* record (nothing to reload for: the user has long since seen the outcome, and recovery no longer creates such records). It stays for records written by older updaters, such as the current prod record, and is also evaluated on `check()`.
4. **Persist `previous` in the apply record** (`commit`, `branch`, `version`, `channel`) before the first checkout mutation, in `_apply_steps` via `_set_apply(..., previous=...)`. `_set_apply` carries `previous` over between states and drops it in terminal states (`done`, `failed`). `PreviousState.started` is not needed for recovery (no DB restore). Records without `previous` (killed in the window between `start_apply` and the first write, or written by an older updater) never restore anything.
5. **No DB restore in recovery.** An old version answering means the new container is not running against the database. If the target ran, we do not roll back (decision 2); the pre-migration backup remains for manual use.
6. **Recovery runs in the background, holding the apply lock.** `recover_interrupted()` takes `_apply_lock` synchronously, sets `restarting` ("Updater restarted, checking the outcome of the update"), and finishes in a daemon thread, so the HTTP server starts immediately and `check()`/`apply` refuse meanwhile. Order in `server.py`: `reconcile_self_update()` first, then `recover_interrupted()`. After `done`, recovery calls `_maybe_recreate()` exactly like the normal flow (guarded once per fingerprint, so a manual recreate by the user makes it a no-op). `mark_interrupted` is replaced.
7. **UI.** `useUpdater` owns `applyInFlight` (set on accepted apply and whenever a reachable status shows `building`/`restarting`; cleared by a reachable status with another apply state; an unreachable reply leaves it untouched; expires 10 min after the last observation). `UpdateCard` uses `inProgress = applyInFlight || awaiting || applyState in (building, restarting)`; both command hints require `!inProgress`; the unreachable case renders "Updater not responding, the update continues". The `done` branch of the card tick is unchanged. Considered and rejected: also retaining the last known `apply`/`updater_outdated` across a `reachable: false` reply. It would be redundant: `applyInFlight` already gates every consumer that needs the knowledge (both hints and the neutral message), the unreachable payload has no live progress to show, and a stale `apply` object would be shown as current state next to "not responding" and risk the card tick acting on an outdated `done`/`building` record. A single boolean with an expiry is the smaller, safer state.
8. **Spec overlap.** "Feature availability / Updater down" still describes the hint for an idle state; the new UI rule narrows it to "not during an update". No change needed to that requirement's text.

## Risks / Trade-offs

- [Target version reports while a rollback was running] -> marked `done`; the version answering is the truth and the next check/UI reflects it.
- [Old version briefly answers while an interrupted `up` is replacing it] -> two consecutive polls; the CLI is dead so the daemon finishes at most one call.
- [Restore fails (stale `.git/index.lock`, permissions)] -> `failed` with the manual `git checkout` command; no retry loop.
- [Container never comes back] -> after 5 min the apply is `failed`, nothing restored; retrying is refused if the checkout is at target ("Already up to date") but the message names the logs/compose command. Accepted: guessing would risk the data.
- [In-flight guard hides the unavailable hint while the updater is really dead] -> bounded by the 10 min expiry.

## Migration Plan

Ships with the next update. Existing `failed` records are handled by `_settle_completed_failure`; records without `previous` follow the no-previous path. Rollback is reverting the commit; no data format is incompatible.
