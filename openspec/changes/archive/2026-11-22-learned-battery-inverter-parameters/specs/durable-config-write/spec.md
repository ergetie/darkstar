## MODIFIED Requirements

### Requirement: All config writers persist atomically
Every code path that writes `config.yaml` at runtime SHALL persist the file through the single shared config writer, which writes to a temporary file in the same directory as the resolved target and then atomically replaces the target. No writer SHALL open the live config file in truncating write mode (`"w"`), stream content directly into it, or copy over it outside the shared writer. Learning components SHALL NOT write `config.yaml`.

#### Scenario: Covered writer paths
- **WHEN** any of startup migration, the UI/wizard save endpoint, config reset, executor endpoints or theme selection writes `config.yaml`
- **THEN** it persists the file through the single shared config writer

#### Scenario: UI save uses the atomic writer
- **WHEN** a user saves configuration via `POST /api/config/save` and validation passes
- **THEN** the save SHALL write through the shared atomic writer (temp file + atomic replace)
- **AND** the live `config.yaml` SHALL NOT be opened in `"w"` truncating mode by the save handler

#### Scenario: Secondary writers use the atomic writer
- **WHEN** an executor settings endpoint, theme selection or config reset changes `config.yaml`
- **THEN** the change SHALL be persisted through the shared atomic writer

#### Scenario: Crash mid-write never truncates the live file
- **WHEN** any config write is interrupted before the atomic replace completes
- **THEN** the live `config.yaml` SHALL retain its previous complete contents
- **AND** no empty or partially-written `config.yaml` SHALL be left in place

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
- **WHEN** a settings write (formerly the Reflex toggle, now any single-key settings write such as a notification toggle) runs and `config.yaml` is a single-file bind mount
- **THEN** the write SHALL persist the value and return success

### Requirement: Config read-modify-write is serialized
All runtime config mutations SHALL run their read-modify-write under one process-wide lock, so concurrent writers cannot overwrite each other's changes.

#### Scenario: Concurrent writers do not lose updates
- **WHEN** two writers change different keys concurrently (e.g. a UI save and an executor settings update)
- **THEN** the final `config.yaml` SHALL contain both changes
