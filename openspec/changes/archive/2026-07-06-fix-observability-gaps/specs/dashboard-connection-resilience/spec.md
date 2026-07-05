## ADDED Requirements

### Requirement: Dashboard reconnects indefinitely

The dashboard WebSocket client SHALL attempt to reconnect indefinitely after a lost connection, rather than giving up after a fixed number of attempts. Reconnection backoff SHALL remain bounded (delay capped) so reconnection storms are avoided.

#### Scenario: Backend unavailable longer than the old attempt limit

- **WHEN** the backend is unreachable for longer than the previous ~50 s / 10-attempt limit while a dashboard tab is open
- **THEN** the client keeps retrying and reconnects automatically once the backend returns, without a manual page reload

### Requirement: Dashboard refetches state on reconnect

When the WebSocket reconnects after a drop, the dashboard SHALL refetch the full state bundle so any events missed during the outage are reconciled.

#### Scenario: Reconnect after a drop

- **WHEN** the socket fires a reconnect/connect event after having been disconnected
- **THEN** the dashboard re-runs the full state fetch (the same bundle loaded on initial mount), replacing any values that went stale during the outage

### Requirement: Dashboard shows connection liveness

The dashboard SHALL expose the WebSocket connection state to the UI and display a visible indicator distinguishing "live" from "stale/disconnected", so a frozen tab is never mistaken for live data.

#### Scenario: Connection is live

- **WHEN** the socket is connected
- **THEN** the indicator shows a live state

#### Scenario: Connection is lost

- **WHEN** the socket is disconnected or actively retrying to reconnect
- **THEN** the indicator shows a stale/disconnected state so the operator knows the displayed numbers may be out of date
