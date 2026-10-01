## MODIFIED Requirements

### Requirement: All config writers persist atomically
Every code path that writes `config.yaml` at runtime SHALL persist the file through the single shared config writer, which writes to a temporary file in the same directory as the resolved target and then atomically replaces the target. This covers startup migration, the UI/wizard save endpoint, config reset, the Reflex toggle, executor endpoints, theme selection, and the Reflex learning engine. No writer SHALL open the live config file in truncating write mode (`"w"`), stream content directly into it, or copy over it outside the shared writer.

#### Scenario: UI save uses the atomic writer
- **WHEN** a user saves configuration via `POST /api/config/save` and validation passes
- **THEN** the save SHALL write through the shared atomic writer (temp file + atomic replace)
- **AND** the live `config.yaml` SHALL NOT be opened in `"w"` truncating mode by the save handler

#### Scenario: Secondary writers use the atomic writer
- **WHEN** the Reflex toggle, an executor settings endpoint, theme selection, the Reflex learning engine, or config reset changes `config.yaml`
- **THEN** the change SHALL be persisted through the shared atomic writer

#### Scenario: Crash mid-write never truncates the live file
- **WHEN** any config write is interrupted before the atomic replace completes
- **THEN** the live `config.yaml` SHALL retain its previous complete contents
- **AND** no empty or partially-written `config.yaml` SHALL be left in place

### Requirement: A backup exists before any overwrite
Before overwriting an existing `config.yaml`, the writer SHALL create a timestamped backup in the persistent backup directory resolved from the real (symlink-resolved) config path.

#### Scenario: UI save creates a backup
- **WHEN** a user saves configuration and a `config.yaml` already exists
- **THEN** a timestamped backup of the prior config SHALL be created before the new content is written

#### Scenario: Add-on backups land in persistent storage
- **WHEN** the writer is invoked with `config.yaml` that is a symlink to `/config/darkstar/config.yaml`
- **THEN** the timestamped backup SHALL be written to `/share/darkstar/backups`
- **AND** no backup SHALL be written to the ephemeral `/app/backups`

#### Scenario: Backups are retention-pruned
- **WHEN** a backup is created and more than the retention limit exist
- **THEN** the oldest backups beyond the limit SHALL be removed

### Requirement: Bind-mount writes remain atomic
On filesystems where an atomic replace is not possible (e.g. Docker single-file bind mounts that raise `EXDEV`/`EBUSY`/`ETXTBSY`), the writer SHALL first attempt the atomic replace within the target's own directory. If that raises one of those errors, it SHALL go directly to the guarded last-resort copy without repeating the identical replace.

#### Scenario: Bind-mount path replaces within the same filesystem
- **WHEN** the target config lives on a mount where same-directory replace succeeds
- **THEN** the write SHALL complete via an atomic replace within that filesystem
- **AND** the live config SHALL NOT be truncated by a streaming copy

#### Scenario: Last-resort copy is flushed and guarded
- **WHEN** an atomic replace raises `EBUSY`, `EXDEV` or `ETXTBSY`
- **THEN** the writer SHALL NOT retry the identical replace
- **AND** a streaming copy SHALL be used with the data flushed to disk (fsync) and a warning logged
- **AND** a recoverable backup SHALL already exist

#### Scenario: Reflex toggle works on a standalone Docker bind mount
- **WHEN** the Reflex toggle is used and `config.yaml` is a single-file bind mount
- **THEN** the toggle SHALL persist the value and return success

### Requirement: A failed write does not report success
If a config write is aborted (validation failure, persistence-guard failure or write error), the originating operation SHALL NOT report success.

#### Scenario: Aborted save surfaces an error
- **WHEN** the UI save's underlying write is aborted and the file is not updated
- **THEN** the `POST /api/config/save` endpoint SHALL return an error rather than a success status

## ADDED Requirements

### Requirement: Writes through a symlink update the real file
When `config.yaml` is a symlink, the writer SHALL resolve it and write to the link's real target. The symlink SHALL remain a symlink pointing to the same target after the write.

#### Scenario: Add-on save persists across restart
- **WHEN** `/app/config.yaml` is a symlink to `/config/darkstar/config.yaml` and a user saves settings
- **THEN** `/config/darkstar/config.yaml` SHALL contain the saved settings
- **AND** `/app/config.yaml` SHALL still be a symlink to `/config/darkstar/config.yaml`
- **AND** the temporary and `.bak` files SHALL be created in `/config/darkstar/`

### Requirement: Config writes are durable
The writer SHALL flush and fsync the temporary file before the atomic replace, and SHALL fsync the containing directory after the replace (best-effort where the filesystem does not support directory fsync).

#### Scenario: Power loss after a reported save
- **WHEN** a save has returned success
- **THEN** the new content SHALL already have been fsynced to the persistent filesystem

### Requirement: Config read-modify-write is serialized
All runtime config mutations SHALL run their read-modify-write under one process-wide lock, so concurrent writers cannot overwrite each other's changes.

#### Scenario: Concurrent writers do not lose updates
- **WHEN** two writers change different keys concurrently (e.g. a UI save and the Reflex learning engine)
- **THEN** the final `config.yaml` SHALL contain both changes

### Requirement: Add-on writes must target persistent storage
When running as the Home Assistant add-on (`SUPERVISOR_TOKEN` set), the writer SHALL refuse to write if the resolved target is not under `/config/darkstar/`, log an error, and report failure.

#### Scenario: Ephemeral target is refused
- **WHEN** running as the add-on and the resolved config target is outside `/config/darkstar/`
- **THEN** no write SHALL occur
- **AND** the originating endpoint SHALL return an error explaining that the config is not on persistent storage
