## ADDED Requirements

### Requirement: Database snapshot download
The system SHALL provide a download of `planner_learning.db` as a transactionally consistent snapshot taken with SQLite's online backup, without stopping Darkstar and without blocking other requests or the recorder.

#### Scenario: Snapshot while Darkstar is running
- **WHEN** a user requests the database snapshot while the recorder is writing to the database
- **THEN** the response is a single SQLite file that opens without error and passes `PRAGMA integrity_check`
- **AND** Darkstar keeps running and other requests are served during the copy

#### Scenario: Snapshot includes recent writes
- **WHEN** rows have been written to the WAL file but not yet checkpointed
- **THEN** the snapshot contains those rows

#### Scenario: Snapshot is read-only toward the live database
- **WHEN** the snapshot is taken
- **THEN** the live database is opened read-only and its contents are unchanged

#### Scenario: Temporary file is removed
- **WHEN** the snapshot response has finished or failed
- **THEN** no temporary snapshot file remains on disk

#### Scenario: Database missing or copy fails
- **WHEN** the database file does not exist or the backup fails
- **THEN** the request fails with an HTTP error and a clear message, and no partial file is served

### Requirement: Diagnostics bundle download
The system SHALL provide a single zip download containing a consistent snapshot of `planner_learning.db`, `config.yaml` exactly as stored on disk, the log file, `schedule.json`, the JSON output of the version, status, health and monitors endpoints, and a `manifest.json`.

#### Scenario: Bundle contents
- **WHEN** a user requests the diagnostics bundle on a healthy system
- **THEN** the zip contains `planner_learning.db`, `config.yaml`, `darkstar.log`, `schedule.json`, `version.json`, `status.json`, `health.json`, `monitors.json` and `manifest.json`

#### Scenario: Config is exported as is
- **WHEN** the bundle is created
- **THEN** `config.yaml` in the zip is byte-identical to the file on disk

#### Scenario: Secrets file is never included
- **WHEN** the bundle is created
- **THEN** it contains no file derived from `secrets.yaml`

#### Scenario: Database is in the bundle
- **WHEN** the bundle is created while Darkstar is running
- **THEN** the `planner_learning.db` inside the zip opens without error and passes `PRAGMA integrity_check`
- **AND** it is a consistent snapshot, the same as the standalone database download

#### Scenario: One item fails
- **WHEN** an item is missing or its source fails, for example `schedule.json` does not exist or Home Assistant is unreachable for status
- **THEN** the bundle is still returned with the remaining items
- **AND** `manifest.json` lists that item with the reason it is missing

#### Scenario: Manifest content
- **WHEN** the bundle is created
- **THEN** `manifest.json` records the Darkstar version, the export time in UTC, and for every item either that it is included or the error

### Requirement: Export file naming
Exported files SHALL carry a UTC timestamp in their file name, and the bundle name SHALL also carry the Darkstar version.

#### Scenario: Distinct names
- **WHEN** a user exports twice
- **THEN** the two downloads have different file names

### Requirement: One export at a time
The system SHALL allow only one database snapshot or diagnostics bundle to run at once, since both run the database backup.

#### Scenario: Second request while one is running
- **WHEN** a snapshot or bundle is in progress and another snapshot or bundle is requested
- **THEN** the second request is rejected with HTTP 409

### Requirement: Config download is the raw file
The existing configuration download SHALL return `config.yaml` exactly as stored on disk, without rebuilding, merging or removing any content.

#### Scenario: Byte-identical download
- **WHEN** a user downloads the configuration
- **THEN** the response body is byte-identical to `config.yaml` on disk, including comments and key order

#### Scenario: Secrets file not involved
- **WHEN** a user downloads the configuration
- **THEN** `secrets.yaml` is not read

#### Scenario: Config file missing
- **WHEN** `config.yaml` does not exist
- **THEN** the request fails with HTTP 404

### Requirement: Debug page buttons
The Debug page SHALL show a "Database" download button and an "Export bundle" button next to the existing Logs and Config buttons, and the Logs and Config buttons SHALL keep working. The toolbar SHALL wrap onto additional rows when it does not fit, and button text SHALL never wrap or compress.

#### Scenario: Buttons present
- **WHEN** the Debug page is opened
- **THEN** the Database and Export bundle buttons are visible beside Logs and Config

#### Scenario: Buttons work behind Home Assistant ingress
- **WHEN** a button is clicked inside the Home Assistant add-on panel
- **THEN** the file downloads using a relative URL, like the existing Logs and Config buttons

#### Scenario: Narrow toolbar
- **WHEN** the toolbar does not fit the card width
- **THEN** it wraps onto a second row and no button label wraps or is compressed

### Requirement: Download progress feedback
The Database and Export bundle buttons SHALL download via fetch and show progress from click until the file has been handed to the browser or the request has failed.

#### Scenario: Busy state
- **WHEN** a user clicks Database or Export bundle
- **THEN** the clicked button shows a spinner and the label "Preparing…" or "Exporting…", and both buttons are disabled until the download is delivered or fails

#### Scenario: Double click
- **WHEN** a click happens while a download is in progress
- **THEN** no second request is sent

#### Scenario: Failure
- **WHEN** the request fails (network error, HTTP error, or HTTP 409 because another export is running)
- **THEN** an error toast with a readable message is shown, the buttons are enabled again, and no file is saved
