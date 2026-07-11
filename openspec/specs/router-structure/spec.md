# Router Structure

## Purpose

Conventions and requirements for how FastAPI router files are organized in `backend/api/routers/`.

## Requirements

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

### Requirement: Router naming follows project conventions
Each router file SHALL define router objects using `APIRouter()` with explicit `prefix` and `tags` parameters. Router variable names SHALL be `router` for the primary router. If a file needs a secondary router for a different URL prefix, it SHALL use a descriptive name (e.g., `router_misc`).

#### Scenario: Primary router uses standard name
- **WHEN** a router file defines its primary router
- **THEN** the variable is named `router`
- **AND** it has a `prefix` parameter matching its URL path
- **AND** it has a `tags` parameter for OpenAPI grouping

#### Scenario: Secondary router uses descriptive name
- **WHEN** a router file requires endpoints under a different URL prefix (e.g., ha.py needing both `/api/ha` and `/api` prefixes)
- **THEN** the secondary router uses a descriptive variable name (e.g., `router_misc`)
- **AND** both routers are registered separately in `main.py`

### Requirement: Each router file has its own logger
Each router file SHALL define a module-level logger using the naming convention `darkstar.api.<domain>` (e.g., `darkstar.api.ha`, `darkstar.api.energy`, `darkstar.api.water`).

#### Scenario: Logger naming convention
- **WHEN** a new router file `ha.py` is created
- **THEN** it defines `logger = logging.getLogger("darkstar.api.ha")`

### Requirement: All routers are registered in main.py
Every router exported from a router file MUST be registered in `backend/main.py` via `app.include_router()`. The `create_app()` function is the single source of truth for router registration.

#### Scenario: New routers replace old services routers
- **WHEN** the application starts
- **THEN** `main.py` registers `ha.router`, `ha.router_misc`, `energy.router`, and `water.router`
- **AND** does NOT register `services.router_ha` or `services.router_services`

### Requirement: No services.py shims or re-exports
After the split, `backend/api/routers/services.py` MUST NOT exist. There SHALL be no backwards-compatibility re-exports or stub files.

#### Scenario: Clean deletion
- **WHEN** the split is complete
- **THEN** `services.py` does not exist in `backend/api/routers/`
- **AND** no file imports from `backend.api.routers.services`

### Requirement: URL paths are preserved exactly
All endpoint URL paths MUST remain identical after the split. No URL path SHALL change as a result of this refactoring.

#### Scenario: Route preservation
- **WHEN** the application starts after the split
- **THEN** all of the following routes are registered: `GET /api/ha/entity/{entity_id}`, `GET /api/ha/average`, `GET /api/ha/entities`, `GET /api/ha/services`, `POST /api/ha/test`, `GET /api/water/boost`, `POST /api/water/boost`, `DELETE /api/water/boost`, `GET /api/energy/today`, `GET /api/energy/range`, `GET /api/performance/data`, `GET /api/ha-socket`
- **AND** each path resolves to the same handler logic as before

### Requirement: Route-preservation snapshot test exists
A permanent test SHALL verify that all expected routes are registered in the application. This test MUST be created BEFORE any endpoint code is moved and MUST pass both before and after the split.

#### Scenario: Snapshot test catches missing route
- **WHEN** a route is accidentally removed or its path changes
- **THEN** the route-preservation test fails
- **AND** the failure message identifies which specific route is missing

### Requirement: Endpoint smoke tests exist
Each relocated endpoint SHALL have a smoke test that calls the endpoint with mocked dependencies and verifies it returns a non-500 HTTP status code.

#### Scenario: Smoke test for a mocked endpoint
- **WHEN** the smoke test for `GET /api/ha/entities` runs
- **THEN** it calls the endpoint with HA client dependencies mocked
- **AND** verifies the response status code is not 500

#### Scenario: Smoke tests cover all relocated endpoints
- **WHEN** the full test suite runs
- **THEN** every endpoint that was in services.py has a corresponding smoke test
