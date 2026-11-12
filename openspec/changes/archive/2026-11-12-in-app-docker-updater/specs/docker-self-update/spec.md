# Spec Delta

## Purpose
Let plain-Docker installs check for and apply Darkstar updates from the UI, building locally from git through an isolated updater, without exposing the Docker socket to the Darkstar container.

## ADDED Requirements

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
The updater SHALL run `git fetch --tags origin` and compare the checked-out commit with the channel target. Checks SHALL run automatically every 6 hours and on demand ("Check now"). The result SHALL include current version/commit, target version/commit, whether an update is available, and for `dev` a summary of up to 20 commit subjects between current and target. A failed fetch SHALL be reported as an error with the last successful check time retained.

#### Scenario: Dev behind
- **WHEN** `origin/main` is ahead of the checkout
- **THEN** status shows update available with target version and commit subjects

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
- **THEN** it checks out the target (`dev`: fast-forward `main` to `origin/main`; `stable`: detached checkout of the tag), runs `docker compose build darkstar` with `DARKSTAR_VERSION` and `DARKSTAR_RELEASE_CHANNEL` build args, and only on build success runs `docker compose up -d --no-deps darkstar`

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
