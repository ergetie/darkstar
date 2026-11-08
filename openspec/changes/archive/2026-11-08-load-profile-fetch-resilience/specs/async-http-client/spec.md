# Spec Delta

## ADDED Requirements

### Requirement: Home Assistant failures are logged with their exception type
Every log line and raised error that reports a failed Home Assistant request, including the history fetch and the executor retry loop, SHALL include the exception type and a description that is never empty. When the exception text is empty (as for timeouts), the description SHALL fall back to the exception's representation.

#### Scenario: Timeout has no text
- **WHEN** a request fails with an exception whose string is empty, such as a read timeout
- **THEN** the log line names the exception type, for example `ReadTimeout` or `TimeoutError`, and the line does not end in a bare colon or full stop

#### Scenario: Executor retries
- **WHEN** the executor retries a Home Assistant call after a failure
- **THEN** each retry log line contains the exception type and the attempt counter

#### Scenario: Retries exhausted
- **WHEN** all executor attempts fail
- **THEN** the final error carries the last exception's type and description, not only a generic message

#### Scenario: Error with text
- **WHEN** the exception has a message, such as a connection failure
- **THEN** the log contains the type and the message
