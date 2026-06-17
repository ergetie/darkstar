## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Resource management for async HTTP clients

**Reason:** This requirement mandated a fresh `httpx.AsyncClient` per request using `async with` context managers and explicitly forbade a singleton/shared-client pattern. While it ensured clean resource cleanup, it caused redundant TLS/CA trust-store reloads and a measurable per-request performance cost from repeatedly creating and tearing down connection pools.

**Migration:** Replaced by the per-event-loop shared client introduced above. Each event loop holds one lazily-created client that is reused for all requests within that loop; resource cleanup (closing the client and releasing the connection pool) now happens explicitly on application shutdown.
