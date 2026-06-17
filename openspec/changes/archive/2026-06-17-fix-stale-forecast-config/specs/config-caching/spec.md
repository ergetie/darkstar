## ADDED Requirements

### Requirement: Forecast layer uses current config, not a startup snapshot

The forecast layer SHALL run on the current on-disk configuration. The shared `LearningEngine` (obtained via `get_learning_engine()`) caches its parsed config; before each forecast generation it SHALL detect a change in `config.yaml`'s modification time and re-parse from disk when the mtime has changed, so that load, PV, and price forecasts — and all config-derived inputs (solar-array geometry, inverter limits, weather location, PV tuning) — reflect the latest saved values without requiring a process restart. Re-parsing SHALL be mtime-gated so an unchanged config incurs no repeated disk I/O.

#### Scenario: Config unchanged between forecast runs
- **WHEN** a forecast run starts
- **AND** `config.yaml` has not been modified since the engine last read it
- **THEN** the engine reuses its cached config without re-reading from disk

#### Scenario: Config edited after process startup
- **WHEN** the user changes an inverter limit (e.g. `system.inverter.max_ac_power_kw`) in `config.yaml` while the backend is running
- **AND** a forecast run starts after the change
- **THEN** the engine detects the changed mtime, re-parses the config
- **AND** the resulting forecast uses the new inverter limit, not the value present at startup

#### Scenario: Forecast layer and planner agree on config
- **WHEN** config is changed while the backend is running
- **AND** both a planner run and a forecast run occur afterwards
- **THEN** the forecast layer SHALL use the same current config values the planner uses
- **AND** no split-brain (planner-on-new, forecast-on-old) state occurs

### Requirement: Config save refreshes the forecast layer

Saving configuration through the API SHALL propagate the change to the forecast layer, not only the executor. After a successful config write, the `LearningEngine`'s cached config SHALL be invalidated or refreshed so the next forecast uses the saved values.

#### Scenario: Config saved through the UI/API
- **WHEN** a config save completes successfully via the config API
- **THEN** the executor reload is triggered as before
- **AND** the `LearningEngine` cached config is invalidated or refreshed
- **AND** the next forecast run reads the newly saved values
