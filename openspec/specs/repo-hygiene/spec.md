## Purpose
Keeps the repository free of stray debug dumps, editor backups and unused tooling so tracked files are all intentional.

## Requirements

### Requirement: No stray tracked files
The repository SHALL NOT track `history_debug_dump.json`, `msg_bad`, `data/history.db`, `frontend/package.json.bak`, the `frontend/lint*.txt` output dumps, or the unused `conductor/` directory.

#### Scenario: Listing tracked files
- **WHEN** `git ls-files` is run
- **THEN** none of the listed paths appear

### Requirement: Ignore rules cover leftovers
Ignore rules SHALL prevent re-adding backup files, runtime databases and lint output dumps, adding patterns only where existing ones do not already cover them.

#### Scenario: Recreated lint dump
- **WHEN** a lint output text file is recreated in `frontend/`
- **THEN** git reports it as ignored

### Requirement: Backlog reflects reality
`docs/BACKLOG.md` SHALL NOT list work that is complete: the test gaps (updater, E2E), the missing tested marker and the outside-contributor readiness entries are removed, and other entries are unchanged.

#### Scenario: Reading the backlog
- **WHEN** the backlog is read after this change
- **THEN** the three entries are gone and all others remain
