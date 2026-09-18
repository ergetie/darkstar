## ADDED Requirements

### Requirement: At most one executor tick runs at a time
The executor SHALL run at most one tick concurrently across all entrants, including the scheduled background loop and the manual `POST /api/executor/run` endpoint. A second entrant arriving while a tick is in flight SHALL be rejected immediately rather than run in parallel.

#### Scenario: Manual trigger during a scheduled tick is rejected
- **WHEN** `POST /api/executor/run` arrives while a scheduled tick is in flight
- **THEN** the manual request SHALL NOT execute a second tick
- **AND** it SHALL return a result indicating the tick was skipped because one is already running

#### Scenario: Scheduled tick during a manual run is skipped
- **WHEN** the scheduled loop reaches its interval while a manual tick is in flight
- **THEN** the scheduled tick SHALL be skipped
- **AND** the loop SHALL continue to its next interval without waiting

#### Scenario: Concurrent ticks do not collide on database writes
- **WHEN** two tick entrants overlap in time
- **THEN** only one SHALL write `execution_log` and `slot_observations` for that tick
- **AND** no `database is locked` error SHALL arise from two ticks writing simultaneously

#### Scenario: The guard releases after a failed tick
- **WHEN** a tick raises an exception
- **THEN** the guard SHALL be released before the tick returns
- **AND** the next scheduled tick SHALL run normally

### Requirement: The tick guard is thread-safe across event loops
The scheduled loop runs in a background thread with its own event loop, while the manual endpoint runs on the main FastAPI event loop. The tick guard SHALL therefore be a thread-level lock acquired without blocking. It SHALL NOT be an `asyncio` primitive, which is bound to a single event loop and would never block the other entrant.

#### Scenario: Guard blocks an entrant from a different thread
- **WHEN** one tick is in flight in the executor's loop thread
- **AND** a second entrant calls the tick from a different thread
- **THEN** the second entrant SHALL be rejected

#### Scenario: A rejected entrant returns immediately
- **WHEN** an entrant is rejected because a tick is already running
- **THEN** it SHALL return without waiting for the in-flight tick to finish
- **AND** ticks SHALL NOT accumulate in a queue behind a slow tick

#### Scenario: The guard is not an asyncio primitive
- **WHEN** the executor tick guard implementation is inspected
- **THEN** it SHALL be a thread-level lock
- **AND** it SHALL be acquired in non-blocking mode

### Requirement: Rejected ticks are logged with a reason
A skipped tick SHALL be logged at warning level with the reason, so that a period of suppressed ticks is visible in the logs rather than silent.

#### Scenario: Skip emits a log line
- **WHEN** a tick entrant is rejected because one is already running
- **THEN** a warning SHALL be logged naming the reason
- **AND** the executor status SHALL record the skip reason
