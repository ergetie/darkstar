## ADDED Requirements

### Requirement: All schedule writers persist atomically
Every code path that writes `schedule.json` SHALL persist the file atomically: write to a temporary file in the target's own directory, then atomically replace the target. No writer SHALL open the live schedule file in truncating write mode (`"w"`) and stream content into it.

#### Scenario: Planner output uses the atomic writer
- **WHEN** the planner saves a generated schedule
- **THEN** the write SHALL go through the shared atomic JSON helper (temp file in the target directory, then atomic replace)
- **AND** the live schedule file SHALL NOT be opened in `"w"` truncating mode by the planner

#### Scenario: Manual override save uses the atomic writer
- **WHEN** a user saves manual overrides via `POST /api/schedule/save`
- **THEN** the write SHALL go through the same atomic JSON helper
- **AND** the live schedule file SHALL NOT be opened in `"w"` truncating mode by the save handler

#### Scenario: A concurrent reader never observes a partial file
- **WHEN** a reader opens the schedule file while a writer is mid-write
- **THEN** the reader SHALL observe either the complete previous file or the complete new file
- **AND** the reader SHALL NOT observe truncated or partially written JSON

#### Scenario: Crash mid-write leaves the previous schedule intact
- **WHEN** a schedule write is interrupted before the atomic replace completes
- **THEN** the live schedule file SHALL retain its previous complete contents
- **AND** no empty or partially written schedule file SHALL be left in place

#### Scenario: A failed serialization does not replace the target
- **WHEN** JSON serialization raises while writing the temporary file
- **THEN** the temporary file SHALL be removed
- **AND** the live schedule file SHALL be left unchanged

### Requirement: The schedule directory supports atomic replace without a streaming fallback
The schedule file lives in a directory-level persistent volume, where a temporary file in the same directory renames within the same filesystem. The schedule writer SHALL perform a plain atomic replace and SHALL NOT implement a non-atomic streaming-copy fallback.

#### Scenario: Replace happens within the target directory
- **WHEN** the atomic helper writes the schedule
- **THEN** the temporary file SHALL be created in the target file's own directory
- **AND** the replace SHALL be performed with `os.replace` onto the target

#### Scenario: No streaming-copy fallback path exists
- **WHEN** the schedule writer implementation is inspected
- **THEN** it SHALL NOT contain an `EXDEV`/`EBUSY`/`ETXTBSY` streaming-copy fallback
- **AND** a replace failure SHALL surface as an error rather than degrading to a non-atomic copy

### Requirement: A guard test prevents reintroducing non-atomic schedule writes
The test suite SHALL fail when any non-test module opens the schedule file in truncating write mode, so a future writer cannot silently reintroduce the torn-read defect.

#### Scenario: Guard fails on a new truncating writer
- **WHEN** a module outside the test suite opens the schedule path with mode `"w"`
- **THEN** the guard test SHALL fail and name the offending file
