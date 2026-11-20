# Capability: Docker Self Update

## Purpose
Let plain-Docker installs check for and apply Darkstar updates from the UI, building locally from git through an isolated updater, without exposing the Docker socket to the Darkstar container.

## Requirements

### Requirement: Feature availability
The update feature SHALL be available only when `DARKSTAR_INSTALLATION_TYPE` is `docker` and the updater is opted in (`DARKSTAR_UPDATER_URL` and `DARKSTAR_UPDATER_TOKEN` both set). It SHALL be hidden for `ha_addon` installs and for installs without the token, so installs that update manually keep working unchanged. If the updater is opted in but unreachable, the UI SHALL show an explanatory "updater unavailable" state and no dot, banner or update action.

#### Scenario: HA add-on
- **WHEN** installation type is `ha_addon`
- **THEN** no update UI is shown and `/api/updater/*` returns 404

#### Scenario: Not opted in
- **WHEN** `DARKSTAR_UPDATER_TOKEN` is unset (no `.env`, `updater` compose profile disabled)
- **THEN** `/api/updater/*` returns 404 and no update UI is shown

#### Scenario: Updater down
- **WHEN** installation type is `docker` and the updater does not respond
- **THEN** the UI shows "updater unavailable" with a hint to run `docker compose up -d updater`

### Requirement: Updater isolation
The Darkstar container SHALL NOT mount or receive the Docker socket. The updater SHALL be reachable only on the internal compose network (no published port) and SHALL reject every request lacking the correct shared-secret bearer token (constant-time compare). The updater SHALL accept only fixed operations (status, check, set channel, apply, log) and SHALL NOT run caller-supplied commands, refs or paths.

#### Scenario: Bad token
- **WHEN** a request has a missing or wrong token
- **THEN** the updater returns 401 and performs no action

#### Scenario: Ref injection
- **WHEN** a request body contains a ref or command
- **THEN** it is ignored; the target is derived solely from the stored channel

### Requirement: Channels
Two channels SHALL exist: `dev` (HEAD of `origin/main`) and `stable` (highest `v*` tag by version order with `versionsort.suffix=-`; pre-release tags such as `v2.7.1-beta` count but sort below their final release). The channel SHALL be switchable in Settings and persisted by the updater across restarts. The initial channel SHALL default to `dev` if the current `VERSION` starts with `dev-`, else `stable`. The reported release channel (installation stats) SHALL reflect the active channel.

#### Scenario: Switch to stable
- **WHEN** the user selects Stable and checks
- **THEN** the target is the latest `v*` tag and the UI shows it, even if it is older than the current commit (subject to the database gate)

### Requirement: Update check
The updater SHALL run `git fetch --prune origin` and `--tags` (without `--force` or `--prune-tags`) from the pinned origin and compare the checked-out commit with the channel target. Checks SHALL run automatically every 6 hours and on demand ("Check now"). The result SHALL include current version/commit, target version/commit, whether an update is available, and for `dev` a summary of up to 20 commit subjects between current and target.

#### Scenario: Dev behind
- **WHEN** `origin/main` is ahead of the checkout
- **THEN** status shows update available with target version and commit subjects

### Requirement: Update check network behaviour
A failed fetch SHALL be reported as an error with the last successful check time retained. Git network operations SHALL use anonymous HTTPS (ssh GitHub origins are rewritten) and never prompt for credentials. Tags are not force-fetched: a tag that already exists locally is never overwritten by the remote.

#### Scenario: Offline
- **WHEN** fetch fails
- **THEN** status shows the fetch error and no update is offered based on stale data

### Requirement: Dirty tree refusal
The updater SHALL refuse to apply when `git status --porcelain --untracked-files=no` is non-empty, listing the modified files in the response. Untracked files and the bind-mounted `config.yaml`, `secrets.yaml`, `data/` SHALL never be modified.

#### Scenario: Local edit
- **WHEN** a tracked file is modified
- **THEN** apply is rejected with the file list and nothing changes

