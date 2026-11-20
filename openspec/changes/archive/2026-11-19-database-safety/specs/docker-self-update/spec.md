# Spec Delta

## ADDED Requirements

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
