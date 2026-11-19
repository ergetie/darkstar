# Spec Delta

## Purpose
Prevent websites open in a user's browser from driving Darkstar's write API or reading its live Socket.IO feed, without breaking Home Assistant ingress, scripts or the dev proxy.

## ADDED Requirements

### Requirement: Browser cross-site writes are rejected
The system SHALL reject POST, PUT, PATCH and DELETE requests with HTTP 403 when the `Sec-Fetch-Site` header is `cross-site` or `same-site`, and SHALL accept them when the header is `same-origin`, `none` or absent. Safe methods SHALL always pass.

#### Scenario: Cross-site POST blocked
- **WHEN** a POST to a write route carries `Sec-Fetch-Site: cross-site`
- **THEN** the response is 403 and no state is changed

#### Scenario: Same-origin and script writes allowed
- **WHEN** a POST carries `Sec-Fetch-Site: same-origin`, `none`, or no such header
- **THEN** the request is processed normally

#### Scenario: Same-site blocked
- **WHEN** a PUT carries `Sec-Fetch-Site: same-site`
- **THEN** the response is 403

### Requirement: No permissive CORS
The system SHALL NOT emit `Access-Control-Allow-Origin` headers on any HTTP or Socket.IO response.

#### Scenario: No ACAO header
- **WHEN** any request carries an `Origin` header
- **THEN** the response has no `Access-Control-Allow-Origin` header

### Requirement: Socket.IO handshake follows the same rule
The system SHALL reject WebSocket and engine.io polling-write handshakes whose `Sec-Fetch-Site` is `cross-site` or `same-site`.

#### Scenario: Cross-site handshake rejected
- **WHEN** a Socket.IO connection is attempted with `Sec-Fetch-Site: cross-site`
- **THEN** the connection is refused

#### Scenario: Same-origin handshake accepted
- **WHEN** a Socket.IO connection is attempted with `Sec-Fetch-Site: same-origin`
- **THEN** the connection is established

### Requirement: Typed request bodies
The executor config, executor notifications and briefing endpoints SHALL validate their bodies through typed models and answer 422 for invalid JSON.

#### Scenario: Invalid JSON
- **WHEN** a non-JSON body is sent to PUT `/api/executor/config`
- **THEN** the response is 422
