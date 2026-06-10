# Spec: Durable Config Write

## Purpose

Defines durable write behavior for `config.yaml` so startup migration and UI saves cannot leave the live config truncated, partially written, or falsely reported as saved.

## Requirements

### Requirement: All config writers persist atomically
Every code path that writes `config.yaml` (startup migration and the UI save endpoint) SHALL persist the file atomically: write to a temporary file on the same filesystem as the target, then atomically replace the target. No writer SHALL open the live config file in truncating write mode (`"w"`) and stream content directly into it.

#### Scenario: UI save uses the atomic writer
- **WHEN** a user saves configuration via `POST /api/config` and validation passes
- **THEN** the save SHALL write through the atomic `_write_config` helper (temp file + atomic replace)
- **AND** the live `config.yaml` SHALL NOT be opened in `"w"` truncating mode by the save handler

#### Scenario: Crash mid-write never truncates the live file
- **WHEN** any config write is interrupted before the atomic replace completes
- **THEN** the live `config.yaml` SHALL retain its previous complete contents
- **AND** no empty or partially-written `config.yaml` SHALL be left in place

### Requirement: A backup exists before any overwrite
Before overwriting an existing `config.yaml`, the writer SHALL create a timestamped backup in the persistent backup directory.

#### Scenario: UI save creates a backup
- **WHEN** a user saves configuration and a `config.yaml` already exists
- **THEN** a timestamped backup of the prior config SHALL be created before the new content is written

#### Scenario: Backups are retention-pruned
- **WHEN** a backup is created and more than the retention limit exist
- **THEN** the oldest backups beyond the limit SHALL be removed

### Requirement: Bind-mount writes remain atomic
On filesystems where an atomic replace across devices is not possible (e.g. Docker bind mounts that raise `EXDEV`/`EBUSY`/`ETXTBSY`), the writer SHALL keep the temporary file within the target's own directory and perform the atomic replace within that filesystem. A non-atomic streaming copy SHALL NOT be the primary fallback.

#### Scenario: Bind-mount path replaces within the same filesystem
- **WHEN** the target config lives on a bind mount and the temp file is in the same directory
- **THEN** the write SHALL complete via an atomic replace within that filesystem
- **AND** the live config SHALL NOT be truncated by a streaming copy

#### Scenario: Last-resort copy is flushed and guarded
- **WHEN** an atomic replace genuinely cannot be performed on the mount
- **THEN** a streaming copy MAY be used only as a last resort
- **AND** the data SHALL be flushed to disk (fsync) and a warning SHALL be logged
- **AND** a recoverable backup SHALL already exist

### Requirement: A failed write does not report success
If a config write is aborted (validation failure or write error), the originating operation SHALL NOT report success.

#### Scenario: Aborted save surfaces an error
- **WHEN** the UI save's underlying write is aborted and the file is not updated
- **THEN** the `POST /api/config` endpoint SHALL return an error rather than a success status
