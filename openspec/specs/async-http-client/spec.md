# Capability: Async HTTP Client

## Purpose

Provides non-blocking HTTP communication between the Darkstar executor and Home Assistant API, preventing system freezes when HA becomes unresponsive.

## Requirements

### Requirement: Async HTTP client for Home Assistant API

The async HTTP client SHALL provide non-blocking HTTP communication with Home Assistant API.

#### Scenario: Successful async request
- **WHEN** the executor requests an entity state from Home Assistant
- **THEN** the request SHALL be made asynchronously without blocking the event loop
- **AND** the response SHALL be returned within 5 seconds

#### Scenario: Timeout handling
- **WHEN** Home Assistant does not respond within 5 seconds
- **THEN** the client SHALL raise a timeout exception
- **AND** the executor SHALL continue processing the next tick

#### Scenario: Connection pooling
- **WHEN** multiple requests are made to the same Home Assistant instance
- **THEN** the client SHALL reuse connections from a connection pool
- **AND** connection overhead SHALL be minimized

### Requirement: Backward compatibility with configuration

The async HTTP client SHALL use the same configuration as the existing sync client.

#### Scenario: Existing configuration works
- **WHEN** the executor starts with existing `config.yaml`
- **THEN** the async client SHALL connect to the same Home Assistant URL
- **AND** use the same authentication token
- **AND** require no configuration changes

### Requirement: Proper exception handling

The async HTTP client SHALL handle exceptions gracefully and provide meaningful error messages.

#### Scenario: Network error handling
- **WHEN** a network error occurs during the request
- **THEN** the client SHALL raise an appropriate exception
- **AND** the error message SHALL include the entity ID and error type

#### Scenario: HTTP error handling
- **WHEN** Home Assistant returns a 4xx or 5xx status code
- **THEN** the client SHALL raise an exception with the status code
- **AND** the error details SHALL be available for logging

### Requirement: Timeout configuration

The async HTTP client SHALL support configurable timeouts with sensible defaults.

#### Scenario: Default timeout
- **WHEN** no timeout is configured
- **THEN** the client SHALL use a 5-second timeout for all requests

#### Scenario: Custom timeout
- **WHEN** a custom timeout is configured in config.yaml
- **THEN** the client SHALL use the configured timeout value
- **AND** timeout SHALL be applied to all HTTP operations

### Requirement: Event loop isolation for async HTTP clients

Async HTTP clients SHALL NOT be shared across different event loops to prevent event loop corruption.

#### Scenario: Cross-thread event loop safety
- **WHEN** an async HTTP client is created in one event loop (e.g., FastAPI main thread)
- **AND** the same client instance is used from a different event loop (e.g., executor background thread)
- **THEN** the client SHALL either be created fresh for each event loop
- **OR** use thread-safe mechanisms that prevent event loop binding issues

#### Scenario: Executor thread isolation
- **WHEN** the executor runs in a background thread with its own event loop
- **AND** the executor makes HTTP requests to Home Assistant
- **THEN** the HTTP client SHALL NOT share internal asyncio state with clients from other threads
- **AND** requests SHALL complete without "bound to a different event loop" errors

#### Scenario: FastAPI and executor coexistence
- **WHEN** both FastAPI API handlers and the executor make concurrent HTTP requests
- **THEN** each SHALL use independent HTTP client instances
- **AND** neither SHALL interfere with the other's event loop
- **AND** both SHALL receive correct responses from Home Assistant

### Requirement: Home Assistant HTTP client is shared within an event loop

The application SHALL maintain one `httpx.AsyncClient` per running event loop for Home Assistant requests: created lazily on first use within that loop, reused for all subsequent requests in the same loop so that connections are pooled and the TLS/CA trust context is loaded only once, and closed when the application shuts down. The client SHALL NOT be shared across different event loops — the main server loop and any background executor loop SHALL each own a separate client instance, satisfying the event-loop isolation requirement above.

#### Scenario: Repeated reads reuse one client within a loop
- **WHEN** an endpoint performs multiple Home Assistant entity reads within the same event loop (e.g. the health check reads many entities in one request)
- **THEN** all reads use the same shared client instance for that loop
- **AND** the TLS/CA trust store is not reloaded per read
- **AND** connections to the Home Assistant host are reused from the pool

#### Scenario: Client created on first use
- **WHEN** the first Home Assistant request is made in a given event loop after startup
- **THEN** the per-loop client is created and cached for subsequent use within that loop

#### Scenario: Client closed on shutdown
- **WHEN** the application shuts down
- **THEN** each per-loop client SHALL be closed and its connection-pool resources released
- **AND** no connection-pool leak SHALL occur

#### Scenario: Per-call behavior preserved
- **WHEN** a request is made through the shared per-loop client
- **THEN** existing timeout and error-handling behavior is unchanged
- **AND** the same Home Assistant URL and token from configuration are used
