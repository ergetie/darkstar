# ha-discovery Specification

## Purpose
Expose Home Assistant connection testing, core configuration and registry-enriched entity discovery.

## Requirements

### Requirement: Connection test uses supplied credentials
`POST /api/ha/test` SHALL accept an optional JSON body `{url, token}`. When the body is present and the app is not running as the HA add-on, the system SHALL test exactly those credentials and SHALL NOT persist them. Without a body, or in add-on mode, it SHALL test the active saved/Supervisor credentials.

#### Scenario: Standalone first run with typed credentials
- **WHEN** no HA credentials are saved and the user posts a valid `{url, token}`
- **THEN** the response SHALL report `status: "success"` with the HA version
- **AND** `secrets.yaml` SHALL be unchanged

#### Scenario: Wrong token
- **WHEN** the posted token is rejected by HA
- **THEN** the response SHALL report `status: "error"` with a message identifying an authentication failure

#### Scenario: Add-on ignores body
- **WHEN** running with `SUPERVISOR_TOKEN` set and a body is posted
- **THEN** the Supervisor credentials SHALL be tested instead of the body values

### Requirement: HA core config is exposed
The system SHALL provide `GET /api/ha/core-config` returning HA's `latitude`, `longitude`, `time_zone`, `currency`, `country` and `unit_system`. It SHALL NOT return a price-area guess.

#### Scenario: Core config returned
- **WHEN** HA is reachable
- **THEN** the response SHALL contain the six fields with HA's values
- **AND** the response SHALL NOT contain any price-area field

#### Scenario: HA unreachable
- **WHEN** HA cannot be reached
- **THEN** the endpoint SHALL return HTTP 502 with an error message and SHALL NOT raise an unhandled exception

### Requirement: Registry-enriched entity discovery
The system SHALL provide `GET /api/ha/discovery` returning every entity with `entity_id`, `friendly_name`, `domain`, `state`, `unit_of_measurement`, `device_class`, `state_class`, `platform`, `device_id`, `manufacturer` and `model`, plus a top-level `registry_available` flag. Registry data SHALL come from the HA websocket commands `config/entity_registry/list` and `config/device_registry/list`, joined via `device_id`.

#### Scenario: Registry available
- **WHEN** the websocket registry commands succeed
- **THEN** each entity linked to a device SHALL include that device's `manufacturer` and `model`
- **AND** `registry_available` SHALL be `true`

#### Scenario: Registry unavailable
- **WHEN** the registry commands fail (auth, permission, timeout)
- **THEN** the endpoint SHALL still return state-derived entities with `platform`, `device_id`, `manufacturer`, `model` set to `null`
- **AND** `registry_available` SHALL be `false`

#### Scenario: Registry result caching
- **WHEN** discovery is called twice within 60 seconds
- **THEN** the registry SHALL be fetched from HA only once
