## ADDED Requirements

### Requirement: EV charger state is refetched on reconnect

When the WebSocket reconnects after a drop, the EV charger state (`GET /api/ev/chargers`) SHALL be refetched, including for the EV card on the dashboard's Energy Resources EV tab, so that goal, manual-charge, schedule and SoC data changed while the client was disconnected or suspended are reconciled. The initial connect on mount SHALL NOT trigger an additional fetch, and a reconnect SHALL trigger exactly one refetch. No fetch SHALL occur while EV is disabled.

#### Scenario: Reconnect after the app was suspended

- **WHEN** the socket status goes from `connected` to a non-connected state and back to `connected` while EV is enabled
- **THEN** `/api/ev/chargers` is requested once and the EV card shows the fresh response

#### Scenario: Reconnect with the Energy Resources EV tab open

- **WHEN** the EV tab of the Energy Resources card is shown and the socket drops and reconnects
- **THEN** `/api/ev/chargers` is requested once by the tab and the card shows the fresh response

#### Scenario: Initial connect

- **WHEN** the dashboard mounts and the socket connects for the first time
- **THEN** only the mount fetch of `/api/ev/chargers` occurs, with no extra reconnect fetch

#### Scenario: EV disabled

- **WHEN** the socket reconnects while EV is disabled
- **THEN** `/api/ev/chargers` is not requested
