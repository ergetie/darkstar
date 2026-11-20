## MODIFIED Requirements

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

## ADDED Requirements

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
