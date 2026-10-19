# Spec: Input Module Structure

## Purpose

Defines the structure and responsibilities of the four input modules under `backend/core/`: `secrets.py`, `ha_client.py`, `prices.py`, and `forecasts.py`. These modules replace the legacy root-level `inputs.py` file, providing a clean dependency hierarchy and explicit import paths.

## Requirements

### Requirement: Secrets module provides config/secrets loading

`backend/core/secrets.py` SHALL contain all YAML configuration and secrets loading functions. It SHALL export the following public functions with signatures identical to the current `inputs.py`:
- `load_yaml(path: str) -> dict[str, Any]`
- `load_home_assistant_config() -> dict[str, Any]`
- `load_notifications_config() -> dict[str, Any]`

This module SHALL have no imports from other `backend.core` modules (it is the dependency root).

#### Scenario: load_yaml returns parsed config
- **WHEN** `load_yaml("config.yaml")` is called with a valid YAML file path
- **THEN** the function returns a dict with the parsed YAML content, identical to the current behavior

#### Scenario: load_home_assistant_config reads from secrets
- **WHEN** `load_home_assistant_config()` is called
- **THEN** the function returns the `home_assistant` section from `secrets.yaml`, or an empty dict if not found

#### Scenario: load_notifications_config reads from secrets
- **WHEN** `load_notifications_config()` is called
- **THEN** the function returns the `notifications` section from `secrets.yaml`, or an empty dict if not found

---

### Requirement: HA client module provides Home Assistant sensor access
`backend/core/ha_client.py` SHALL contain all Home Assistant HTTP client functions. It SHALL export the following public functions with signatures identical to the current `inputs.py`, as listed in the scenarios below.

#### Scenario: HA client public function signatures preserved
- **WHEN** the HA client module is imported
- **THEN** it SHALL export the following functions with signatures identical to the current `inputs.py`:
  - `make_ha_headers(token: str) -> dict[str, str]`
  - `get_ha_entity_state(entity_id: str) -> dict[str, Any] | None`
  - `get_ha_sensor_float(entity_id: str) -> float | None`
  - `get_ha_sensor_kw_normalized(entity_id: str) -> float | None`
  - `get_ha_bool(entity_id: str) -> bool`
  - `get_load_profile_from_ha(config: dict[str, Any]) -> list[float]`
  - `get_initial_state(config: ...) -> dict`
  - `get_dummy_load_profile(config: dict[str, Any]) -> list[float]`

#### Scenario: HA client private helper and secrets access
- **WHEN** the `inputs.py` split is carried out
- **THEN** the private helper `_normalize_energy_to_kwh` SHALL also move to the HA client module
- **AND** the module SHALL import from `backend.core.secrets` using module-level reference (`from backend.core import secrets`)
- **AND** it SHALL call `secrets.load_yaml()`, `secrets.load_home_assistant_config()` etc. via attribute access, NOT via `from backend.core.secrets import load_yaml`

#### Scenario: HA sensor functions use secrets module for config
- **WHEN** any HA client function needs Home Assistant configuration
- **THEN** it calls `secrets.load_home_assistant_config()` from the secrets module

#### Scenario: All HA functions maintain identical signatures
- **WHEN** any HA client function is called with the same arguments as before the refactor
- **THEN** it returns identical results

---

### Requirement: Prices module provides Nordpool electricity pricing
`backend/core/prices.py` SHALL contain all electricity price fetching functions. It SHALL export the following public functions with signatures identical to the current `inputs.py`:
- `get_nordpool_data(config_path: str = "config.yaml") -> list[dict[str, Any]]`
- `calculate_import_export_prices(...) -> ...` (same signature)
- `get_current_slot_prices(config: dict[str, Any]) -> dict[str, float] | None`

#### Scenario: Prices module private helper and secrets access
- **WHEN** the `inputs.py` split is carried out
- **THEN** the private helper `_process_nordpool_data` SHALL also move to the prices module
- **AND** the module SHALL import from `backend.core.secrets` using module-level reference

#### Scenario: Nordpool data fetching works identically
- **WHEN** `get_nordpool_data()` is called
- **THEN** it returns the same Nordpool price data structure as before the refactor

