# Delta: router-structure

## MODIFIED Requirements

### Requirement: Router files are organized by domain
Each API router file in `backend/api/routers/` SHALL contain endpoints for a single semantic domain. A router file MUST NOT mix unrelated domains (e.g., Home Assistant integration and energy data queries).

#### Scenario: HA integration endpoints live in ha.py
- **WHEN** a developer looks for Home Assistant integration endpoints
- **THEN** all HA endpoints (entity state, average, entities list, services list, connection test, WebSocket status) are found in `backend/api/routers/ha.py`

#### Scenario: Energy data endpoints live in energy.py
- **WHEN** a developer looks for energy data endpoints
- **THEN** all energy endpoints (energy/today, energy/range, performance/data) are found in `backend/api/routers/energy.py`

#### Scenario: Water heating endpoints live in water.py
- **WHEN** a developer looks for water heating control endpoints
- **THEN** all water boost endpoints (GET, POST, DELETE) are found in `backend/api/routers/water.py`

### Requirement: URL paths are preserved exactly
All endpoint URL paths MUST remain identical after the split. No URL path SHALL change as a result of this refactoring.

#### Scenario: Route preservation
- **WHEN** the application starts after the split
- **THEN** all of the following routes are registered: `GET /api/ha/entity/{entity_id}`, `GET /api/ha/average`, `GET /api/ha/entities`, `GET /api/ha/services`, `POST /api/ha/test`, `GET /api/water/boost`, `POST /api/water/boost`, `DELETE /api/water/boost`, `GET /api/energy/today`, `GET /api/energy/range`, `GET /api/performance/data`, `GET /api/ha-socket`
- **AND** each path resolves to the same handler logic as before
