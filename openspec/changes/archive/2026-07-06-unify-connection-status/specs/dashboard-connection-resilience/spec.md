## ADDED Requirements

### Requirement: Socket is eagerly initialized at app boot

The Socket.IO client singleton SHALL be initialized when the application root layout mounts, not deferred until a page that subscribes to socket events is visited. This ensures the connection state is meaningful on every route from first paint.

#### Scenario: User navigates directly to a non-dashboard route on fresh load

- **WHEN** the application loads with the initial route set to a page that does not subscribe to socket events (e.g. `/settings` or `/debug`)
- **THEN** the Socket.IO client singleton SHALL be created and begin connecting
- **AND** the connection state SHALL reflect the real WebSocket transport status, not a default "unknown" value

### Requirement: Connection state escalates to offline after sustained failure

The connection state SHALL escalate from `connecting` to `offline` when the socket has been in the `connecting` state for more than 10 seconds without a successful `connect` event. This distinguishes a transient reconnect blip from a sustained outage so the operator is not misled by a perpetually "connecting" indicator.

#### Scenario: Transient blip resolves within 10 seconds

- **WHEN** the socket disconnects and reconnects within 10 seconds
- **THEN** the state SHALL remain `connecting` during the blip
- **AND** the state SHALL return to `connected` on the `connect` event
- **AND** the state SHALL NOT pass through `offline`

#### Scenario: Sustained outage exceeds 10 seconds

- **WHEN** the socket has been in the `connecting` state for more than 10 seconds
- **THEN** the state SHALL escalate to `offline`
- **AND** the state SHALL remain `offline` until a `connect` event fires

#### Scenario: Escalation timer resets on each disconnect

- **WHEN** the socket disconnects, reconnects briefly, and disconnects again
- **THEN** the 10-second escalation timer SHALL restart on each `disconnect` event
- **AND** the state SHALL not carry over a stale timer from a prior disconnection

## REMOVED Requirements

### Requirement: Dashboard shows connection liveness

**Reason**: The liveness indicator is moving from the Dashboard page to the Sidebar so it is visible on every route, not only when the Dashboard is open. The state model is also expanding from a boolean (live/stale) to a tri-state (connecting/connected/offline) with a 10-second sustained-failure escalation, so the requirement's contract changes substantively.

**Migration**: Replaced by "Sidebar shows connection liveness" below, which covers the same user need (a frozen tab is never mistaken for live data) with the broader visibility and richer state model.

## ADDED Requirements

### Requirement: Sidebar shows connection liveness

The sidebar SHALL expose the WebSocket connection state to the operator via a small status dot visible on every route. The dot SHALL distinguish three states — `connecting` (grey, "Connecting…"), `connected` (green with glow, "System Online"), and `offline` (red, "System Offline — reconnecting") — so the operator can tell at a glance whether the displayed data is live, reconciling, or stale due to a sustained outage. No text label is shown; the state is conveyed by color and a tooltip on hover.

#### Scenario: Connection is live

- **WHEN** the socket is in the `connected` state
- **THEN** the sidebar dot SHALL be green with a glow effect
- **AND** the tooltip SHALL read "System Online"

#### Scenario: Connection is initially establishing or transiently reconnecting

- **WHEN** the socket is in the `connecting` state (initial boot or reconnect in progress, <10s elapsed)
- **THEN** the sidebar dot SHALL be grey
- **AND** the tooltip SHALL read "Connecting…"

#### Scenario: Connection has been down for a sustained period

- **WHEN** the socket is in the `offline` state (connecting for >10s without success)
- **THEN** the sidebar dot SHALL be red
- **AND** the tooltip SHALL read "System Offline — reconnecting"

#### Scenario: Indicator is visible on non-dashboard routes

- **WHEN** the user navigates to any route (e.g. `/settings`, `/debug`, `/aurora`)
- **THEN** the sidebar dot SHALL be rendered and reflect the current connection state
- **AND** the dot SHALL update in real time as the socket state changes, without a page reload