#### Scenario: Price calculations are unchanged
- **WHEN** `calculate_import_export_prices()` is called with the same arguments
- **THEN** it returns identical results

---

### Requirement: Forecasts module provides PV/load forecast orchestration
`backend/core/forecasts.py` SHALL contain all forecast-related functions. It SHALL export the following public functions with signatures identical to the current `inputs.py`:
- `get_forecast_data(config: ...) -> ...`
- `get_all_input_data(config_path: str = ...) -> ...`
- `get_db_forecast_slots(db_path: ...) -> ...`
- `build_db_forecast_for_slots(config: ...) -> ...`

#### Scenario: Forecasts module private helpers and imports
- **WHEN** the `inputs.py` split is carried out
- **THEN** the private helpers `_interpolate_small_gaps`, `_get_forecast_data_aurora` and `_get_forecast_data_async` SHALL also move to the forecasts module
- **AND** the module SHALL import from `backend.core.secrets`, `backend.core.ha_client`, and `backend.core.prices` using module-level references

#### Scenario: get_all_input_data orchestrates all data sources
- **WHEN** `get_all_input_data()` is called
- **THEN** it gathers prices, forecasts, load profiles, and initial state identically to before

#### Scenario: Forecast functions maintain identical signatures
- **WHEN** any forecast function is called with the same arguments
- **THEN** it returns identical results

---

### Requirement: No remaining root-level inputs module

After migration is complete, the file `inputs.py` at the project root SHALL be deleted. No file in the repository SHALL contain `from inputs import` or `import inputs`.

#### Scenario: Root inputs.py is removed
- **WHEN** the migration is complete
- **THEN** `inputs.py` does not exist at the project root

#### Scenario: No legacy imports remain
- **WHEN** a grep for `from inputs import` or `import inputs` is run across all `.py` files
- **THEN** zero matches are found

---

### Requirement: All imports use full module paths

All consuming files SHALL use explicit full import paths to the specific module (e.g., `from backend.core.secrets import load_yaml`, `from backend.core.prices import get_nordpool_data`). No consuming file SHALL import from a generic `backend.core` namespace or `__init__.py` re-export.

#### Scenario: Import paths are specific to each module
- **WHEN** a file needs `load_yaml`
- **THEN** it imports `from backend.core.secrets import load_yaml`

#### Scenario: Import paths for HA functions
- **WHEN** a file needs `get_ha_entity_state`
- **THEN** it imports `from backend.core.ha_client import get_ha_entity_state`

#### Scenario: Import paths for price functions
- **WHEN** a file needs `get_nordpool_data`
- **THEN** it imports `from backend.core.prices import get_nordpool_data`

#### Scenario: Import paths for forecast functions
- **WHEN** a file needs `get_all_input_data`
- **THEN** it imports `from backend.core.forecasts import get_all_input_data`

---

### Requirement: Test infrastructure patches the canonical module

`tests/conftest.py` SHALL patch `backend.core.secrets.load_yaml` instead of `inputs.load_yaml`. The session-scoped fixture SHALL use `patch.object` targeting the `backend.core.secrets` module.

#### Scenario: conftest patches secrets module
- **WHEN** the test session starts
- **THEN** `conftest.py` imports `backend.core.secrets` and patches `load_yaml` on that module using `patch.object(secrets_module, "load_yaml", mock_load_yaml)`

#### Scenario: Mock propagates to all consumers
- **WHEN** `backend.core.ha_client` calls `secrets.load_yaml()` during tests
- **THEN** it receives the mocked test config (because it uses attribute access on the module object)

---

### Requirement: Each new module has its own logger

Each new module SHALL create its own logger with a descriptive namespace:
- `backend/core/secrets.py`: `logging.getLogger("darkstar.core.secrets")`
- `backend/core/ha_client.py`: `logging.getLogger("darkstar.core.ha_client")`
- `backend/core/prices.py`: `logging.getLogger("darkstar.core.prices")`
- `backend/core/forecasts.py`: `logging.getLogger("darkstar.core.forecasts")`

#### Scenario: Logger namespaces are module-specific
- **WHEN** a log message is emitted from `backend/core/prices.py`
- **THEN** the logger name is `darkstar.core.prices`
