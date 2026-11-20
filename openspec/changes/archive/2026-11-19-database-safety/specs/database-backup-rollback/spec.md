# Spec Delta

## Purpose

Guarantee that a database schema migration (and the one-time storage-format switch) can always be undone: a consistent backup is taken first, a failed backup stops the migration, and a failed migration puts the backup back.

## ADDED Requirements

### Requirement: Backup only before a pending change
The system SHALL take a database backup during container start-up only when an Alembic migration is pending or the one-time auto-vacuum switch is pending, and SHALL NOT take one on a start where neither applies. A missing or empty database file and a first-ever start SHALL NOT produce a backup.

#### Scenario: Nothing pending
- **WHEN** the database revision equals the Alembic head and auto-vacuum is already incremental
- **THEN** no backup file is created and no backup is pruned

#### Scenario: Migration pending
- **WHEN** the database revision differs from the Alembic head
- **THEN** a backup is created before `alembic upgrade head` runs

#### Scenario: Fresh install
- **WHEN** the database file does not exist or is empty
- **THEN** no backup is attempted and the migration proceeds

### Requirement: Consistent backup
Backups SHALL be made with SQLite's online backup API from a read-only source connection, written to a temporary name, verified with `PRAGMA quick_check`, stored as one self-contained file, and only then renamed to `pre-migration-<UTC timestamp>-<from revision>.db` in a `backups/` folder next to the database file, which survives container recreation.

#### Scenario: WAL content included
- **WHEN** the live database has committed rows that exist only in its WAL file
- **THEN** the backup contains all committed rows

#### Scenario: Corrupt copy never published
- **WHEN** the verification of the new copy fails
- **THEN** the temporary file is deleted and the backup is reported as failed

### Requirement: Bounded backup count
The system SHALL keep the 3 newest `pre-migration-*.db` backups and delete older ones after each successful backup. Files not matching that name pattern SHALL NOT be touched.

#### Scenario: Fourth backup
- **WHEN** a fourth backup is created
- **THEN** the oldest `pre-migration-*.db` file is deleted and the other three remain

### Requirement: Migration aborts when the backup fails
If a backup is required for a pending migration and cannot be created (including insufficient free disk space), the system SHALL NOT run the migration, SHALL log the reason and SHALL exit non-zero so the process does not start on an unprotected database. If only the one-time auto-vacuum switch is pending and its backup fails, the switch SHALL be skipped with a warning and start-up SHALL continue.

#### Scenario: Backup fails before migration
- **WHEN** the backup cannot be written
- **THEN** the database file is unchanged, no migration ran and start-up stops with an error

#### Scenario: Backup fails for the switch only
- **WHEN** no migration is pending and the backup fails
- **THEN** the switch is skipped, a warning is logged and the application starts normally

### Requirement: Failed migration restores the backup
If `alembic upgrade head` fails after a backup was taken, the system SHALL replace the database with that backup (atomically, discarding any `-wal`/`-shm` files) before exiting non-zero.

#### Scenario: Partial migration
- **WHEN** a migration fails half way
- **THEN** the database is byte-for-byte the pre-migration backup and the process exits non-zero

### Requirement: Same behaviour in Docker and add-on
The Docker entrypoint, `darkstar/run.sh` and `darkstar-dev/run.sh` SHALL all use the same backup, abort and restore behaviour and SHALL resolve the database path the same way the application does (`DB_PATH`, else `learning.sqlite_path`, else `data/planner_learning.db`).

#### Scenario: Add-on upgrade
- **WHEN** the add-on starts with a pending migration
- **THEN** a backup appears in `/share/darkstar/backups/` before the migration runs
