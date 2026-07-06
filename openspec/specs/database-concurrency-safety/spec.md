# Database Concurrency Safety

## Purpose
This specification defines database concurrency safeguards for startup initialization, FastAPI request handling, and SQLite read paths.

## Requirements

### Requirement: WAL mode is enabled at application startup

The application SHALL place `planner_learning.db` into SQLite WAL journal mode during startup, independent of whether the executor is enabled, so that concurrent readers and writers do not block each other.

#### Scenario: WAL enabled on startup regardless of executor state
- **WHEN** the backend starts and initializes the `LearningStore`
- **THEN** the startup sequence enables WAL mode on `planner_learning.db`
- **AND** this occurs even when `executor.config.enabled` is false

#### Scenario: Fresh database opens in WAL mode
- **WHEN** the application starts against a newly created `planner_learning.db`
- **THEN** the database journal mode is WAL before the recorder, planner, or ML training issue any query

### Requirement: Synchronous database reads do not block the event loop

API request handlers SHALL NOT perform synchronous SQLite or ORM reads directly on the FastAPI event loop; such reads SHALL run off the loop (e.g. via a worker thread) so that one query cannot stall unrelated requests.

#### Scenario: Price-forecast routes offload sync DB work
- **WHEN** a price-forecast or price-outlook route executes a synchronous SQLite query
- **THEN** the query runs off the event loop
- **AND** other concurrent requests are not blocked for the query duration

#### Scenario: Executor-history routes offload sync DB work
- **WHEN** an executor history or stats route executes a synchronous ORM read
- **THEN** the read runs off the event loop

### Requirement: Database connections use a bounded busy-timeout

SQLite connections opened by the price-forecast read paths SHALL set an explicit busy-timeout rather than relying on the short default, so that a brief lock held by another writer does not immediately raise `database is locked`.

#### Scenario: Price connection sets an explicit timeout
- **WHEN** a price-forecast or price-outlook route opens a `sqlite3` connection
- **THEN** the connection is opened with an explicit busy-timeout of 30 seconds
- **AND** it does not rely on SQLite's ~5 second default

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