### Requirement: Database revision gate
Before apply (and shown at check time), the updater SHALL read the DB's current alembic revision from `data/planner_learning.db` (read-only) and verify that the target commit's `alembic/versions` contains that revision. If it does not, apply SHALL be blocked with the message "<Channel> doesn't include your database version yet". No downgrade SHALL be attempted. An absent or empty DB SHALL pass the gate.

#### Scenario: Dev to Stable
- **WHEN** the DB revision is missing from the stable tag's migrations
- **THEN** the Update button is disabled and the message is shown

### Requirement: Apply
Apply SHALL re-run the gates, check out the target, build Darkstar locally and restart it only after a successful build. Only one apply SHALL run at a time (409 otherwise), and progress SHALL be retrievable by polling and persisted to a log file.

#### Scenario: Steps
- **WHEN** apply starts
- **THEN** it checks out the target commit resolved at apply time (`dev`: fast-forward `main` to that commit; `stable`: detached checkout of that commit), runs `docker compose build darkstar` with `DARKSTAR_VERSION` and `DARKSTAR_RELEASE_CHANNEL` build args, and only on build success runs `docker compose up -d --no-deps darkstar`

#### Scenario: Build fails
- **WHEN** `docker compose build` exits non-zero
- **THEN** the checkout is restored, the old container keeps running, status is `failed` with the log tail

#### Scenario: Success
- **WHEN** build and `up -d` succeed
- **THEN** status is `restarting`, then `done` once the new container reports the target version

### Requirement: UI feedback and reconnect
The UI SHALL show update state, let the user switch channel, check, and confirm an update, show live progress, and reconnect automatically after the restart.

#### Scenario: Layout
- **WHEN** an update is available
- **THEN** a dot shows next to the version in the sidebar (and the mobile nav); clicking the version opens a floating card with current/target version, channel selector, Check now, Update (with confirm), messages, live log and restarting state; a dismissible banner announces the update and dismissal persists per target version

#### Scenario: Unhealthy
- **WHEN** the new container is not healthy within 5 minutes
- **THEN** the UI shows the failure with a pointer to the updater log

#### Scenario: Restart
- **WHEN** the container restarts after apply
- **THEN** the UI shows "Restarting" and reconnects automatically without manual reload

### Requirement: Test isolation
Automated tests SHALL NOT access the network, GitHub or Docker; git and docker invocations SHALL go through injectable fakes.

#### Scenario: Test run
- **WHEN** the suite runs offline
- **THEN** all updater tests pass

### Requirement: Automatic rollback on failed update
If `docker compose up -d` fails, or the updated container does not report the target version within the health window, the updater SHALL restore the previous checkout, rebuild and restart the previous version, wait until it reports its own version, and mark the apply `failed` with a message stating that it was rolled back. A build failure SHALL keep its existing behaviour (checkout restored, running container untouched).

#### Scenario: Unhealthy new version
- **WHEN** the new container never reports the target version
- **THEN** the previous commit is checked out, rebuilt and started, and status is `failed` with "rolled back" in the message

#### Scenario: Start failure
- **WHEN** `up -d` returns non-zero
- **THEN** the same rollback runs

### Requirement: Database restored with the code
When the failed update had created a `pre-migration-*.db` backup (file time not earlier than the apply start), the updater SHALL stop the Darkstar container and replace `planner_learning.db` with the newest such backup, discarding `-wal`/`-shm`, before restarting the previous version. When no such backup exists the database SHALL be left untouched.

#### Scenario: Migrated then unhealthy
- **WHEN** the new container migrated the database and then failed its health check
- **THEN** the pre-migration backup is back in place before the previous version starts

#### Scenario: Failed before migration
- **WHEN** the new container failed before any backup of this apply was written
- **THEN** the database is not modified

### Requirement: Rollback failure is reported
If the rollback itself cannot complete, the updater SHALL record apply state `failed` with a message naming the backup file and the manual restore command, and SHALL NOT retry in a loop.

