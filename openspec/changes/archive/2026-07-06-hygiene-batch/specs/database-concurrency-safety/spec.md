## ADDED Requirements

### Requirement: Executor history engine uses per-thread connections

The executor history SQLite engine SHALL use a per-thread connection pool rather than a single shared connection, so that the executor tick thread and FastAPI worker threads cannot interleave transactions on one connection's state.

#### Scenario: History engine does not use a single shared connection
- **WHEN** the executor history engine is created
- **THEN** it does not use `StaticPool` (a single shared connection)
- **AND** it opens a connection per thread while retaining `check_same_thread=False`, a 30 s busy-timeout, and idempotent WAL mode

#### Scenario: Concurrent tick write and API read do not corrupt state
- **WHEN** the executor tick thread writes execution history while an API worker thread reads it
- **THEN** each thread uses its own connection
- **AND** neither operation observes the other's partial transaction