#### Scenario: Restore error
- **WHEN** the database restore raises an error
- **THEN** the message names the backup path and the state is `failed`

### Requirement: Updater recreates itself after an update
After an apply that ends `done`, when the updater source or `docker-compose.yml` differs from what the running updater started with, the updater SHALL recreate itself through a detached helper container, at most once per changed version. A failed recreate SHALL leave the old updater running and visible as `failed` with the helper output in the apply log. Darkstar SHALL never be affected.

#### Scenario: Updater changed
- **WHEN** an update changed `updater/` or `docker-compose.yml` and finished `done`
- **THEN** the updater is rebuilt and recreated, the new process reports `self_update` state `done`, and `updater_outdated` is false

#### Scenario: Recreate fails
- **WHEN** the helper's build fails
- **THEN** the old updater keeps serving, `self_update` is `failed` with a message and the manual command, and no further attempt is made for that version

#### Scenario: After a rollback
- **WHEN** an apply was rolled back
- **THEN** no self-recreate is started

### Requirement: Rollback needs a writable data mount
When the updater's data directory is not writable, rollback SHALL restore the code, leave the database untouched and report the manual restore command and backup file instead of failing.

#### Scenario: Old read-only mount
- **WHEN** a rollback runs on a read-only data mount
- **THEN** the previous version is restarted and the message names the backup and the restore command

### Requirement: Pinned origin
The updater SHALL fetch and apply only from the `github.com/ergetie/darkstar` repository. Before every fetch and every apply it SHALL check the `origin` remote, accepting the https, `git@github.com:` and `ssh://git@github.com/` forms with or without a `.git` suffix, and SHALL refuse any other origin without changing the checkout.

#### Scenario: Foreign origin
- **WHEN** origin points to any repository other than `ergetie/darkstar`
- **THEN** check records an error "Origin is not github.com/ergetie/darkstar", apply is rejected, and no fetch or checkout runs

#### Scenario: Equivalent forms accepted
- **WHEN** origin is `git@github.com:ergetie/darkstar.git` or `https://github.com/ergetie/darkstar`
- **THEN** the origin check passes

### Requirement: Published tags are immutable locally
The updater SHALL NOT force-update or prune tags when fetching. A tag that changed upstream SHALL be reported as a warning in the check result and the locally held tag SHALL keep being used. Other fetch failures SHALL remain check errors.

#### Scenario: Tag moved upstream
- **WHEN** a fetched tag already exists locally at a different commit
- **THEN** the local tag is unchanged, the check still succeeds, and the result carries a warning naming the tag

#### Scenario: Newest tag deleted upstream
- **WHEN** the newest release tag no longer exists on origin
- **THEN** it is still held locally and no older tag is offered as an update

#### Scenario: Other fetch failure
- **WHEN** the fetch fails for any reason other than a changed tag
- **THEN** the check records the error

### Requirement: Apply installs the resolved commit
Apply SHALL re-resolve the target at apply time and check out or fast-forward to the resolved commit hash, not a ref name.

#### Scenario: Tag moves between check and apply
- **WHEN** a ref moves after the last check
- **THEN** apply installs the commit it resolved at apply time and the version shown matches that commit

### Requirement: Stable refuses downgrades
A stable install on a detached tagged checkout SHALL refuse a target that is a strict ancestor of its current commit. Switching from dev to stable SHALL remain allowed.

#### Scenario: Older target
- **WHEN** a stable install resolves a target older than the installed commit
- **THEN** apply is rejected with "Target is older than the installed version"

#### Scenario: Dev to stable
- **WHEN** a dev install on a branch switches to stable and applies
- **THEN** the apply is not refused by this rule

### Requirement: Dev channel is fast-forward only
The dev channel SHALL apply only when the current commit is an ancestor of the target and SHALL install by fast-forward to the resolved commit.

#### Scenario: Diverged history
- **WHEN** the local commit is not an ancestor of `origin/main`
- **THEN** apply is rejected with "Dev branch history diverged, refusing non-fast-forward update" before any checkout
